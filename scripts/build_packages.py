"""Build development ZIPs from this standalone source snapshot; original release ZIPs stay separate."""
import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'packaging/files.json'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def safe_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or str(path) != value:
        raise ValueError(f'Percorso non valido: {value}')
    forbidden = {'.git', '.venv', 'data', 'models', 'logs', 'benchmark-runs', 'fonti', 'allegati', '__pycache__'}
    if forbidden.intersection(path.parts) or path.suffix in {'.db', '.sqlite3', '.log', '.pyc', '.key', '.pem'}:
        raise ValueError(f'File non distribuibile: {value}')
    return value


def prepared_bytes(source):
    source = safe_path(source)
    path = ROOT / source
    if any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(ROOT)):
        raise ValueError(f'Link simbolico non ammesso: {source}')
    return path.read_bytes()


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError('CRC ZIP non valido.')
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('File duplicati nello ZIP.')
        manifests = [name for name in names if name.endswith('/release-manifest.json')]
        if len(manifests) != 1:
            raise ValueError('Manifesto ZIP assente o ambiguo.')
        prefix = manifests[0].removesuffix('release-manifest.json')
        manifest = json.loads(archive.read(manifests[0]))
        expected = {prefix + name for name in manifest['files']} | {manifests[0]}
        if set(names) != expected:
            raise ValueError('Il contenuto ZIP differisce dal manifesto.')
        for name, metadata in manifest['files'].items():
            safe_path(name)
            content = archive.read(prefix + name)
            if len(content) != metadata['bytes'] or digest(content) != metadata['sha256']:
                raise ValueError(f'Hash diverso: {name}')
        return manifest


def build(output):
    config_bytes = CONFIG.read_bytes()
    config = json.loads(config_bytes)
    version = config['version']
    if not re.fullmatch(r'[0-9A-Za-z.-]+', version):
        raise ValueError('Versione non valida.')
    commit = config['source_commit']  # Provenance only; no original Git history required.
    timestamp = config['source_timestamp']
    runtime_commit = None
    reference = json.loads(prepared_bytes(config['runtime_reference_ref']))
    if config['license'] != 'MIT' or config['copyright'] != 'Copyright (c) 2026 aledige':
        raise ValueError('Licenza o intestatario diversi dalla scelta concordata.')
    if set(config['documentation']) != {'it', 'en'}:
        raise ValueError('La documentazione deve essere disponibile in italiano e inglese.')
    stamp = datetime.fromtimestamp(timestamp, timezone.utc).timetuple()[:6]
    checkpoint = {}
    for name in config['checkpoint_files']:
        name = safe_path(name)
        if name in checkpoint:
            raise ValueError(f'File ripetuto: {name}')
        checkpoint[name] = prepared_bytes(name)
    platforms = config['platform_files']
    if set(platforms) != {'macos-arm64', 'windows-x64'}:
        raise ValueError('Il piano include soltanto Mac Apple Silicon e Windows x64.')
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for target in sorted(platforms):
        payload = dict(checkpoint)
        origins = {name: {'kind': 'checkpoint', 'path': name} for name in payload}
        overlays = {**config['prepared_files'], **platforms[target]}
        for source, name in overlays.items():
            name = safe_path(name)
            if name in payload:
                raise ValueError(f'Overlay ambiguo: {name}')
            content = prepared_bytes(source)
            if name.endswith('.cmd'):
                content = content.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            payload[name] = content
            origins[name] = {'kind': 'packaging-overlay', 'path': source}
        # Check the actual payload, not only its file names. Generic loopback
        # addresses are expected; personal home directories and LAN IPs are not.
        for name, content in payload.items():
            if re.search(rb'/Users/|192\.168\.\d+\.\d+|sk-(?:proj-)?[A-Za-z0-9_-]{24,}', content):
                raise ValueError(f'Possibile contenuto personale: {name}')
            if name.startswith(('app/', 'scripts/')) or name in {'start.py', 'requirements.lock'}:
                if digest(content) != reference.get(name):
                    raise ValueError(f'Il runtime differisce dal riferimento sorgenti: {name}')
            if name.endswith(('.cmd', '.command')):
                if digest(prepared_bytes(origins[name]['path'])) != reference.get(origins[name]['path']):
                    raise ValueError(f'L’avvio differisce dal riferimento sorgenti: {name}')
        if config['copyright'].encode() not in payload.get('LICENSE', b''):
            raise ValueError('Il pacchetto deve includere LICENSE intestata ad aledige.')
        if 'THIRD-PARTY-NOTICES.md' not in payload:
            raise ValueError('Mancano le note sui materiali esterni.')
        for documents in config['documentation'].values():
            for name in documents:
                if not payload.get(safe_path(name)):
                    raise ValueError(f'Documentazione mancante o vuota: {name}')
        manifest = {
            'format': 1, 'version': version, 'platform': target,
            'compiler_source_commit': commit, 'compiler_source_tag': config['source_ref'],
            'recipe_sha256': digest(config_bytes),
            'builder_sha256': digest(Path(__file__).read_bytes()),
            'stable_tag': config['stable_tag'],
            'runtime_reference_tag': config['runtime_reference_ref'],
            'runtime_reference_commit': runtime_commit,
            'runtime_matches_reference': True,
            'license': config['license'], 'copyright': config['copyright'],
            'documentation': config['documentation'],
            'distribution': 'MIT; source snapshot; development build; not the original tested release',
            'files': {name: {'sha256': digest(content), 'bytes': len(content), **origins[name]}
                      for name, content in sorted(payload.items())},
        }
        payload['release-manifest.json'] = encoded(manifest)
        stem = f'MiniMax-H3-Compiler-Lite-{version}-{target}'
        path = output / (stem + '.zip')
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, content in sorted(payload.items()):
                entry = zipfile.ZipInfo(stem + '/' + name, date_time=stamp)
                entry.create_system = 3
                mode = 0o100755 if name.endswith('.command') else 0o100644
                entry.external_attr = mode << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, content, compresslevel=9)
        verify_archive(path)
        packages.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes()),
                         'platform': target, 'payload_files': len(payload), 'verified_contents': True})
    (output / 'SHA256SUMS.txt').write_text(''.join(f"{p['sha256']}  {p['file']}\n" for p in packages), encoding='utf-8')
    report = {'format': 1, 'version': version, 'compiler_source_commit': commit,
              'compiler_source_tag': config['source_ref'], 'packages': packages,
              'stable_tag': config['stable_tag'], 'license': config['license'],
              'copyright': config['copyright'], 'documentation': config['documentation'],
              'runtime_reference_tag': config['runtime_reference_ref'],
              'runtime_reference_commit': runtime_commit, 'runtime_matches_reference': True,
              'notes': {'it': 'Hash e contenuti verificati; runtime conforme al riferimento sorgenti. Build di sviluppo, non nuovo collaudo nativo.',
                        'en': 'Hashes and contents verified; runtime matches source reference. Development build, not a new native acceptance test.'}}
    (output / 'PACCHETTI.json').write_bytes(encoded(report))
    for source, name in config['prepared_files'].items():
        if '/' not in name:
            (output / name).write_bytes(prepared_bytes(source))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        output = args.output or ROOT / 'dist' / json.loads(CONFIG.read_text(encoding='utf-8'))['version']
        report = build(output.resolve())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Confezionamento non riuscito: {error}\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
