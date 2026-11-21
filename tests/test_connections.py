import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import create_app
from app.connections import Connections, OpenAIClient, ollama_url, strict_schema
from app.domain import CompileInput
from app.interpreter import OllamaClient, OllamaError, input_hash
from app.narrative import response_schema
from app.repository import Repository
from app.store import StoreError
from test_picture_registry import catalogue_input


class Provider(OllamaClient):
    def __init__(self):
        self.keep_alive = '0'
        self.calls = []
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.available = True

    def models(self):
        if not self.available:
            raise OllamaError('service_unreachable')
        return [{'name': 'shared', 'digest': 'same-digest'}]

    def _request(self, path, payload):
        if path == '/api/show':
            return {'capabilities': ['completion', 'vision']}
        assert path == '/api/chat'
        self.calls.append(copy.deepcopy(payload))
        self.entered.set(); self.release.wait(timeout=4)
        properties = payload['format'].get('properties', {})
        if 'red_square' in properties:
            value = {'red_square': True, 'blue_circle': True}
        elif 'ok' in properties:
            value = {'ok': True}
        elif 'description' in properties:
            value = {'description': 'a blue ceramic cup'}
        else:
            value = {'narrative_parts': [{'action_en': '<Subject 1> looks at the camera.'}],
                     'summary_en': '<Subject 1> looks at the camera.', 'estimated_duration_s': 4.0, 'question': None}
        return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(value)}}


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.providers = {'ollama': Provider(), 'openai': Provider()}
        self.app = create_app(self.temp.name, connection_factory=lambda service, config: self.providers[service])
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8767')
        self.client.__enter__()

    def tearDown(self):
        for provider in self.providers.values(): provider.release.set()
        self.app.state.worker.pending.join()
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def save(self, **updates):
        current = self.client.get('/api/connections').json()
        body = {'command_id': str(uuid4()), 'expected_revision': current['revision'],
                'ollama_url': 'http://ollama-one.local:11434', 'api_key': 'test-api-secret-value', **updates}
        return self.client.put('/api/connections', json=body)

    def trial(self, kind='vision', model='shared'):
        response = self.client.post('/api/connections/trials', json={'kind': kind, 'model': model})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def completed(self, job):
        self.app.state.worker.pending.join()
        return self.client.get('/api/connections/trials/' + job['id']).json()

    def test_fresh_models_are_unselected_and_compile_without_text_model_creates_no_job(self):
        self.assertEqual(self.client.get('/api/assistance/settings').json(),
                         {'revision': 0, 'text_model': '', 'vision_model': None})
        self.assertEqual(self.client.get('/api/health').json()['default_model'], '')
        cut = self.client.get('/api/workspace').json()
        response = self.client.post(f'/api/cuts/{cut["id"]}/compile', json={
            'command_id': str(uuid4()), 'expected_revision': cut['revision'], 'cut_id': cut['id'],
            'input': {'request': 'Una stanza vuota.', 'pictures': [], 'declared_duration_s': 5.0}})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()['detail']['code'], 'text_model_required')
        self.assertEqual(self.client.get('/api/workspace').json(), cut)
        with closing(self.app.state.repository.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.assertTrue(all(not provider.calls for provider in self.providers.values()))

    def test_fresh_install_has_no_personal_url_and_key_is_redacted_idempotent_and_removable(self):
        self.assertEqual(self.client.get('/api/connections').json()['ollama_url'], '')
        body = {'command_id': str(uuid4()), 'expected_revision': 0, 'ollama_url': 'http://server.local:11434', 'api_key': 'test-secret-value'}
        first = self.client.put('/api/connections', json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.client.put('/api/connections', json=body).json(), first.json())
        self.assertNotIn('test-secret-value', self.client.get('/api/connections').text)
        with closing(self.app.state.repository.connect()) as db:
            self.assertNotIn('test-secret-value', str([tuple(r) for r in db.execute('SELECT * FROM commands')]))
        self.assertEqual(self.providers['ollama'].calls, [])
        self.assertEqual(self.providers['openai'].calls, [])
        self.assertEqual(self.save(api_key=None).status_code, 200)
        self.assertTrue(self.client.get('/api/connections').json()['openai_key_set'])
        self.assertEqual(self.save(api_key=None, remove_api_key=True).status_code, 200)
        self.assertFalse(self.client.get('/api/connections').json()['openai_key_set'])

    def test_model_identities_trials_and_cache_are_separate_between_services_and_endpoints(self):
        self.save()
        models = self.client.get('/api/assistance/models').json()
        self.assertEqual({m['name'] for m in models}, {'shared', 'openai::shared'})
        self.assertEqual(len({m['digest'] for m in models}), 2)
        self.assertEqual(self.completed(self.trial())['status'], 'succeeded')
        models = self.client.get('/api/assistance/models').json()
        self.assertTrue(next(m for m in models if m['name'] == 'shared')['vision_tested'])
        self.assertFalse(next(m for m in models if m['name'] == 'openai::shared')['vision_tested'])
        before = next(m['digest'] for m in models if m['name'] == 'shared')
        self.save(ollama_url='http://ollama-two.local:11434')
        models = self.client.get('/api/assistance/models').json()
        after = next(m for m in models if m['name'] == 'shared')
        self.assertNotEqual(before, after['digest'])
        self.assertFalse(after['vision_tested'])
        self.assertEqual(len(self.providers['ollama'].calls), 1)

    def test_queue_blocks_connection_and_selection_changes_and_tests_need_no_cut(self):
        self.save()
        self.providers['openai'].release.clear()
        job = self.trial('text', 'openai::shared')
        self.assertTrue(self.providers['openai'].entered.wait(timeout=2))
        self.assertEqual(self.save(ollama_url='http://another.local').status_code, 409)
        response = self.client.put('/api/assistance/settings', json={'command_id': str(uuid4()), 'expected_revision': 0,
            'text_model': 'shared', 'vision_model': 'openai::shared'})
        self.assertEqual(response.status_code, 409)
        self.providers['openai'].release.set()
        self.assertEqual(self.completed(job)['status'], 'succeeded')
        self.assertEqual(len(self.providers['openai'].calls), 1)
        self.assertEqual(self.providers['ollama'].calls, [])

    def test_vision_required_and_independent_provider_selection_persists(self):
        self.save()
        body = {'command_id': str(uuid4()), 'expected_revision': 0, 'text_model': 'shared', 'vision_model': None}
        self.assertEqual(self.client.put('/api/assistance/settings', json=body).status_code, 422)
        body.update(command_id=str(uuid4()), vision_model='openai::shared')
        self.assertEqual(self.client.put('/api/assistance/settings', json=body).status_code, 200)
        self.assertEqual(self.client.get('/api/assistance/settings').json()['vision_model'], 'openai::shared')
        router = self.app.state.connections
        result = router.compile(CompileInput.model_validate(catalogue_input()), 'shared')
        self.assertEqual(result.status, 'proposal', result.issues)
        self.assertEqual(result.input_hash, input_hash(CompileInput.model_validate(catalogue_input())))
        self.assertEqual(len(self.providers['ollama'].calls), 1)
        self.assertEqual(self.providers['openai'].calls, [])

    def test_service_failure_never_falls_back_and_saved_models_remain_available_to_editor(self):
        self.save()
        self.providers['openai'].available = False
        result = self.app.state.connections.compile(CompileInput.model_validate(catalogue_input()), 'openai::shared')
        self.assertEqual(result.status, 'error')
        self.assertEqual(self.providers['ollama'].calls, [])
        self.assertEqual(self.client.get('/api/projects').status_code, 200)
        self.assertEqual(self.client.get('/api/connections/models/openai').status_code, 503)

    def test_existing_local_configuration_and_vision_proof_migrate_without_rewriting_original(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(directory)
            with repository.transaction() as db:
                db.execute("INSERT INTO settings VALUES ('models',?)", (json.dumps({'revision': 4, 'text_model': 'old-text', 'vision_model': 'old-vision'}),))
                db.execute('INSERT INTO vision_trials VALUES (?,?,?)', ('original-digest', 'old-vision', '{}'))
            router = Connections(repository)
            self.assertEqual(router.settings()['ollama_url'], 'http://127.0.0.1:11434')
            from app.assistance import Assistance
            self.assertEqual(Assistance(repository, router, None, None).settings(),
                             {'revision': 4, 'text_model': 'old-text', 'vision_model': 'old-vision'})
            with closing(repository.connect()) as db:
                self.assertEqual(json.loads(db.execute("SELECT value FROM settings WHERE key='models'").fetchone()[0])['revision'], 4)
                self.assertEqual(db.execute('SELECT count(*) FROM vision_trials').fetchone()[0], 2)
            Connections(repository)
            with closing(repository.connect()) as db: self.assertEqual(db.execute('SELECT count(*) FROM vision_trials').fetchone()[0], 2)

    def test_bad_urls_conflicting_key_operations_and_stale_revisions_are_rejected(self):
        for value in ['file:///tmp/x', 'http://user:pass@server', 'http://server/path', 'http://server?token=x', 'http://server:99999']:
            with self.assertRaises(StoreError): ollama_url(value)
        self.assertEqual(ollama_url(' https://server.local:11434/ '), 'https://server.local:11434')
        self.assertEqual(self.save(remove_api_key=True).status_code, 422)
        self.save()
        self.assertEqual(self.client.put('/api/connections', json={'command_id': str(uuid4()), 'expected_revision': 0,
            'ollama_url': 'http://new.local'}).status_code, 409)


class OpenAITransportTests(unittest.TestCase):
    def test_compile_reuses_renderer_and_validation_with_one_responses_call(self):
        client = OpenAIClient('test-private-key')
        plan = {'narrative_parts': [{'action_en': '<Subject 1> looks at the camera.'}],
                'summary_en': '<Subject 1> looks at the camera.', 'estimated_duration_s': 4.0, 'question': None}
        data = CompileInput.model_validate(catalogue_input())
        with patch.object(client, '_http', side_effect=[{'data': [{'id': 'chosen-model', 'created': 1}]},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(plan)}]}]}]) as http:
            result = client.compile(data, 'chosen-model')
        self.assertEqual(result.status, 'proposal', result.issues)
        self.assertTrue(result.structural_checks_passed)
        self.assertEqual(result.metrics.inference_calls, 1)
        self.assertEqual([c.args[0] for c in http.call_args_list], ['/models', '/responses'])
        sent = http.call_args_list[-1].args[1]
        self.assertEqual(sent['text']['format']['schema']['type'], 'object')
        self.assertNotIn('input_image', json.dumps(sent))
        self.assertIn('<Subject 1>', result.prompt)

    def test_schema_is_root_object_required_nullable_and_keeps_original_untouched(self):
        original = response_schema(CompileInput.model_validate(catalogue_input()))
        saved = copy.deepcopy(original)
        converted = strict_schema(original)
        self.assertEqual(original, saved)
        self.assertEqual(converted['type'], 'object')
        self.assertNotIn('anyOf', converted)
        def check(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    self.assertIs(value['additionalProperties'], False)
                    self.assertEqual(set(value['required']), set(value['properties']))
                for child in value.values(): check(child)
            elif isinstance(value, list):
                for child in value: check(child)
        check(converted)

    def test_responses_request_has_inline_image_strict_schema_no_storage_and_one_call(self):
        client = OpenAIClient('test-private-key')
        response = {'status': 'completed', 'output': [{'type': 'reasoning'}, {'type': 'message',
            'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}], 'usage': {'input_tokens': 20, 'output_tokens': 3}}
        with patch.object(client, '_http', return_value=response) as call:
            normalized = client._request('/api/chat', {'model': 'chosen-model', 'messages': [{'role': 'user', 'content': 'Look.', 'images': ['YWJj']}],
                'format': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}, 'options': {'num_predict': 4096}})
        self.assertEqual(call.call_count, 1)
        path, payload = call.call_args.args
        self.assertEqual(path, '/responses'); self.assertIs(payload['store'], False)
        self.assertEqual(payload['input'][0]['content'][1]['image_url'], 'data:image/jpeg;base64,YWJj')
        self.assertNotIn('test-private-key', json.dumps(payload))
        self.assertIs(payload['text']['format']['strict'], True)
        self.assertEqual(normalized['prompt_eval_count'], 20)

    def test_refusal_incomplete_and_http_errors_are_explicit_without_secret_bodies_or_retry(self):
        client = OpenAIClient('test-private-key')
        payload = {'model': 'chosen-model', 'messages': [], 'format': {'type': 'object', 'properties': {}}, 'options': {'num_predict': 4096}}
        for response, code in [({'status': 'incomplete'}, 'truncated_response'),
            ({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'PRIVATE'}]}]}, 'model_refusal')]:
            with patch.object(client, '_http', return_value=response) as call:
                with self.assertRaises(OllamaError) as raised: client._request('/api/chat', payload)
                self.assertEqual(raised.exception.code, code); self.assertNotIn('PRIVATE', str(raised.exception))
                self.assertEqual(call.call_count, 1)
        with patch('urllib.request.OpenerDirector.open', side_effect=urllib.error.HTTPError('https://api.openai.com', 401, 'private', {}, None)) as call:
            with self.assertRaises(OllamaError) as raised: client.models()
            self.assertEqual(raised.exception.code, 'invalid_credentials'); self.assertEqual(call.call_count, 1)


