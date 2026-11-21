"""Connessioni private, routing esplicito e verifiche senza dati dei progetti."""
import copy
import hashlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from urllib.parse import urlsplit
from uuid import uuid4

from app.interpreter import OllamaClient, OllamaError, PUBLIC_ERRORS
from app.store import StoreError, digest

OPENAI_URL = 'https://api.openai.com/v1'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ollama_url(value):
    value = value.strip().rstrip('/')
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path or (port is not None and not 1 <= port <= 65535) or
                any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError()
    except ValueError:
        raise StoreError('invalid_input', 'Inserisci l’indirizzo HTTP o HTTPS del server Ollama, con eventuale porta e senza percorsi o credenziali.', 422) from None
    return value


def strict_schema(source):
    """Schema OpenAI a radice object; esclusività verificata dal DTO originale."""
    source = copy.deepcopy(source)
    if 'anyOf' in source and 'type' not in source:
        branches = source.pop('anyOf')
        names = list(branches[0]['properties'])
        source.update(type='object', additionalProperties=False, required=names,
                      properties={name: {'anyOf': [branch['properties'][name] for branch in branches]} for name in names})
    def visit(node):
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        result = {key: ({name: visit(schema) for name, schema in value.items()} if key in {'properties', '$defs'} else visit(value))
                  for key, value in node.items() if key not in {
            'default', 'title', 'minLength', 'maxLength', 'pattern', 'minimum', 'maximum',
            'exclusiveMinimum', 'exclusiveMaximum', 'minItems', 'maxItems', 'format'}}
        if result.get('type') == 'object':
            props = result.setdefault('properties', {})
            required = result.get('required', [])
            for key in props:
                if key not in required:
                    props[key] = {'anyOf': [props[key], {'type': 'null'}]}
            result.update(required=list(props), additionalProperties=False)
        return result
    return visit(source)


