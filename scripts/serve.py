"""Avvio locale o LAN con password facoltativa e un solo processo per archivio."""
import argparse
import ipaddress
import re
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn

from app.api import create_app
from app.workspace_lock import WorkspaceInUse, workspace_lock


def network_hosts():
    hosts = {socket.gethostname(), socket.gethostname().split('.')[0] + '.local'}
    try:
        hosts.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    if sys.platform == 'darwin':
        result = subprocess.run(['/sbin/ifconfig', '-a'], capture_output=True, text=True, timeout=5)
        for address in re.findall(r'\binet (\d+\.\d+\.\d+\.\d+)', result.stdout):
            if ipaddress.ip_address(address).is_private and not ipaddress.ip_address(address).is_loopback:
                hosts.add(address)
        result = subprocess.run(['/usr/sbin/scutil', '--get', 'LocalHostName'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and re.fullmatch(r'[a-zA-Z0-9-]+', result.stdout.strip()):
            hosts.add(result.stdout.strip() + '.local')
    return sorted(hosts - {'127.0.0.1'})


def main():
    parser = argparse.ArgumentParser(description='MiniMax H3 Compiler Lite — servizio M2')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1')
    parser.add_argument('--allowed-host', action='append', default=[])
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('La porta deve essere fra 1 e 65535.')
    directory = (args.data_dir or Path(__file__).resolve().parent.parent / 'data').resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lan = args.host == '0.0.0.0'
    try:
        with workspace_lock(directory):
            # Si passa a Uvicorn lo stesso socket verificato: nessuna finestra di gara.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                option = socket.SO_EXCLUSIVEADDRUSE if sys.platform == 'win32' else socket.SO_REUSEADDR
                listener.setsockopt(socket.SOL_SOCKET, option, 1)
                try:
                    listener.bind((args.host, args.port))
                except OSError:
                    parser.exit(1, f'Porta {args.port} non disponibile; scegliere un’altra porta.\n')
                listener.listen(128)
                hosts = [*network_hosts(), *args.allowed_host] if lan else args.allowed_host
                app = create_app(data_dir=directory, lan=lan, allowed_hosts=hosts)
                app.state.access.allowed_hosts = hosts
                config = uvicorn.Config(app, host=args.host, port=args.port, workers=1, access_log=False, log_level='warning')
                try:
                    uvicorn.Server(config).run(sockets=[listener])
                except KeyboardInterrupt:
                    pass
    except WorkspaceInUse:
        parser.exit(1, 'Un servizio usa già questo archivio. Fermarlo prima di riavviare.\n')


if __name__ == '__main__':
    main()
