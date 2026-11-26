"""Schede oggetto sintetiche e client simulati: nessun file o modello utente."""
import io
import json
import unittest
from unittest.mock import Mock

from PIL import Image, ImageDraw

from app.analysis import encoded_image, infer
from app.image_profiles import DEFAULTS, LEVELS, OBJECT_SHEET_INSTRUCTION, analysis_instruction
import test_m3 as m3


def object_sheet():
    image = Image.new('RGB', (1500, 1000), 'white')
    draw = ImageDraw.Draw(image)
    # Stesso veicolo: silhouette, fronte/retro e dettaglio in basso.
    for x, y in [(20, 20), (770, 20), (20, 520), (770, 520)]:
        draw.rounded_rectangle((x+30, y+90, x+680, y+340), 35, fill='#556475')
        draw.rectangle((x+140, y+105, x+560, y+205), fill='#27313b')
        for wheel_x in [x+160, x+550]:
            draw.ellipse((wheel_x-55, y+285, wheel_x+55, y+395), fill='#151515')
    draw.rectangle((1200, 860, 1420, 950), fill='#d22c26')
    draw.text((1220, 890), 'RIVER 4', fill='white')
    output = io.BytesIO(); image.save(output, format='PNG')
    return output.getvalue()


class ObjectSheetTests(unittest.TestCase):
    def response(self, description):
        client = Mock(keep_alive='0')
        client._request.return_value = dict(done=True, done_reason='stop',
            message=dict(content=json.dumps(dict(description=description))))
        result = infer(client, 'image_object_sheet', 'vision-test', 'digest', 'hash',
            role='object', content=object_sheet(), analysis=dict(DEFAULTS, category='held_item', level='medium'))
        return result, client

    def test_object_prompt_consolidates_all_regions_at_every_level_without_character_instructions(self):
        for level in LEVELS:
            with self.subTest(level=level):
                prompt = analysis_instruction(dict(DEFAULTS, category='held_item', level=level), '', object_sheet=True)
                self.assertTrue(prompt.startswith(OBJECT_SHEET_INSTRUCTION))
                for text in ['ONE object', 'not separate objects', 'ALL visible regions', 'lower rows',
                             'no fixed panel count', 'wheels, lights', 'exact spelling', 'its actual part']:
                    self.assertIn(text, prompt)
                self.assertNotIn('ONE person', prompt)
                self.assertNotIn('wearer’s anatomical', prompt)
                self.assertNotIn('portrait of the person', prompt)
        ordinary = analysis_instruction(dict(DEFAULTS, category='held_item'), '', object_sheet=False)
        self.assertNotIn(OBJECT_SHEET_INSTRUCTION, ordinary)

    def test_one_full_image_one_call_and_physical_parts_are_not_layout_commentary(self):
        description = 'A grey SUV has dark windows, rear view mirrors, black wheels and red rear lights, with "RIVER 4" lettering on the tailgate.'
        result, client = self.response(description)
        self.assertEqual(result.status, 'proposal', result)
        self.assertEqual(result.text, description)
        self.assertEqual(result.metrics.task, 'image_object_sheet')
        self.assertEqual(result.metrics.inference_calls, 1)
        client._request.assert_called_once()
        payload = client._request.call_args.args[1]
        self.assertEqual(payload['messages'][-1]['images'], [encoded_image(object_sheet())])
        self.assertEqual(set(payload['format']['properties']), {'description'})

    def test_layout_commentary_fails_without_rewriting_or_retry(self):
        for description in ['The object sheet shows a grey SUV.',
                            'The top-left panel shows a grey SUV.',
                            'In the rear view, the SUV has red lights.',
                            'A grey SUV is shown in multiple views.']:
            with self.subTest(description=description):
                result, client = self.response(description)
                self.assertEqual(result.status, 'error')
                self.assertIsNone(result.text)
                self.assertEqual(result.metrics.error_code, 'object_sheet_layout_description')
                self.assertIn('oggetto', result.issues[0])
                client._request.assert_called_once()


