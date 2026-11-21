"""Backup locale verificabile; il ripristino scrive solo in una cartella nuova."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.workspace_lock import WorkspaceInUse, workspace_lock


PAYLOADS = ('data', 'models', 'service')


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def files(root):
    if root.is_symlink():
        raise ValueError('Una cartella del backup non può essere un link simbolico.')
    result = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Link simbolico non ammesso nel backup: {path.relative_to(root)}')
        if path.is_file():
            result.append(path)
        elif not path.is_dir():
            raise ValueError(f'Elemento non regolare: {path.relative_to(root)}')
    return result


def payload_files(root):
    return [path for name in PAYLOADS if (root / name).exists() for path in files(root / name)]


def database_report(path, *, immutable=False):
    uri = path.resolve().as_uri() + '?mode=ro' + ('&immutable=1' if immutable else '')
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Controllo di integrità SQLite non superato.')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Il database contiene collegamenti relazionali non validi.')
        tables = {}
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            rows = sorted(db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
            content = json.dumps(rows, ensure_ascii=False, default=lambda item: {'bytes': item.hex()})
            tables[name] = {'rows': len(rows), 'sha256': hashlib.sha256(content.encode()).hexdigest()}
        active = sum(json.loads(row[0]).get('status') in {'queued', 'running'}
                     for table in ('jobs', 'assistance_jobs') if table in tables
                     for row in db.execute('SELECT data FROM ' + table))
        return {'tables': tables, 'active_jobs': active}


def verify_media(data):
    count = 0
    with closing(sqlite3.connect((data / 'workspace.sqlite3').resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('media', 'audio_media', 'video_media'):
            if table not in tables:
                continue
            for row in db.execute('SELECT * FROM ' + table):
                entries = [(row['relative_path'], row['sha256'])]
                if table == 'audio_media':
                    entries.append((row['preview_path'], row['preview_sha256']))
                elif table == 'video_media':
                    metadata = json.loads(row['data'])
                    entries += [(metadata[key + '_path'], metadata[key + '_sha256']) for key in ('poster', 'tail')]
                for relative, expected in entries:
                    path = data / relative
                    if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or not path.resolve().is_relative_to(data.resolve()):
                        raise ValueError('Un media usa un percorso esterno o un link simbolico.')
                    if not path.is_file() or sha256(path) != expected:
                        raise ValueError(f'Media mancante o diverso dall’originale: {relative}')
                    count += 1
    return count


def create(project, destination, service_plist=None, *, data_dir=None):
    project, destination = project.resolve(), destination.resolve()
    source_data = Path(data_dir) if data_dir is not None else project / 'data'
    if source_data.is_symlink():
        raise ValueError('La cartella dati non può essere un link simbolico.')
    data = source_data.resolve()
    if (destination.exists() or destination.is_relative_to(project) or project.is_relative_to(destination)
            or destination.is_relative_to(data) or data.is_relative_to(destination)):
        raise ValueError('Scegli una cartella nuova, esterna al progetto.')
    if not (data / 'workspace.sqlite3').is_file():
        raise ValueError('Database sorgente non trovato.')
    if data.is_symlink() or (data / 'service.lock').is_symlink():
        raise ValueError('La cartella dati e il lock non possono essere link simbolici.')
    try:
        with workspace_lock(data):
            return _copy_workspace(project, destination, service_plist, data)
    except WorkspaceInUse as error:
        raise ValueError('Ferma prima il servizio; il backup non interrompe lavori in corso.') from error


def _copy_workspace(project, destination, service_plist, data):
    before = database_report(data / 'workspace.sqlite3')
    if before['active_jobs']:
        raise ValueError('Lavori attivi nel database: attendi il loro completamento prima del backup.')
    sources = {'data': files(data)}
    # External per-user archives do not borrow weights from an unrelated code
    # checkout. Guided packages have no bundled ASR models.
    if data == project / 'data' and (project / 'models').exists():
        sources['models'] = files(project / 'models')
    if service_plist and (service_plist.is_symlink() or not service_plist.is_file()):
        raise ValueError('Configurazione del servizio non valida.')
    destination.mkdir(parents=True, mode=0o700)
    os.chmod(destination, 0o700)
    for name, paths in sources.items():
        source_root = data if name == 'data' else project / name
        for path in paths:
            relative = Path(name) / path.relative_to(source_root)
            if relative.as_posix() in {
                'data/workspace.sqlite3', 'data/workspace.sqlite3-wal',
                'data/workspace.sqlite3-shm', 'data/service.lock',
            }:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, target)
            os.chmod(target, 0o600)
            if sha256(path) != sha256(target):
                raise ValueError(f'Copia non corrispondente: {relative}')
    (destination / 'data').mkdir(exist_ok=True, mode=0o700)
    target_db = destination / 'data/workspace.sqlite3'
    with closing(sqlite3.connect((data / 'workspace.sqlite3').as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target_db)) as target:
            source.backup(target)
    os.chmod(target_db, 0o600)
    if database_report(target_db, immutable=True) != before or database_report(data / 'workspace.sqlite3') != before:
        raise ValueError('Il contenuto del database è cambiato durante la copia.')
    if service_plist:
        target = destination / 'service' / service_plist.name
        target.parent.mkdir(mode=0o700)
        shutil.copy2(service_plist, target)
        os.chmod(target, 0o600)
    manifest = {
        'format': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'project': str(project), 'database': before,
        'files': {path.relative_to(destination).as_posix(): {'bytes': path.stat().st_size, 'sha256': sha256(path)}
                  for path in payload_files(destination)},
    }
    manifest_path = destination / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(manifest_path, 0o600)
    return verify(destination)


def verify(backup):
    backup = backup.resolve()
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1:
        raise ValueError('Formato del manifesto non supportato.')
    actual = {path.relative_to(backup).as_posix(): path for path in payload_files(backup)}
    if set(actual) != set(manifest['files']):
        raise ValueError('L’elenco dei file differisce dal manifesto.')
    for relative, path in actual.items():
        expected = manifest['files'][relative]
        if path.stat().st_size != expected['bytes'] or sha256(path) != expected['sha256']:
            raise ValueError(f'Integrità del backup non superata: {relative}')
    if database_report(backup / 'data/workspace.sqlite3', immutable=True) != manifest['database']:
        raise ValueError('Il database non corrisponde al manifesto.')
    media = verify_media(backup / 'data')
    return {'verified': True, 'files': len(actual), 'bytes': sum(p.stat().st_size for p in actual.values()),
            'media_files_checked': media, 'tables': len(manifest['database']['tables'])}


def restore(backup, destination):
    backup, destination = backup.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(backup) or backup.is_relative_to(destination):
        raise ValueError('Il ripristino richiede una cartella nuova e separata dal backup.')
    report = verify(backup)
    destination.mkdir(parents=True, mode=0o700)
    os.chmod(destination, 0o700)
    for name in PAYLOADS:
        if (backup / name).exists():
            shutil.copytree(backup / name, destination / name)
    shutil.copy2(backup / 'manifest.json', destination / 'manifest.json')
    if verify(destination) != report:
        raise ValueError('La copia ripristinata non corrisponde al backup.')
    return report | {'restored': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create_parser = commands.add_parser('create')
    create_parser.add_argument('destination', type=Path)
    create_parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parent.parent)
    create_parser.add_argument('--service-plist', type=Path)
    create_parser.add_argument('--data-dir', type=Path, help='Archivio esterno usato dai pacchetti con avvio guidato')
    for name in ('verify', 'restore'):
        command = commands.add_parser(name)
        command.add_argument('backup', type=Path)
        if name == 'restore':
            command.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'create':
            report = create(args.project, args.destination, args.service_plist, data_dir=args.data_dir)
        elif args.command == 'verify':
            report = verify(args.backup)
        else:
            report = restore(args.backup, args.destination)
    except (ValueError, OSError, sqlite3.Error, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
