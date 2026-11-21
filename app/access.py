"""Password LAN, sessioni opache e controllo delle richieste di modifica."""
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import time
from contextlib import closing
from pathlib import Path

from app.store import StoreError

COOKIE = 'h3_session'
SESSION_SECONDS = 12 * 60 * 60


def loopback(request):
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        return False


class Access:
    def __init__(self, repository, *, lan=False):
        self.repository = repository
        self.path = repository.directory / 'access.json'
        self.bootstrap = repository.directory / 'first-access.txt'
        self.lan = lan
        self.allowed_hosts = []
        self.lock = threading.RLock()
        self.failures = {}
        with closing(repository.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL)')

    def configured(self):
        return bool(self.configuration().get('key'))

    def configuration(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    def enabled(self):
        value = self.configuration()
        return value.get('enabled', bool(value.get('key')))

    def set_password(self, password, *, protect_all=False):
        if len(password) < 12 or len(password) > 256:
            raise StoreError('invalid_input', 'Usa una password da 12 a 256 caratteri.', 422)
        salt = secrets.token_hex(16)
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        temporary = self.path.with_suffix('.tmp')
        with self.lock:
            with temporary.open('w') as file:
                os.chmod(temporary, 0o600)
                json.dump({'salt': salt, 'key': key, 'enabled': True, 'protect_all': protect_all}, file)
                file.flush(); os.fsync(file.fileno())
            os.replace(temporary, self.path)
            with closing(self.repository.connect()) as db:
                db.execute('DELETE FROM sessions')
            self.bootstrap.unlink(missing_ok=True)

    def generate_initial_password(self):
        if self.path.exists():
            return
        password = secrets.token_urlsafe(18)
        self.set_password(password)
        with self.bootstrap.open('x') as file:
            os.chmod(self.bootstrap, 0o600)
            file.write(password)

    def session(self, request):
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        with closing(self.repository.connect()) as db:
            return db.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?',
                              (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()

    def status(self, request):
        session = self.session(request)
        local = loopback(request)
        config = self.configuration()
        required = self.enabled() and (config.get('protect_all', False) or self.lan and not local)
        return {'local': local, 'configured': self.configured(), 'lan_enabled': self.lan,
                'enabled': self.enabled(), 'protect_all': config.get('protect_all', False),
                'lan_urls': [f'http://{host}:{request.url.port or 80}/' for host in self.allowed_hosts] if local and self.lan else [],
                'authenticated': bool(session) or not required, 'authentication_required': required,
                'csrf': session['csrf'] if session else None}

    def authorize(self, request):
        if not self.status(request)['authentication_required']:
            return
        session = self.session(request)
        if session is None:
            raise StoreError('authentication_required', 'Accedi con la password del compilatore.', 401)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise StoreError('forbidden', 'Sessione da aggiornare: accedi di nuovo.', 403)

    def check_password(self, request, password):
        address = request.client.host
        with self.lock:
            failures = self.failures.setdefault(address, [])
            failures[:] = [t for t in failures if time.monotonic() - t < 60]
            if len(failures) >= 6:
                raise StoreError('too_many_attempts', 'Troppi tentativi. Attendi un minuto.', 429)
            failures.append(time.monotonic())
        if not self.configured():
            raise StoreError('not_configured', 'La password di accesso non è configurata.', 409)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(saved['salt']), n=16384, r=8, p=1).hex()
        if not hmac.compare_digest(key, saved['key']):
            raise StoreError('invalid_credentials', 'Password non corretta.', 401)
        with self.lock:
            self.failures.pop(address, None)

    def login(self, request, password, response):
        self.check_password(request, password)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with closing(self.repository.connect()) as db:
            db.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', max_age=SESSION_SECONDS,
                            secure=request.url.scheme == 'https', path='/')
        return {'authenticated': True, 'csrf': csrf}

    def change(self, request, command, response):
        with self.lock:
            if self.configured():
                self.check_password(request, command.current_password)
            if command.enabled:
                self.set_password(command.password, protect_all=True)
                value = self.login(request, command.password, response)
                return {**value, 'enabled': True, 'configured': True}
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w') as file:
                os.chmod(temporary, 0o600)
                json.dump({'enabled': False, 'protect_all': True}, file)
                file.flush(); os.fsync(file.fileno())
            os.replace(temporary, self.path)
            self.bootstrap.unlink(missing_ok=True)
            with closing(self.repository.connect()) as db:
                db.execute('DELETE FROM sessions')
            response.delete_cookie(COOKIE, path='/')
            return {'authenticated': True, 'csrf': None, 'enabled': False, 'configured': False}

    def logout(self, request, response):
        token = request.cookies.get(COOKIE, '')
        with closing(self.repository.connect()) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie(COOKIE, path='/')
        return {'authenticated': False}
