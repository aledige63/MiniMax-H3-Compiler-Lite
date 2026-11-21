import copy
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import test_m2 as support
from app.domain import CurrentInterpretation
from app.repository import Repository
from app.subjects import remap_subjects


class SceneSubjectTests(unittest.TestCase):
    setUp = support.M2Tests.setUp
    tearDown = support.M2Tests.tearDown
    command = support.M2Tests.command
    cut_command = support.M2Tests.cut_command
    prepare = support.M2Tests.prepare
    create_cut = support.M2Tests.create_cut
    completed = support.M2Tests.completed

    def view(self, cut=None):return self.client.get(f'/api/cuts/{cut or self.cut}').json()

    def reuse(self, cut, identity):
        library = self.client.get(f'/api/projects/{self.view(cut)["project_id"]}/library').json()
        unit = next(u for u in library['units'] if u['id'] == identity)
        ids = list(dict.fromkeys(s['picture_id'] for s in unit['sources'] if s.get('picture_id')))
        view = self.view(cut);existing = {p['id'] for p in view['draft_input']['pictures']};used = {p['slot'] for p in view['draft_input']['pictures']}
        free = iter(n for n in range(1,10) if n not in used)
        slots = {id:next(free) for id in ids if id not in existing}
        r = self.client.post(f'/api/cuts/{cut}/reuse',json=self.cut_command(cut,kind='unit',reference_id=identity,slots=slots))
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def compact(self, cut=None, command=None):
        view = self.view(cut);scene = next(s for p in self.client.get('/api/projects').json() for s in p['scenes'] if s['id'] == view['scene_id'])
        return self.client.post(f'/api/scenes/{scene["id"]}/subjects/compact',json=command or dict(command_id=str(uuid4()),expected_revision=scene['revision']))

    def legacy_gap(self):
        self.prepare();repo=self.app.state.repository
        with repo.transaction() as db:
            state = repo._load(db,self.cut);identity=state['unit_bindings']['3']
            db.execute('UPDATE scene_subjects SET subject=5 WHERE scene_id=? AND subject=3',(state['scene_id'],))
            state['draft_input']=remap_subjects(state['draft_input'],{3:5})
            state['unit_bindings']['5']=state['unit_bindings'].pop('3');state['unit_revisions']['5']=state['unit_revisions'].pop('3')
            repo._write_cut(db,state)
        return identity

    def test_new_scene_starts_at_one_despite_other_scene_history(self):
        self.prepare();original=self.view();second=self.create_cut(new_scene=True)
        for n in range(1,4):
            added=self.client.post(f'/api/cuts/{second}/items',json=self.cut_command(second,kind='unit')).json()
            self.assertEqual(added['draft_input']['active_units'][-1]['subject'],n)
        self.assertNotEqual(original['unit_ids']['1'],added['unit_ids']['1'])
        self.assertEqual(self.view()['draft_input'],original['draft_input']);self.assertEqual(self.fake.calls,0)

    def test_reuse_and_reload_use_identity_even_when_scene_numbers_differ(self):
        self.prepare();original=self.view();second=self.create_cut(new_scene=True)
        first=self.reuse(second,original['unit_ids']['2']);second_view=self.reuse(second,original['unit_ids']['1'])
        self.assertEqual([u['subject'] for u in second_view['draft_input']['active_units']],[1,2])
        self.assertEqual(second_view['unit_ids']['1'],original['unit_ids']['2']);self.assertEqual(second_view['unit_ids']['2'],original['unit_ids']['1'])
        raw=second_view['draft_input'];raw['active_units'][1]['name']='Anna aggiornata'
        r=self.client.put(f'/api/cuts/{second}/draft',json=self.cut_command(second,input=raw));self.assertEqual(r.status_code,200,r.text)
        library=self.client.get(f'/api/projects/{original["project_id"]}/library?scene_id={second_view["scene_id"]}').json()
        anna=next(u for u in library['units'] if u['id']==original['unit_ids']['1']);self.assertEqual(anna['subject'],2);self.assertEqual(anna['name'],'Anna aggiornata')
        self.assertEqual(self.view()['draft_input'],original['draft_input'])
        reloaded=self.reuse(self.cut,original['unit_ids']['1']);self.assertEqual(reloaded['draft_input']['active_units'][0]['name'],'Anna aggiornata')
        self.assertEqual(reloaded['draft_input']['active_units'][0]['subject'],1)

    def test_compaction_updates_structured_references_but_keeps_words_and_history(self):
        identity=self.legacy_gap();raw=self.view()['draft_input'];words='Non cambiare <Subject 5>  dentro questa battuta.'
        raw['request']='<Subject 5> entra con <Subject 1>.';raw['dialogues'][0].update(speaker_subject=5,text=words)
        raw['audio_references']=[dict(id='a1',speaker_subject=5,transcript=words)]
        raw['camera']=dict(subject=5,notes='Segui <Subject 5>.')
        raw['pictures'][0]['guidance']=dict(enabled=False,mappings=[dict(figure='A',subject=5)],prompt_en='Frame <Subject 5>.')
        with self.app.state.repository.transaction() as db:
            state=self.app.state.repository._load(db,self.cut);state['draft_input']=raw;self.app.state.repository._write_cut(db,state)
        saved=self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Vecchio prompt: <Subject 5>.')).json()['versions'][-1]
        before=copy.deepcopy(saved);r=self.compact();self.assertEqual(r.status_code,200,r.text)
        after=self.view();draft=after['draft_input'];self.assertEqual([u['subject'] for u in draft['active_units']],[1,2,3]);self.assertEqual(after['unit_ids']['3'],identity)
        self.assertEqual(draft['request'],'<Subject 3> entra con <Subject 1>.');self.assertEqual(draft['dialogues'][0]['speaker_subject'],3);self.assertEqual(draft['dialogues'][0]['text'],words)
        self.assertEqual(draft['audio_references'][0]['speaker_subject'],3);self.assertEqual(draft['audio_references'][0]['transcript'],words)
        self.assertEqual(draft['camera']['subject'],3);self.assertEqual(draft['pictures'][0]['guidance']['mappings'][0]['subject'],3)
        self.assertEqual(draft['pictures'][0]['guidance']['prompt_en'],'Frame <Subject 3>.');self.assertEqual(after['versions'][-1],before)
        self.assertEqual(self.client.get(f'/api/cuts/{self.cut}/text?version_id={saved["id"]}').text,saved['text']);self.assertEqual(self.fake.calls,0)

    def test_context_from_old_number_keeps_identity_after_compaction(self):
        identity=self.legacy_gap()
        saved=self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Storico <Subject 5>.')).json()['versions'][-1]
        self.assertEqual(self.compact().status_code,200)
        second=self.create_cut();raw=self.view(second)['draft_input'];raw['continuity']=dict(mode='latent',declared_state='Stato verificato.',previous_cut_id=self.cut,previous_version_id=saved['id'])
        r=self.client.put(f'/api/cuts/{second}/draft',json=self.cut_command(second,input=raw));self.assertEqual(r.status_code,200,r.text)
        r=self.client.post(f'/api/cuts/{second}/context-subject',json=self.cut_command(second,subject=5));self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['draft_input']['active_units'][0]['subject'],3);self.assertEqual(r.json()['unit_ids']['3'],identity)
        # Il numero 5 della vecchia versione non consuma nuovamente uno slot.
        r=self.client.post(f'/api/cuts/{second}/items',json=self.cut_command(second,kind='unit'));self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['draft_input']['active_units'][-1]['subject'],4)

    def test_generated_prompt_and_version_binding_use_scene_number(self):
        self.prepare();original=self.view();second=self.create_cut(new_scene=True);view=self.reuse(second,original['unit_ids']['2'])
        raw=view['draft_input'];raw.update(request='<Subject 1> cammina.',declared_duration_s=5)
        for p in raw['pictures']:p['linked_to_h3']=True
        self.fake.plan=CurrentInterpretation(summary_en='<Subject 1> walks.',narrative_en='<Subject 1> walks.',estimated_duration_s=5,question=None)
        r=self.client.post(f'/api/cuts/{second}/compile',json=self.cut_command(second,input=raw,model='local-test')|{'cut_id':second});self.assertEqual(r.status_code,202,r.text)
        job=self.completed(r.json());self.assertEqual(job['status'],'succeeded')
        version=self.view(second)['versions'][-1];self.assertIn('<Subject 1>',version['text']);self.assertNotIn('<Subject 2>',version['text'])
        with closing(self.app.state.repository.connect()) as db:
            binding=self.app.state.repository._version_subject_ids(db,version['id'])
        self.assertEqual(binding,{'1':original['unit_ids']['2']})

    def test_migration_preserves_rows_and_restart_preserves_bindings(self):
        self.prepare();self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Storico esatto.'))
        repo=self.app.state.repository
        with repo.transaction() as db:
            db.execute('DROP TABLE version_subjects');db.execute('DROP TABLE scene_subjects');db.execute("UPDATE settings SET value='5' WHERE key='schema_version'")
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            before={t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}
        reopened=Repository(self.temp.name)
        with closing(reopened.connect()) as db:
            for table,rows in before.items():
                after=[tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                if table=='settings':rows=[r for r in rows if r[0]!='schema_version'];after=[r for r in after if r[0]!='schema_version']
                self.assertEqual(after,rows,table)
            self.assertEqual(db.execute('SELECT count(*) FROM scene_subjects').fetchone()[0],3)
        with closing(sqlite3.connect(Path(self.temp.name)/'workspace.before-scene-subjects.sqlite3')) as db:self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'5')
        self.assertEqual(Repository(self.temp.name).workspace(),reopened.workspace())

    def test_compaction_is_idempotent_and_rejects_stale_scene_revision(self):
        self.legacy_gap();scene=self.client.get('/api/projects').json()[0]['scenes'][0]
        command=dict(command_id=str(uuid4()),expected_revision=scene['revision'])
        first=self.compact(command=command);self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.compact(command=command).json(),first.json())
        stale=command|{'command_id':str(uuid4())};self.assertEqual(self.compact(command=stale).status_code,409)

    def test_missing_subject_reference_cannot_turn_into_a_different_identity(self):
        self.legacy_gap();raw=self.view()['draft_input'];raw['request']='<Subject 3> entra.'
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw)).status_code,200)
        before=self.view();r=self.compact();self.assertEqual(r.status_code,422)
        self.assertEqual(r.json()['detail']['code'],'subject_references_unresolved');self.assertEqual(self.view(),before)
