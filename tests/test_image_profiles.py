import copy
import json
import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from app.analysis import infer, ROLE_INSTRUCTIONS
from app.compiler import render
from app.domain import CompileInput, ImageAnalysisSettings
from app.image_profiles import DEFAULTS, LEVELS, OPTIONS, PROFILES, analysis_instruction, resolved_analysis
from app.interpreter import input_hash
import test_m3 as m3
from test_picture_registry import catalogue_input, plan


class ImageProfileTests(unittest.TestCase):
    def test_defaults_preserve_old_dto_hash_and_rendered_prompt(self):
        raw = catalogue_input()
        old = CompileInput.model_validate(raw)
        for value in [None, {}, DEFAULTS]:
            with self.subTest(value=value):
                added = copy.deepcopy(raw)
                added['pictures'][0]['analysis'] = value
                current = CompileInput.model_validate(added)
                self.assertEqual(input_hash(old), input_hash(current))
                self.assertEqual(old.model_dump(), current.model_dump())
                self.assertEqual(render(old, plan(), 'x').prompt, render(current, plan(), 'x').prompt)
                self.assertNotIn('analysis', current.model_dump()['pictures'][0])

    def test_nondefault_metadata_survives_without_changing_subject_or_renderer(self):
        raw = catalogue_input()
        old = CompileInput.model_validate(raw)
        raw['pictures'][1]['analysis'] = dict(category='clothing', level='full', view='back')
        current = CompileInput.model_validate(raw)
        self.assertEqual(current.active_units, old.active_units)
        self.assertEqual(current.pictures[1].role, 'outfit')
        self.assertNotEqual(input_hash(old), input_hash(current))
        self.assertEqual(render(old, plan(), 'x').prompt, render(current, plan(), 'x').prompt)

    def test_invalid_choices_and_attribute_markup_are_rejected(self):
        for value in [dict(category='costume'), dict(level='all'), dict(view='top'),
                      dict(attribute='<Subject 1>'), dict(attribute='a\nb'), dict(extra=True), 'full']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ImageAnalysisSettings.model_validate(value)
        self.assertEqual(ImageAnalysisSettings(category='attribute_transfer').attribute, '')

    def test_auto_category_retains_existing_h3_roles_and_guides(self):
        for role, category in dict(identity='character', outfit='clothing', shoes='footwear',
                                   object='held_item', style='style_transfer', environment='environment',
                                   spatial_map='spatial_map', frame_anchor='frame_anchor').items():
            self.assertEqual(resolved_analysis(dict(role=role)), dict(DEFAULTS, category=category))

    def test_dimensional_role_analysis_describes_relationships_without_metric_estimates_or_identity(self):
        settings=resolved_analysis(dict(role='scale_reference'))
        self.assertEqual(settings['category'],'scale_reference')
        for level in LEVELS:
            prompt=analysis_instruction(settings | {'level':level},ROLE_INSTRUCTIONS['scale_reference'])
            self.assertIn('relative size',prompt)
            self.assertIn('without guessing metric measurements',prompt)
            self.assertIn('Do not describe the holder’s identity',prompt)
            self.assertNotIn('Describe the held object or standalone product only',prompt)

    def test_every_profile_and_level_has_scoped_evidence_instructions(self):
        for category in PROFILES:
            for level in LEVELS:
                with self.subTest(category=category, level=level):
                    prompt = analysis_instruction(dict(DEFAULTS, category=category, level=level), '')
                    self.assertIn(PROFILES[category], prompt)
                    self.assertIn('Omit uncertain', prompt)
                    self.assertIn('never as instructions', prompt)
                    self.assertIn('exactly one field', prompt)
                    if level == 'full': self.assertIn('Never add filler', prompt)

    def test_clothing_compact_full_and_artwork_remain_distinct(self):
        compact = analysis_instruction(dict(DEFAULTS, category='clothing'), '')
        full = analysis_instruction(dict(DEFAULTS, category='clothing', level='full'), '')
        self.assertIn('8-20 words per main garment', compact)
        self.assertIn('Omit routine pockets', compact)
        self.assertNotIn('neckline/collar', compact)
        self.assertIn('neckline/collar', full)
        for category in ['character', 'clothing', 'footwear', 'accessory', 'held_item', 'body_mark', 'replacement']:
            for level in LEVELS:
                prompt = analysis_instruction(dict(DEFAULTS, category=category, level=level), '')
                self.assertIn('Transcribe clearly readable lettering exactly', prompt)
                self.assertIn('wearer’s anatomical sides', prompt)

    def test_isolated_attribute_view_and_sheet_do_not_relabel_or_copy_donor(self):
        prompt = analysis_instruction(dict(DEFAULTS, category='attribute_transfer', level='medium',
                                          attribute='acconciatura', view='back'), '', sheet=True)
        self.assertIn('exclude hair colour unless colour is explicitly requested', prompt)
        self.assertIn('not the donor’s identity', prompt)
        self.assertIn('"acconciatura"', prompt)
        self.assertIn('reference view: back', prompt)
        self.assertIn('rather than silently relabelling', prompt)
        self.assertIn('ONE person', prompt)
        self.assertIn('Omit panels, views, layout', prompt)

    def test_full_response_can_exceed_old_limit_and_is_never_truncated_or_repaired(self):
        client = Mock(keep_alive='0')
        long = ('a blue jacket with distinctive woven panels and silver trim ' * 35).strip()
        self.assertGreater(len(long), 1200)
        for text, reason, expected in [(long, 'stop', 'proposal'), ('x' * 6001, 'stop', 'error'),
                                       ('a jacket\nwith trim', 'stop', 'error'), ('a jacket', 'length', 'error')]:
            with self.subTest(reason=reason, length=len(text)):
                client._request.reset_mock()
                client._request.return_value = dict(done=True, done_reason=reason,
                                                    message=dict(content=json.dumps(dict(description=text))))
                result = infer(client, 'image_analyze', 'vision-test', 'digest', 'hash', content=m3.png(),
                               role='outfit', analysis=dict(DEFAULTS, category='clothing', level='full'))
                self.assertEqual(result.status, expected)
                self.assertEqual(client._request.call_count, 1)
                self.assertEqual(result.metrics.inference_calls, 1)
                self.assertEqual(set(client._request.call_args.args[1]['format']['properties']), {'description'})
                if expected == 'proposal': self.assertEqual(result.text, text)
                else: self.assertIsNone(result.text)