class OptionalAccessTests(unittest.TestCase):
    def test_enable_change_disable_protects_local_api_and_revokes_other_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            with TestClient(app, base_url='http://127.0.0.1:8767') as owner:
                self.assertEqual(owner.get('/api/projects').status_code, 200)
                enabled = owner.put('/api/access/settings', json={'enabled': True, 'password': 'first-password-long'})
                self.assertEqual(enabled.status_code, 200, enabled.text)
                csrf = enabled.json()['csrf']
                other = TestClient(app, base_url='http://127.0.0.1:8767')
                for path in ['/api/projects', '/api/health', '/api/connections', '/api/access/bootstrap']:
                    self.assertEqual(other.get(path).status_code, 401)
                self.assertEqual(other.get('/').status_code, 200)
                login = other.post('/api/access/login', json={'password': 'first-password-long'})
                self.assertEqual(login.status_code, 200)
                self.assertEqual(owner.put('/api/access/settings', json={'enabled': False}).status_code, 403)
                headers = {'X-CSRF-Token': csrf}
                self.assertEqual(owner.put('/api/access/settings', headers=headers,
                    json={'enabled': False, 'current_password': 'wrong'}).status_code, 401)
                changed = owner.put('/api/access/settings', headers=headers, json={'enabled': True,
                    'current_password': 'first-password-long', 'password': 'second-password-long'})
                self.assertEqual(changed.status_code, 200, changed.text)
                self.assertEqual(other.get('/api/projects').status_code, 401)
                stored = Path(directory, 'access.json').read_text()
                self.assertNotIn('first-password-long', stored); self.assertNotIn('second-password-long', stored)
                disabled = owner.put('/api/access/settings', headers={'X-CSRF-Token': changed.json()['csrf']},
                    json={'enabled': False, 'current_password': 'second-password-long'})
                self.assertEqual(disabled.status_code, 200, disabled.text)
                self.assertEqual(other.get('/api/projects').status_code, 200)
                self.assertFalse(other.get('/api/access/status').json()['enabled'])

    def test_password_optional_on_lan_and_short_password_does_not_change_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, lan=True, allowed_hosts=['host.local'])
            with TestClient(app, base_url='http://host.local:8767', client=('10.0.0.50', 5000)) as client:
                self.assertEqual(client.get('/api/projects').status_code, 200)
                self.assertEqual(client.put('/api/access/settings', json={'enabled': True, 'password': 'short'}).status_code, 422)
                self.assertFalse(client.get('/api/access/status').json()['enabled'])
                access = app.state.access
                response = client.put('/api/access/settings', json={'enabled': False})
                self.assertEqual(response.status_code, 200)
                access.generate_initial_password()
                self.assertFalse(access.enabled())
