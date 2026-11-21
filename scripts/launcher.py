"""Guided bootstrap. No application dependencies are imported before setup."""
import argparse
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import venv
from pathlib import Path

from app.workspace_lock import WorkspaceInUse, workspace_lock

APP_NAME = 'MiniMax H3 Compiler Lite'
ROOT = Path(__file__).resolve().parent.parent


def default_data_dir(system=None, home=None, environ=None):
    system = system or platform.system()
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    if system == 'Darwin':
        base = home / 'Library' / 'Application Support'
    elif system == 'Windows':
        if not environ.get('LOCALAPPDATA'):
            raise ValueError('LOCALAPPDATA assente: impossibile trovare i dati personali.')
        base = Path(environ['LOCALAPPDATA'])
    else:
        raise ValueError('Questi pacchetti supportano solo Mac Apple Silicon e Windows 11 x64.')
    return base / APP_NAME / 'data'


def check_runtime(root=ROOT):
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Serve Python 3.12 a 64 bit. Installa Python 3.12 da https://www.python.org/downloads/.')
    system, machine = platform.system(), platform.machine().lower()
    target = {'Darwin': 'macos-arm64', 'Windows': 'windows-x64'}.get(system)
    if target is None or (system == 'Darwin' and machine != 'arm64') or (
        system == 'Windows' and (machine not in {'amd64', 'x86_64'} or sys.maxsize <= 2**32)
    ):
        raise ValueError('Usa Python nativo a 64 bit su Mac Apple Silicon o Windows x64; Rosetta non è supportato.')
    manifest = root / 'release-manifest.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8'))['platform'] != target:
        raise ValueError('Questo ZIP è destinato a un’altra piattaforma. Estrai il pacchetto corretto.')


def setup(root=ROOT):
    """Serialize setup and mark it complete only after pip has verified dependencies."""
    environment = root / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    lock = root / 'requirements.lock'
    fingerprint = hashlib.sha256(lock.read_bytes() + str(root.resolve()).encode()
                                 + sys.version.encode()).hexdigest()
    marker = environment / '.minimax-requirements.sha256'
    guard = root / '.bootstrap'
    guard.mkdir(exist_ok=True)
    with workspace_lock(guard):
        if python.is_file() and marker.is_file() and marker.read_text(encoding='utf-8') == fingerprint:
            return python
        print('Preparazione ambiente Python 3.12...', flush=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(environment)
        print('Installazione dipendenze da PyPI. Al primo avvio serve Internet.', flush=True)
        subprocess.run([str(python), '-X', 'utf8', '-m', 'pip', 'install',
                        '--disable-pip-version-check', '-r', str(lock)], cwd=root, check=True)
        subprocess.run([str(python), '-X', 'utf8', '-m', 'pip', 'check'], cwd=root, check=True)
        marker.write_text(fingerprint, encoding='utf-8')
    return python


def run_child(command):
    process = subprocess.Popen(command, cwd=ROOT)
    # The foreground child receives Ctrl+C too. Keep the bootstrap alive until
    # SQLite and the workspace lock have actually been closed by the child.
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return process.wait()
    finally:
        signal.signal(signal.SIGINT, previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Avvio guidato MiniMax H3 Compiler Lite')
    parser.add_argument('--data-dir', type=Path, help='Archivio separato per prove o ripristino')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--no-browser', action='store_true')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--backup', type=Path, metavar='CARTELLA_NUOVA')
    actions.add_argument('--verify-backup', type=Path, metavar='CARTELLA_BACKUP')
    args = parser.parse_args(argv)
    try:
        check_runtime()
        if not 1 <= args.port <= 65535:
            raise ValueError('La porta deve essere fra 1 e 65535.')
        directory = (args.data_dir or default_data_dir()).expanduser().resolve()
        print(f'{APP_NAME}\nDati: {directory}', flush=True)
        python = setup()
        if args.backup:
            command = ['-m', 'scripts.backup_workspace', 'create', str(args.backup), '--data-dir', str(directory)]
        elif args.verify_backup:
            command = ['-m', 'scripts.backup_workspace', 'verify', str(args.verify_backup)]
        else:
            command = ['-m', 'scripts.guided_server', '--port', str(args.port), '--data-dir', str(directory)]
            if args.no_browser:
                command.append('--no-browser')
        return run_child([str(python), '-X', 'utf8', *command])
    except WorkspaceInUse:
        print('Un altro avvio sta preparando questa cartella. Attendi e riprova.', file=sys.stderr)
    except subprocess.CalledProcessError:
        print('Installazione non completata. Controlla Internet e i messaggi qui sopra, poi riavvia.', file=sys.stderr)
    except KeyboardInterrupt:
        print('\nPreparazione interrotta. Puoi riavviare quando vuoi.', file=sys.stderr)
    except (ValueError, OSError) as error:
        print(f'Avvio non riuscito: {error}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
