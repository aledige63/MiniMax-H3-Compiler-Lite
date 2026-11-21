import copy
import unittest

import test_m2 as m2


class ReferenceRevisionTests(unittest.TestCase):
    setUp = m2.M2Tests.setUp
    tearDown = m2.M2Tests.tearDown
    prepare = m2.M2Tests.prepare
    command = m2.M2Tests.command
    create_cut = m2.M2Tests.create_cut
    cut_command = m2.M2Tests.cut_command

    def view(self):return self.client.get('/api/workspace').json()
    def save(self,cut,raw):return self.client.put(f'/api/cuts/{cut}/draft',json=self.cut_command(cut,input=raw))

    def test_two_subject_physical_changes_accept_identical_library_content_at_newer_revisions(self):
        self.prepare()
        raw=self.view()['draft_input']; third=next(u for u in raw['active_units'] if u['subject']==3)
        third.update(role='character',name='Seconda persona',sources=[dict(attribute='identity',picture_id=raw['pictures'][2]['id'])])
        self.assertEqual(self.save(self.cut,raw).status_code,200)
        self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Saved exact text.'))
        before=self.view(); ids=before['unit_ids']
        with self.app.state.repository.transaction() as db:
            db.execute('UPDATE project_units SET revision=revision+2 WHERE id=?',(ids['1'],))
        raw=copy.deepcopy(before['draft_input']);raw['request']='Una nuova richiesta locale.'
        for unit in raw['active_units']:
            if unit['subject'] in [1,3]:
                unit['physical_details']=[dict(id='p1',description='una piccola cicatrice',body_location='guancia sinistra',operation='add')]
                unit['confirmed']=False
        response=self.save(self.cut,raw);self.assertEqual(response.status_code,200,response.text)
        saved=response.json()
        self.assertEqual(saved['draft_input'],raw);self.assertEqual(saved['unit_ids'],ids)
        self.assertEqual(saved['versions'],before['versions']);self.assertEqual(self.fake.calls,0)

    def test_subject_changed_elsewhere_then_restored_to_same_content_allows_local_edit(self):
        self.prepare();before=self.view(); unit_id=before['unit_ids']['1']; second=self.create_cut()
        response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind='unit',reference_id=unit_id,slots={p['id']:p['slot'] for p in self.input['pictures']}))
        self.assertEqual(response.status_code,200,response.text)
        other=response.json()['draft_input']; original_name=other['active_units'][0]['name']
        other['active_units'][0]['name']='Temporary name';self.assertEqual(self.save(second,other).status_code,200)
        other['active_units'][0]['name']=original_name;self.assertEqual(self.save(second,other).status_code,200)
        stable=self.client.get(f'/api/cuts/{second}').json()
        raw=before['draft_input'];raw['active_units'][0]['description_en']='A local manual definition.'
        raw['active_units'][0]['definition_mode']='manual';raw['active_units'][0]['confirmed']=False
        response=self.save(self.cut,raw);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['unit_ids']['1'],unit_id)
        self.assertEqual(self.client.get(f'/api/cuts/{second}').json()['draft_input'],stable['draft_input'])

    def test_picture_default_fields_are_normalized_when_content_has_not_changed(self):
        self.prepare();before=self.view(); id=before['draft_input']['pictures'][0]['id']
        with self.app.state.repository.transaction() as db:
            # Equivalent historical row, without additive language/analysis defaults.
            import json
            row=db.execute('SELECT data FROM project_references WHERE id=?',(id,)).fetchone()
            data=json.loads(row['data'])
            for key in ['description_language','use_original_language','original_description','original_language','analysis']:data.pop(key,None)
            db.execute('UPDATE project_references SET data=?,revision=revision+2 WHERE id=?',(json.dumps(data),id))
        raw=before['draft_input'];raw['pictures'][0]['description_en']='A revised reference description.'
        response=self.save(self.cut,raw);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['draft_input']['pictures'][0]['description_en'],raw['pictures'][0]['description_en'])

    def test_real_subject_conflict_names_the_subject_and_preserves_local_saved_state(self):
        self.prepare();before=self.view();unit_id=before['unit_ids']['1']
        with self.app.state.repository.transaction() as db:
            import json
            row=db.execute('SELECT data FROM project_units WHERE id=?',(unit_id,)).fetchone();data=json.loads(row['data'])
            data['description_en']='A different shared definition.';data['definition_mode']='manual'
            db.execute('UPDATE project_units SET data=?,revision=revision+1 WHERE id=?',(json.dumps(data),unit_id))
        raw=copy.deepcopy(before['draft_input']);raw['active_units'][0]['physical_details']=[dict(id='p1',description='una cicatrice',body_location='guancia',operation='add')]
        response=self.save(self.cut,raw);self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['detail']['code'],'reference_conflict')
        self.assertIn('Subject 1',response.json()['detail']['message'])
        self.assertIn(raw['active_units'][0]['name'],response.json()['detail']['message'])
        self.assertEqual(self.view()['draft_input'],before['draft_input'])

    def test_replaced_media_with_identical_description_is_still_a_real_conflict(self):
        self.prepare();id=self.input['pictures'][0]['id']
        first=self.client.post('/api/media',content=m2.png('red')).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.command(media_id=first['id']))
        second=self.create_cut()
        response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind='picture',reference_id=id,slots={id:1}))
        self.assertEqual(response.status_code,200,response.text);stale=response.json()['draft_input']
        newer=self.client.post('/api/media',content=m2.png('blue')).json()
        response=self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.command(media_id=newer['id']))
        self.assertEqual(response.status_code,200,response.text)
        stale['pictures'][0]['name']='Edited from the older photo'
        response=self.save(second,stale);self.assertEqual(response.status_code,409,response.text)
        self.assertIn('Picture 1',response.json()['detail']['message'])
        self.assertEqual(self.client.get(f'/api/cuts/{second}').json()['media_by_picture'][id]['id'],first['id'])

    def test_replaced_proxy_is_not_an_unchanged_base_at_a_newer_reference_revision(self):
        self.prepare();id=self.input['pictures'][0]['id']
        first=self.client.post('/api/media',content=m2.png('red')).json()
        response=self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/proxy',json=self.command(media_id=first['id']))
        self.assertEqual(response.status_code,200,response.text)
        second=self.create_cut()
        response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind='picture',reference_id=id,slots={id:1}))
        self.assertEqual(response.status_code,200,response.text);stale=response.json()['draft_input']
        newer=self.client.post('/api/media',content=m2.png('blue')).json()
        response=self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/proxy',json=self.command(media_id=newer['id']))
        self.assertEqual(response.status_code,200,response.text)
        with self.app.state.repository.transaction() as db:
            db.execute('UPDATE project_references SET revision=revision+2 WHERE id=?',(id,))
        stale['pictures'][0]['description_en']='Edited from the older proxy'
        response=self.save(second,stale);self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.client.get(f'/api/cuts/{second}').json()['proxy_by_picture'][id]['id'],first['id'])


if __name__=='__main__':unittest.main()
