"""LaunchAgent dedicato M2; non modifica altri servizi o impostazioni del Mac."""
import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from app.repository import Repository
from app.workspace_lock import WorkspaceInUse, workspace_lock

LABEL = 'it.local.minimax-h3-lite'


def main():
    parser = argparse.ArgumentParser(description='Installa/rimuove l’avvio di MiniMax H3 Lite al login')
    parser.add_argument('--remove', action='store_true')
    parser.add_argument('--local-only', action='store_true')
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('LaunchAgent disponibile solo su macOS.')
    if not 1 <= args.port <= 65535:
        parser.error('Porta non valida.')
    root = Path(__file__).resolve().parent.parent
    target = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
    if target.exists():
        with target.open('rb') as file:
            previous = plistlib.load(file)
        if previous.get('WorkingDirectory') != str(root):
            parser.error('Questa etichetta appartiene a un altro progetto: nessun servizio modificato.')
    domain = f'gui/{os.getuid()}'
    if args.remove:
        subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
        target.unlink(missing_ok=True)
        print('Avvio automatico rimosso. Archivio e media conservati.')
        return
    directory = root / 'data'
    # Non avviare una migrazione o marcare job interrotti mentre un altro
    # processo serve lo stesso archivio: il servizio va prima fermato.
    directory.mkdir(exist_ok=True, mode=0o700)
    try:
        with workspace_lock(directory):
            Repository(directory)
    except WorkspaceInUse:
        parser.error('Ferma il servizio in esecuzione prima di installare il LaunchAgent.')
    logs = directory / 'logs'; logs.mkdir(exist_ok=True, mode=0o700)
    target.parent.mkdir(parents=True, exist_ok=True)
    arguments = [str(root / '.venv/bin/python'), '-m', 'scripts.serve', '--port', str(args.port)]
    if not args.local_only:
        arguments += ['--host', '0.0.0.0']
    value = {'Label': LABEL, 'ProgramArguments': arguments, 'WorkingDirectory': str(root), 'RunAtLoad': True,
             'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 10, 'ProcessType': 'Background',
             'StandardOutPath': str(logs / 'service.out.log'), 'StandardErrorPath': str(logs / 'service.err.log'),
             'Umask': 0o077, 'EnvironmentVariables': {'PYTHONUNBUFFERED': '1'}}
    # Solo la nostra etichetta; nessun bootout di altre applicazioni.
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
    with target.open('wb') as file:
        os.chmod(target, 0o600)
        plistlib.dump(value, file)
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(target)], capture_output=True, text=True)
    if result.returncode:
        parser.exit(1, f'LaunchAgent scritto ma non avviato: {result.stderr.strip()}\n')
    print(f'Avvio al login installato: {target}')
    print(f'Apri http://127.0.0.1:{args.port}/ — Impostazioni utente mostra accesso e indirizzi dei PC.')


if __name__ == '__main__':
    main()