class ObjectSheetApiTests(unittest.TestCase):
    # Reuse the temporary HTTP fixture, without collecting inherited M3 tests twice.
    setUp = m3.M3ApiTests.setUp
    tearDown = m3.M3ApiTests.tearDown
    view = m3.M3ApiTests.view
    command = m3.M3ApiTests.command
    save = m3.M3ApiTests.save
    completed = m3.M3ApiTests.completed
    run_job = m3.M3ApiTests.run_job
    trial = m3.M3ApiTests.trial
    picture = m3.M3ApiTests.picture
    apply = m3.M3ApiTests.apply

    def object_picture(self):
        id, media = self.picture()
        raw = self.view()['draft_input']
        raw['pictures'][0].update(role='object', analysis=dict(level='medium'))
        self.save(raw)
        return id, media

    def test_sheet_uses_original_and_independent_cache_then_applies_only_explicitly(self):
        id, _ = self.object_picture(); self.trial()
        original = self.view()['draft_input']
        ordinary = self.run_job('image_analyze', id)
        proxy = self.client.post('/api/media', content=m3.png('blue')).json()
        attached = self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/proxy', json=self.command(media_id=proxy['id']))
        self.assertEqual(attached.status_code, 200, attached.text)
        first = self.run_job('image_object_sheet', id)
        self.assertEqual(first['status'], 'succeeded', first)
        self.assertEqual(first['analysis']['category'], 'held_item')
        self.assertEqual(self.fake.last_payload['messages'][-1]['images'], [encoded_image(m3.png())])
        self.assertIn('ONE object', self.fake.last_payload['messages'][0]['content'])
        self.assertNotIn('ONE person', self.fake.last_payload['messages'][0]['content'])
        self.assertEqual(first['result']['metrics']['inference_calls'], 1)
        calls = self.fake.chat_calls
        cached = self.run_job('image_object_sheet', id)
        self.assertEqual(cached['result']['metrics']['inference_calls'], 0)
        self.assertEqual(self.fake.chat_calls, calls)
        fresh = self.run_job('image_object_sheet', id, force=True)
        self.assertEqual(self.fake.chat_calls, calls+1)
        self.assertEqual(self.view()['draft_input'], original)
        self.assertEqual(self.view()['draft_input']['active_units'], [])
        applied = self.apply(fresh)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertFalse(applied.json()['draft_input']['pictures'][0]['confirmed'])
        self.assertTrue(next(j for j in applied.json()['assistance_jobs'] if j['id']==fresh['id'])['applied'])
        self.assertEqual(ordinary['kind'], 'image_analyze')

    def test_role_and_category_are_required_without_inference(self):
        id, _ = self.object_picture(); self.trial()
        for role, category in [('identity','held_item'), ('object','character'), ('environment','environment')]:
            raw = self.view()['draft_input']; raw['pictures'][0].update(role=role, analysis=dict(category=category))
            self.save(raw)
            response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
                kind='image_object_sheet', target_id=id, model='vision-test'))
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.fake.chat_calls, 1)  # Only the synthetic capability trial.
        raw = self.view()['draft_input']; raw['pictures'][0].update(role='appearance', analysis=dict(category='held_item'))
        self.save(raw)
        self.assertEqual(self.run_job('image_object_sheet', id)['status'], 'succeeded')
        response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
            kind='image_character_sheet', target_id=id, model='vision-test'))
        self.assertEqual(response.status_code, 422, response.text)

    def test_proxy_alone_cannot_be_used_as_an_object_sheet(self):
        created = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='picture')).json()
        raw = created['draft_input']; id = raw['pictures'][0]['id']
        raw['pictures'][0].update(role='object', description_en='Manual object description.')
        self.save(raw)
        proxy = self.client.post('/api/media', content=m3.png('blue')).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/proxy', json=self.command(media_id=proxy['id']))
        self.trial()
        response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
            kind='image_object_sheet', target_id=id, model='vision-test'))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('scheda oggetto', response.json()['detail']['message'])
        self.assertEqual(self.fake.chat_calls, 1)

    def test_discard_and_three_result_history_preserve_saved_text_and_media(self):
        id, media = self.object_picture(); self.trial()
        saved = self.client.put(f'/api/cuts/{self.cut}/manual', json=self.command(text='Exact manual prompt.')).json()
        version = saved['versions'][-1]
        before = self.view()['draft_input']
        jobs = [self.run_job('image_object_sheet', id, force=True) for _ in range(5)]
        current = self.view()
        self.assertEqual([j['id'] for j in current['assistance_jobs'] if j['target_id']==id], [j['id'] for j in jobs[-3:]])
        response = self.client.post(f"/api/cuts/{self.cut}/assistance/{jobs[-1]['id']}/dismiss", json=self.command())
        self.assertEqual(response.status_code, 200, response.text)
        current = self.view()
        self.assertTrue(current['assistance_jobs'][-1]['discarded'])
        self.assertEqual(self.apply(jobs[-1]).status_code, 422)
        self.assertEqual(current['draft_input'], before)
        self.assertEqual(current['versions'][-1], version)
        self.assertEqual(self.client.get('/api/media/'+media['id']).content, m3.png())

    def test_changed_object_description_rejects_late_application(self):
        id, _ = self.object_picture(); self.trial()
        self.fake.vision_entered.clear(); self.fake.vision_release.clear()
        response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
            kind='image_object_sheet', target_id=id, model='vision-test'))
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(self.fake.vision_entered.wait(timeout=2))
        raw = self.view()['draft_input']; raw['pictures'][0].update(description_en='Corrected object text.', confirmed=True)
        self.save(raw); self.fake.vision_release.set()
        late = self.completed(response.json())
        self.assertTrue(late['stale'])
        self.assertEqual(self.apply(late).status_code, 409)
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'], 'Corrected object text.')


if __name__ == '__main__': unittest.main()