class OpenAIClient(OllamaClient):
    """Responses API; normalizza solo il trasporto, conserva DTO e renderer."""
    def __init__(self, api_key, timeout_s=120):
        self.api_key, self.timeout_s, self.keep_alive = api_key, timeout_s, '0'

    def _http(self, path, payload=None):
        if not self.api_key:
            raise OllamaError('service_unconfigured')
        req = urllib.request.Request(OPENAI_URL + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json'})
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(req, timeout=self.timeout_s) as response:
                value = json.load(response)
                if not isinstance(value, dict):
                    raise OllamaError('invalid_response')
                return value
        except urllib.error.HTTPError as exc:
            # Non propagare corpo, header o chiave nelle risposte/log.
            code = {401: 'invalid_credentials', 403: 'invalid_credentials', 404: 'model_unavailable',
                    429: 'rate_limited'}.get(exc.code, 'http_error')
            raise OllamaError(code) from None
        except (TimeoutError, socket.timeout):
            raise OllamaError('timeout') from None
        except urllib.error.URLError as exc:
            raise OllamaError('timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'service_unreachable') from None
        except (ValueError, UnicodeError):
            raise OllamaError('invalid_response') from None

    def models(self):
        values = self._http('/models').get('data')
        if not isinstance(values, list) or any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in values):
            raise OllamaError('invalid_response')
        return [{'name': v['id'], 'digest': digest({'service': OPENAI_URL, 'id': v['id'], 'created': v.get('created')})} for v in values]

    def _request(self, path, payload=None):
        if path == '/api/show':
            # /models non dichiara le modalità: sono candidati, da provare.
            return {'capabilities': ['completion', 'vision'], 'capabilities_unknown': True}
        if path != '/api/chat':
            raise OllamaError('invalid_response')
        messages = []
        for message in payload['messages']:
            parts = [{'type': 'input_text', 'text': message['content']}]
            parts += [{'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + image} for image in message.get('images', [])]
            messages.append({'role': message['role'], 'content': parts})
        response = self._http('/responses', {
            'model': payload['model'], 'input': messages, 'store': False,
            'max_output_tokens': max(4096, payload['options']['num_predict']),
            'text': {'format': {'type': 'json_schema', 'name': 'compiler_response',
                                'strict': True, 'schema': strict_schema(payload['format'])}}})
        if response.get('status') == 'incomplete':
            raise OllamaError('truncated_response')
        if response.get('status') != 'completed' or not isinstance(response.get('output'), list):
            raise OllamaError('invalid_response')
        texts = []
        for item in response['output']:
            if item.get('type') != 'message':
                continue
            for part in item.get('content', []):
                if part.get('type') == 'refusal':
                    raise OllamaError('model_refusal')
                if part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                    texts.append(part['text'])
        if len(texts) != 1:
            raise OllamaError('invalid_response')
        usage = response.get('usage') or {}
        return {'done': True, 'done_reason': 'stop', 'message': {'content': texts[0]},
                'prompt_eval_count': usage.get('input_tokens'), 'eval_count': usage.get('output_tokens')}


class Connections:
    keep_alive = '5m'

    def __init__(self, repository, *, factory=None):
        self.repository, self.factory = repository, factory
        self.lock = threading.RLock()
        self.errors = {}
        with repository.transaction() as db:
            if not db.execute("SELECT 1 FROM settings WHERE key='connections'").fetchone():
                existing = db.execute("SELECT value FROM settings WHERE key='models'").fetchone()
                url = 'http://127.0.0.1:11434' if existing else ''
                db.execute("INSERT INTO settings VALUES ('connections',?)", (json.dumps({
                    'revision': 0, 'ollama_url': url, 'api_key': '', 'timeout_s': 120}),))
                # Le prove pregresse appartengono solo al server locale originario.
                if url:
                    for row in db.execute('SELECT * FROM vision_trials').fetchall():
                        db.execute('INSERT OR IGNORE INTO vision_trials VALUES (?,?,?)',
                            (self.scoped_digest('ollama', url, row['digest']), row['model'], row['data']))
            for row in db.execute("SELECT key,value FROM settings WHERE key LIKE 'connection_trial:%'").fetchall():
                value = json.loads(row['value'])
                if value['status'] in {'queued', 'running'}:
                    value.update(status='failed', message='Verifica interrotta dal riavvio. Riprova esplicitamente.')
                    db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(value), row['key']))

    @staticmethod
    def scoped_digest(service, url, model_digest):
        return digest({'service': service, 'url': url, 'digest': model_digest})

    def private(self):
        with closing(self.repository.connect()) as db:
            return json.loads(db.execute("SELECT value FROM settings WHERE key='connections'").fetchone()[0])

    def settings(self):
        value = self.private()
        return {key: value[key] for key in ['revision', 'ollama_url', 'timeout_s']} | {'openai_key_set': bool(value['api_key']), 'openai_url': OPENAI_URL}

    def save(self, command):
        url = ollama_url(command.ollama_url)
        key = command.api_key
        if key is not None and command.remove_api_key:
            raise StoreError('invalid_input', 'Scegli se sostituire o rimuovere la chiave API.', 422)
        if key is not None and (not key.strip() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key)):
            raise StoreError('invalid_input', 'Inserisci una chiave API valida oppure usa Rimuovi chiave.', 422)
        def action(db):
            value = json.loads(db.execute("SELECT value FROM settings WHERE key='connections'").fetchone()[0])
            if command.expected_revision != value['revision']:
                raise StoreError('revision_conflict', 'Le connessioni sono cambiate. Ricarica le impostazioni.', 409)
            value.update(revision=value['revision'] + 1, ollama_url=url, timeout_s=command.timeout_s)
            if command.remove_api_key:
                value['api_key'] = ''
            elif key is not None:
                value['api_key'] = key
            db.execute("UPDATE settings SET value=? WHERE key='connections'", (json.dumps(value),))
            return {k: value[k] for k in ['revision', 'ollama_url', 'timeout_s']} | {'openai_key_set': bool(value['api_key']), 'openai_url': OPENAI_URL}
        return self.repository._entity_command('connections', 'connections', command, action)

    @staticmethod
    def split(model):
        return ('openai', model[len('openai::'):]) if model.startswith('openai::') else ('ollama', model)

    def client(self, service):
        value = self.private()
        if service == 'ollama':
            if not value['ollama_url']:
                raise OllamaError('service_unconfigured')
            client = OllamaClient(value['ollama_url'], value['timeout_s'], remote=True)
            # I redirect non possono cambiare il destinatario configurato.
        elif service == 'openai':
            if not value['api_key']:
                raise OllamaError('service_unconfigured')
            client = OpenAIClient(value['api_key'], value['timeout_s'])
        else:
            raise OllamaError('service_unconfigured')
        return self.factory(service, value) if self.factory else client

    def service_models(self, service):
        client = self.client(service)
        value = self.private()
        url = value['ollama_url'] if service == 'ollama' else OPENAI_URL
        result = []
        for model in client.models():
            name = model['name']
            try:
                info = client._request('/api/show', {'model': name})
            except OllamaError:
                info = {'capabilities': []}
            result.append({'name': 'openai::' + name if service == 'openai' else name,
                'label': name, 'service': service,
                'digest': self.scoped_digest(service, url, model['digest']),
                'capabilities': info.get('capabilities', []),
                'capabilities_unknown': info.get('capabilities_unknown', False)})
        return result

    def models(self):
        result = []
        for service in ['ollama', 'openai']:
            try:
                result.extend(self.service_models(service))
                self.errors.pop(service, None)
            except OllamaError as exc:
                self.errors[service] = PUBLIC_ERRORS.get(exc.code, 'Connessione non disponibile.')
        return result

    def _request(self, path, payload):
        service, model = self.split(payload['model'])
        return self.client(service)._request(path, {**payload, 'model': model})

    def compile(self, data, model):
        from app.domain import CompileResult
        from app.interpreter import input_hash
        service, raw_model = self.split(model)
        try:
            client = self.client(service)
            result = client.compile(data, raw_model)
            if result.metrics:
                value = self.private()
                url = value['ollama_url'] if service == 'ollama' else OPENAI_URL
                result = result.model_copy(update={'metrics': result.metrics.model_copy(update={
                    'model': model, 'digest': self.scoped_digest(service, url, result.metrics.digest)})})
            return result
        except OllamaError as exc:
            return CompileResult(status='error', input_hash=input_hash(data), error_code=exc.code,
                                 issues=[PUBLIC_ERRORS.get(exc.code, 'Servizio non disponibile.')])

    def create_trial(self, command):
        from app.analysis import installed_model
        capability = 'vision' if command.kind == 'vision' else 'completion'
        try:
            model = installed_model(self, command.model, capability)
        except OllamaError as exc:
            raise StoreError(exc.code, PUBLIC_ERRORS.get(exc.code, 'Modello non disponibile per questa funzione.'), 422) from None
        value = {'id': str(uuid4()), 'kind': command.kind, 'model': command.model, 'digest': model['digest'], 'status': 'queued'}
        with self.repository.transaction() as db:
            db.execute('INSERT INTO settings VALUES (?,?)', ('connection_trial:' + value['id'], json.dumps(value)))
        return value

    def trial(self, id):
        with closing(self.repository.connect()) as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', ('connection_trial:' + str(id),)).fetchone()
        if row is None:
            raise StoreError('not_found', 'Verifica non trovata.', 404)
        return json.loads(row[0])

    def run_trial(self, id, queue_s):
        from app.analysis import infer, installed_model
        from app.interpreter import INFERENCE_LOCK
        value = self.trial(id)
        value['status'] = 'running'
        self._write_trial(value)
        try:
            current = installed_model(self, value['model'], 'vision' if value['kind'] == 'vision' else 'completion')
            if current['digest'] != value['digest']:
                raise OllamaError('model_unavailable')
            if value['kind'] == 'vision':
                result = infer(self, 'vision_trial', value['model'], value['digest'], digest(value))
                value['metrics'] = result.metrics.model_dump(mode='json')
                if result.status == 'error':
                    raise OllamaError(result.metrics.error_code)
                with self.repository.transaction() as db:
                    db.execute('INSERT OR REPLACE INTO vision_trials VALUES (?,?,?)', (value['digest'], value['model'], result.model_dump_json()))
            else:
                schema = {'type': 'object', 'additionalProperties': False,
                          'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}
                with INFERENCE_LOCK:
                    value['inference_calls'] = 1
                    response = self._request('/api/chat', {'model': value['model'], 'stream': False, 'think': False,
                        'keep_alive': self.keep_alive, 'messages': [{'role': 'user', 'content': 'Return JSON with exactly one boolean field ok set to true.'}],
                        'format': schema, 'options': {'num_ctx': 8192, 'num_predict': 4096, 'temperature': 0}})
                if response.get('done') is not True or response.get('done_reason') == 'length':
                    raise OllamaError('truncated_response')
                if json.loads(response['message']['content']) != {'ok': True}:
                    raise OllamaError('invalid_response')
            value.update(status='succeeded', message='Verifica riuscita.', queue_s=queue_s)
        except Exception as exc:
            value.update(status='failed', message=PUBLIC_ERRORS.get(getattr(exc, 'code', ''), 'Verifica non riuscita. Il modello non ha superato la prova richiesta.'))
        self._write_trial(value)

    def _write_trial(self, value):
        with self.repository.transaction() as db:
            db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(value), 'connection_trial:' + value['id']))
