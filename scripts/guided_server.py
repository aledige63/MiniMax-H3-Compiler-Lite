"""Foreground loopback server for guided packages; opens the browser after startup."""
import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.api import create_app
from app.workspace_lock import WorkspaceInUse, workspace_lock


class GuidedServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            print(f'Pronto: {self.local_url}\nLascia aperta questa finestra. Per fermare premi Ctrl+C.', flush=True)
            if self.open_browser:
                threading.Thread(target=webbrowser.open, args=(self.local_url,), daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('La porta deve essere fra 1 e 65535.')
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with workspace_lock(directory):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                option = socket.SO_EXCLUSIVEADDRUSE if sys.platform == 'win32' else socket.SO_REUSEADDR
                listener.setsockopt(socket.SOL_SOCKET, option, 1)
                try:
                    listener.bind(('127.0.0.1', args.port))
                except OSError:
                    parser.exit(1, f'Porta {args.port} occupata o non disponibile. Chiudi l’altra copia oppure usa --port NUMERO.\n')
                listener.listen(128)
                app = create_app(data_dir=directory)
                server = GuidedServer(uvicorn.Config(app, workers=1, access_log=False, log_level='warning'))
                server.local_url = f'http://127.0.0.1:{args.port}/'
                server.open_browser = not args.no_browser
                server.run(sockets=[listener])
    except KeyboardInterrupt:
        print('\nServizio arrestato.', flush=True)
    except WorkspaceInUse:
        parser.exit(1, 'Un servizio usa già questo archivio. Fermalo prima di avviare questa copia.\n')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Avvio non riuscito: {error}\n')


if __name__ == '__main__':
    main()
