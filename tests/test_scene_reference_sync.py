import copy
import json
import unittest

import test_m2 as m2


class SceneReferenceSyncTests(unittest.TestCase):
    setUp = m2.M2Tests.setUp
    tearDown = m2.M2Tests.tearDown
    prepare = m2.M2Tests.prepare
    command = m2.M2Tests.command
    create_cut = m2.M2Tests.create_cut
    cut_command = m2.M2Tests.cut_command

    def view(self, cut):
        return self.client.get(f'/api/cuts/{cut}').json()

    def save(self, cut, raw):
        response = self.client.put(f'/api/cuts/{cut}/draft', json=self.cut_command(cut, input=raw))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def subject_four(self):
        self.prepare()
        response = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='unit'))
        raw = response.json()['draft_input']
        raw['active_units'][-1].update(name='Test subject', description_en='Original definition.',
            definition_mode='manual', confirmed=True,
            sources=[dict(picture_id=raw['pictures'][0]['id'], attribute='identity')])
        return self.save(self.cut, raw)['unit_ids']['4']

    def reuse_subject(self, cut, unit_id):
        picture = self.view(self.cut)['draft_input']['pictures'][0]['id']
        response = self.client.post(f'/api/cuts/{cut}/reuse', json=self.cut_command(cut,
            kind='unit', reference_id=unit_id, slots={picture: 7}))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_subject_four_updates_other_cuts_in_scene_preserving_versions_and_local_use(self):
        identity = self.subject_four(); second = self.create_cut()
        second_view = self.reuse_subject(second, identity)
        raw = second_view['draft_input']; raw['request'] = 'Different cut request.'
        raw['active_units'][0]['excluded'] = True
        self.save(second, raw)
        self.client.put(f'/api/cuts/{second}/manual', json=self.cut_command(second, text='Exact historical text.\n'))
        before = self.view(second)
        raw = self.view(self.cut)['draft_input']
        raw['active_units'][-1]['description_en'] = 'Updated definition with one corrected detail.'
        source = self.save(self.cut, raw)
        after = self.view(second)
        self.assertEqual(after['draft_input']['active_units'][0]['description_en'], raw['active_units'][-1]['description_en'])
        self.assertEqual(after['draft_input']['request'], 'Different cut request.')
        self.assertTrue(after['draft_input']['active_units'][0]['excluded'])
        self.assertEqual(after['draft_input']['pictures'][0]['slot'], 7)
        self.assertEqual(after['unit_ids']['4'], identity)
        self.assertEqual(after['versions'], before['versions'])
        self.assertEqual(after['manual_version_id'], before['manual_version_id'])
        self.assertEqual(after['unit_revisions']['4'], source['unit_revisions']['4'])
        self.save(second, after['draft_input'])
        self.assertEqual(self.fake.calls, 0)

    def test_other_scenes_reusing_same_identity_do_not_adopt_the_description(self):
        identity = self.subject_four(); other = self.create_cut(new_scene=True)
        before = self.reuse_subject(other, identity)
        self.assertEqual(before['draft_input']['active_units'][0]['subject'], 1)
        raw = self.view(self.cut)['draft_input']; raw['active_units'][-1]['description_en'] = 'Scene one only.'
        self.save(self.cut, raw)
        after = self.view(other)
        self.assertEqual(after['draft_input'], before['draft_input'])
        self.assertEqual(after['revision'], before['revision'])

    def test_picture_description_updates_without_changing_slot_link_exclusion_or_media(self):
        self.prepare(); picture = self.input['pictures'][0]['id']; second = self.create_cut()
        response = self.client.post(f'/api/cuts/{second}/reuse', json=self.cut_command(second,
            kind='picture', reference_id=picture, slots={picture: 8}))
        self.assertEqual(response.status_code, 200, response.text)
        raw = response.json()['draft_input']; raw['pictures'][0].update(excluded=True, linked_to_h3=True)
        self.save(second, raw); before = self.view(second)
        raw = self.view(self.cut)['draft_input']; raw['pictures'][0]['description_en'] = 'Corrected shared image description.'
        self.save(self.cut, raw); after = self.view(second)
        self.assertEqual(after['draft_input']['pictures'][0]['description_en'], 'Corrected shared image description.')
        for field in ['id', 'slot', 'linked_to_h3', 'excluded']:
            self.assertEqual(after['draft_input']['pictures'][0][field], before['draft_input']['pictures'][0][field])
        self.assertEqual(after['media_by_picture'], before['media_by_picture'])

    def test_existing_stale_draft_is_reconciled_from_a_current_cut_in_same_scene(self):
        identity = self.subject_four(); second = self.create_cut(); original = self.reuse_subject(second, identity)
        raw = self.view(self.cut)['draft_input']; raw['active_units'][-1]['description_en'] = 'New shared definition.'
        self.save(self.cut, raw)
        # Simulate a draft saved by the older application before this fix.
        with self.app.state.repository.transaction() as db:
            data = json.loads(db.execute('SELECT data FROM cuts WHERE id=?', (second,)).fetchone()[0])
            data['draft_input'] = copy.deepcopy(original['draft_input'])
            data['unit_revisions'] = original['unit_revisions']
            db.execute('UPDATE cuts SET data=? WHERE id=?', (json.dumps(data), second))
        fixed = self.view(second)
        self.assertEqual(fixed['draft_input']['active_units'][0]['description_en'], 'New shared definition.')
        revision = fixed['revision']
        self.assertEqual(self.view(second)['revision'], revision)
        self.assertEqual(self.fake.calls, 0)