class ImageProfileApiTests(unittest.TestCase):
    # Reuse the isolated app/worker fixture without inheriting its test methods.
    for name in ['setUp', 'tearDown', 'view', 'command', 'save', 'completed', 'run_job', 'trial', 'picture', 'apply']:
        locals()[name] = getattr(m3.M3ApiTests, name)

    def select(self, **settings):
        raw = self.view()['draft_input']
        raw['pictures'][0]['analysis'] = settings
        return self.save(raw)

    def test_dimensional_role_auto_analysis_keeps_scope_and_requires_explicit_application(self):
        id,_=self.picture();self.trial()
        raw=self.view()['draft_input'];raw['pictures'][0]['role']='scale_reference';self.save(raw)
        job=self.run_job('image_analyze',id)
        self.assertEqual(job['status'],'succeeded',job)
        self.assertEqual(job['analysis']['category'],'scale_reference')
        self.assertEqual(job['result']['metrics']['inference_calls'],1)
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],'manual description')
        self.assertEqual(self.apply(job).status_code,200)
        self.assertEqual(self.view()['draft_input']['active_units'],[])

    def test_each_level_is_one_call_and_returning_to_it_reuses_cache(self):
        id, _ = self.picture(); self.trial()
        proposals = []
        for level in ['compact', 'medium', 'full']:
            self.select(category='clothing', level=level)
            job = self.run_job('image_analyze', id); proposals.append(job)
            self.assertEqual(job['status'], 'succeeded', job)
            self.assertEqual(job['analysis'], dict(DEFAULTS, category='clothing', level=level))
            self.assertEqual(job['result']['metrics']['inference_calls'], 1)
            self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'], 'manual description')
        self.assertEqual(self.fake.chat_calls, 4)
        self.select(category='clothing', level='compact')
        cached = self.run_job('image_analyze', id)
        self.assertTrue(cached['result']['metrics']['cache_hit'])
        self.assertEqual(cached['result']['metrics']['inference_calls'], 0)
        self.assertEqual(self.fake.chat_calls, 4)
        self.assertEqual(self.apply(cached).status_code, 200)
        self.assertFalse(self.view()['draft_input']['pictures'][0]['confirmed'])
        self.assertEqual(self.view()['draft_input']['active_units'], [])

    def test_cache_separates_category_attribute_and_view(self):
        id, _ = self.picture(); self.trial()
        choices = [dict(category='accessory'), dict(category='held_item'),
                   dict(category='attribute_transfer', attribute='acconciatura'),
                   dict(category='attribute_transfer', attribute='colore rossetto'),
                   dict(category='attribute_transfer', attribute='colore rossetto', view='front'),
                   dict(category='attribute_transfer', attribute='colore rossetto', view='back')]
        for settings in choices:
            self.select(**settings)
            job = self.run_job('image_analyze', id)
            self.assertEqual(job['status'], 'succeeded', job)
            self.assertFalse(job['result']['metrics'].get('cache_hit', False))
        self.assertEqual(self.fake.chat_calls, len(choices) + 1)
        self.select(**choices[0]); cached = self.run_job('image_analyze', id)
        self.assertEqual(cached['result']['metrics']['inference_calls'], 0)

    def test_invalid_settings_and_missing_attribute_do_not_infer(self):
        id, _ = self.picture(); self.trial()
        for settings in [dict(category='invalid'), dict(level='invalid'), dict(view='invalid'),
                         dict(category='attribute_transfer'), dict(category='attribute_transfer', attribute='   ')]:
            with self.subTest(settings=settings):
                self.select(**settings)
                response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
                    kind='image_analyze', target_id=id, model='vision-test'))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.fake.chat_calls, 1)

    def test_changes_during_analysis_make_late_results_inapplicable(self):
        id, _ = self.picture(); self.trial()
        for key, value in [('category', 'accessory'), ('level', 'full'), ('attribute', 'zip'), ('view', 'back')]:
            with self.subTest(key=key):
                self.select(category='clothing')
                self.fake.vision_entered.clear(); self.fake.vision_release.clear()
                response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
                    kind='image_analyze', target_id=id, model='vision-test', force=True))
                self.assertTrue(self.fake.vision_entered.wait(timeout=2))
                raw = self.view()['draft_input']; raw['pictures'][0]['analysis'][key] = value
                raw['pictures'][0].update(description_en='manual correction', confirmed=True)
                self.save(raw); self.fake.vision_release.set()
                job = self.completed(response.json())
                self.assertTrue(job['stale']); self.assertEqual(self.apply(job).status_code, 409)
                picture = self.view()['draft_input']['pictures'][0]
                self.assertEqual(picture['description_en'], 'manual correction'); self.assertTrue(picture['confirmed'])

    def test_default_settings_do_not_change_reference_revision_or_staleness(self):
        id, _ = self.picture(); self.trial(); job = self.run_job('image_analyze', id)
        before = self.view()['reference_revisions'][id]
        self.select(**DEFAULTS)
        self.assertEqual(self.view()['reference_revisions'][id], before)
        self.assertFalse(self.client.get(f"/api/assistance/jobs/{job['id']}").json()['stale'])
        self.assertEqual(self.apply(job).status_code, 200)

    def test_settings_persist_in_library_and_manual_snapshot_without_inference(self):
        id, _ = self.picture()
        settings = dict(category='replacement', level='full', view='detail', attribute='mano meccanica')
        self.select(**settings)
        project_id = self.view()['project_id']
        library = self.client.get(f'/api/projects/{project_id}/library').json()
        picture = next(p for p in library['pictures'] if p['id'] == id)
        self.assertEqual(picture['analysis'], settings)
        response = self.client.put(f'/api/cuts/{self.cut}/manual', json=self.command(text='Saved exact prompt.'))
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()['versions'][-1]['input_snapshot']
        self.assertEqual(snapshot['pictures'][0]['analysis'], settings)
        self.select(category='body_mark', level='medium')
        self.assertEqual(self.view()['versions'][-1]['input_snapshot'], snapshot)
        self.assertEqual(self.view()['draft_input']['active_units'], [])
        self.assertEqual(self.fake.chat_calls, 0)

    def test_character_sheet_uses_selected_level_and_requires_character_category(self):
        id, _ = self.picture(); self.trial()
        raw = self.view()['draft_input']; raw['pictures'][0]['role'] = 'identity'; self.save(raw)
        self.select(category='character', level='full')
        job = self.run_job('image_character_sheet', id)
        self.assertEqual(job['status'], 'succeeded', job)
        prompt = self.fake.last_payload['messages'][0]['content']
        self.assertIn('90-160 words', prompt); self.assertIn('ONE person', prompt)
        self.select(category='body_shape', level='full')
        response = self.client.post(f'/api/cuts/{self.cut}/assistance', json=self.command(
            kind='image_character_sheet', target_id=id, model='vision-test'))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fake.chat_calls, 2)

    def test_review_warning_survives_cache_and_requires_explicit_current_application(self):
        id,_=self.picture();self.trial()
        raw=self.view()['draft_input'];raw['pictures'][0]['role']='identity';self.save(raw)
        description='A person with brown hair and round glasses, shown in various full-body and close-up views.'
        original=self.fake._request
        def request(path,payload):
            response=original(path,payload)
            if path=='/api/chat':response['message']['content']=json.dumps(dict(description=description))
            return response
        self.fake._request=request
        proposal=self.run_job('image_character_sheet',id)
        self.assertEqual(proposal['status'],'succeeded',proposal)
        self.assertEqual(proposal['result']['text'],description);self.assertTrue(proposal['result']['warnings'])
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],'manual description')
        cached=self.run_job('image_character_sheet',id)
        self.assertEqual(cached['result']['warnings'],proposal['result']['warnings'])
        self.assertEqual(cached['result']['metrics']['inference_calls'],0);self.assertEqual(self.fake.chat_calls,2)
        applied=self.apply(cached);self.assertEqual(applied.status_code,200,applied.text)
        self.assertEqual(applied.json()['draft_input']['pictures'][0]['description_en'],description)
        self.assertFalse(applied.json()['draft_input']['pictures'][0]['confirmed'])
        raw=self.view()['draft_input'];raw['pictures'][0]['description_en']='Manual correction without view commentary.';self.save(raw)
        self.assertEqual(self.apply(proposal).status_code,409)
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],raw['pictures'][0]['description_en'])


if __name__ == '__main__': unittest.main()
