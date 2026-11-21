import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.repository import Repository
import test_m2 as m2


class LibraryTrashTests(unittest.TestCase):
    tearDown = m2.M2Tests.tearDown
    command = m2.M2Tests.command
    prepare = m2.M2Tests.prepare
    create_cut = m2.M2Tests.create_cut
    cut_command = m2.M2Tests.cut_command

    def setUp(self):
        m2.M2Tests.setUp(self); self.prepare()
        self.project = self.view()['project_id']
        self.repo = self.app.state.repository

    def view(self): return self.client.get('/api/workspace').json()
    def library(self): return self.client.get(f'/api/projects/{self.project}/library').json()
    def item(self, kind, id):
        library = self.library(); key = 'units' if kind == 'unit' else 'pictures'
        return next(item for item in library[key] + library['trashed_' + key] if item['id'] == id)
    def trash_command(self, kind, id, trashed=True):
        return dict(command_id=str(uuid4()), expected_revision=self.library()['revision'],
                    expected_reference_revision=self.item(kind,id)['revision'], trashed=trashed)
    def trash(self, kind, id, trashed=True, command=None):
        return self.client.put(f'/api/projects/{self.project}/library/{kind}/{id}/trash',
                               json=command or self.trash_command(kind,id,trashed))

    def test_picture_trash_and_restore_preserve_cut_versions_file_and_canonical_revision(self):
        id = self.input['pictures'][0]['id']
        media = self.client.post('/api/media',content=m2.png()).json()
        response = self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.command(media_id=media['id']))
        self.assertEqual(response.status_code,200,response.text)
        self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Exact saved prompt.'))
        before = self.view(); item = self.item('picture',id)
        response = self.trash('picture',id); self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn(id,[p['id'] for p in self.library()['pictures']])
        self.assertEqual(self.library()['trashed_pictures'],[item])
        self.assertEqual(self.view(),before)
        self.assertEqual(self.client.get('/api/media/'+media['id']).status_code,200)
        self.assertEqual(self.trash('picture',id,False).status_code,200)
        self.assertEqual(self.item('picture',id),item); self.assertEqual(self.library()['trashed_pictures'],[])
        self.assertEqual(self.view(),before); self.assertEqual(self.fake.calls,0)

    def test_subject_trash_does_not_cascade_to_pictures_or_other_cut_bindings(self):
        id = self.view()['unit_ids']['1']; second = self.create_cut()
        slots = {p['id']:p['slot'] for p in self.input['pictures']}
        response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind='unit',reference_id=id,slots=slots))
        self.assertEqual(response.status_code,200,response.text)
        before=self.client.get(f'/api/cuts/{second}').json()
        self.assertEqual(self.trash('unit',id).status_code,200)
        self.assertNotIn(id,[u['id'] for u in self.library()['units']])
        self.assertEqual(len(self.library()['pictures']),4)
        self.assertEqual(self.client.get(f'/api/cuts/{second}').json(),before)
        self.assertEqual(self.trash('unit',id,False).status_code,200)
        self.assertIn(id,[u['id'] for u in self.library()['units']])

    def test_deleted_items_and_subject_dependencies_cannot_be_reused_until_restored(self):
        picture=self.input['pictures'][0]['id']; unit=self.view()['unit_ids']['1']; second=self.create_cut()
        slots={p['id']:p['slot'] for p in self.input['pictures']}
        self.assertEqual(self.trash('picture',picture).status_code,200)
        before=self.client.get(f'/api/cuts/{second}').json()
        for kind,id in [('picture',picture),('unit',unit)]:
            response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind=kind,reference_id=id,slots=slots))
            self.assertEqual(response.status_code,409,response.text)
            self.assertEqual(response.json()['detail']['code'],'library_trashed')
            self.assertEqual(self.client.get(f'/api/cuts/{second}').json(),before)
        self.trash('picture',picture,False); self.trash('unit',unit)
        response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind='unit',reference_id=unit,slots=slots))
        self.assertEqual(response.status_code,409)
        self.trash('unit',unit,False)
        response=self.client.post(f'/api/cuts/{second}/reuse',json=self.cut_command(second,kind='unit',reference_id=unit,slots=slots))
        self.assertEqual(response.status_code,200,response.text); self.assertEqual(self.fake.calls,0)

    def test_retries_are_idempotent_and_stale_project_revision_does_not_trash_another_item(self):
        first,second=[p['id'] for p in self.input['pictures'][:2]]
        command=self.trash_command('picture',first); stale=self.trash_command('picture',second)
        response=self.trash('picture',first,command=command); self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.trash('picture',first,command=command).json(),response.json())
        self.assertEqual(self.trash('picture',second,command=stale).status_code,409)
        self.assertEqual([p['id'] for p in self.library()['trashed_pictures']],[first])

    def test_changed_reference_is_protected_even_if_project_revision_did_not_change(self):
        id=self.input['pictures'][0]['id']; command=self.trash_command('picture',id)
        raw=self.view()['draft_input']; raw['pictures'][0]['description_en']='Updated manually.'
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw));self.assertEqual(response.status_code,200,response.text)
        response=self.trash('picture',id,command=command)
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['detail']['code'],'reference_conflict')
        self.assertEqual(self.library()['trashed_pictures'],[])

    def test_library_trash_survives_cut_edits_and_repository_reopen(self):
        id=self.input['pictures'][0]['id'];self.trash('picture',id)
        raw=self.view()['draft_input'];raw['pictures'][0]['description_en']='Revised inside the existing cut.'
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw));self.assertEqual(response.status_code,200,response.text)
        reopened=Repository(self.temp.name); library=reopened.library(self.project)
        self.assertEqual(library['trashed_pictures'][0]['id'],id)
        self.assertEqual(library['trashed_pictures'][0]['description_en'],raw['pictures'][0]['description_en'])
        self.assertNotIn('trashed',self.view()['draft_input']['pictures'][0])

    def test_foreign_project_and_invalid_kind_are_rejected(self):
        id=self.input['pictures'][0]['id']; command=self.trash_command('picture',id)
        other=self.client.post('/api/projects',json=dict(command_id=str(uuid4()),expected_revision=0,name='Other')).json()['id']
        response=self.client.put(f'/api/projects/{other}/library/picture/{id}/trash',json=command|dict(expected_revision=0))
        self.assertEqual(response.status_code,404,response.text)
        response=self.client.put(f'/api/projects/{self.project}/library/camera/{id}/trash',json=command)
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.library()['trashed_pictures'],[])

    def test_library_management_remains_available_when_scene_is_finalized(self):
        with self.repo.transaction() as db:db.execute('UPDATE scenes SET finalized=1 WHERE id=?',(self.view()['scene_id'],))
        before=self.view(); id=self.input['pictures'][0]['id']
        self.assertEqual(self.trash('picture',id).status_code,200)
        self.assertEqual(self.view(),before)

    def test_schema_seven_backup_is_consistent_and_preserves_existing_records(self):
        self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Immutable snapshot.'))
        with closing(self.repo.connect()) as db:
            before={table:db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in ['cuts','versions','project_references','project_units']}
            before={key:[tuple(row) for row in rows] for key,rows in before.items()}
            db.execute('DROP TABLE library_trash');db.execute("UPDATE settings SET value='7' WHERE key='schema_version'")
        migrated=Repository(self.temp.name)
        with closing(migrated.connect()) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'8')
            for table,rows in before.items():self.assertEqual([tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY 1')],rows)
        with closing(sqlite3.connect(Path(self.temp.name)/'workspace.before-library-trash.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'7')
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='library_trash'").fetchone())

    def test_purging_a_project_includes_its_library_trash(self):
        id=self.input['pictures'][0]['id'];self.trash('picture',id)
        project=self.client.get('/api/projects').json()[0]
        response=self.client.put(f'/api/projects/{self.project}/trash',json=dict(command_id=str(uuid4()),expected_revision=project['revision'],trashed=True))
        self.assertEqual(response.status_code,200,response.text)
        selection=dict(scope='project',resource_id=self.project)
        plan=self.client.post('/api/trash/preview',json=selection).json()
        self.assertEqual(plan['blockers'],[])
        response=self.client.post('/api/trash/purge',json=dict(command_id=str(uuid4()),selection=selection,plan_hash=plan['plan_hash'],confirmed=True,confirmation='ELIMINA'))
        self.assertEqual(response.status_code,200,response.text)
        with closing(self.repo.connect()) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM library_trash').fetchone()[0],0)


if __name__=='__main__':unittest.main()
