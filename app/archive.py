"""Cestino definitivo: piano verificabile, conservazione e pulizia ripetibile."""
import hashlib
import json
import os
import stat
from contextlib import closing
from pathlib import PurePosixPath

from app.store import StoreError, digest

if os.name == 'nt':
    from app.windows_files import remove_managed_file
else:
    def remove_managed_file(root, folder, name, expected_sha):
        directory = os.open(root / folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(file, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    return False
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected_sha:
                    return False
                os.unlink(name, dir_fd=directory)
                return True
        finally:
            os.close(directory)


def strings(value):
    if isinstance(value,dict):
        for key,item in value.items():yield key;yield from strings(item)
    elif isinstance(value,(list,tuple)):
        for item in value:yield from strings(item)
    elif isinstance(value,str):
        yield value
        if value.startswith(('{','[')):
            try:yield from strings(json.loads(value))
            except (ValueError,RecursionError):pass


def managed_files(table,row):
    result=[(row['relative_path'],row['sha256'])]
    if table=='audio_media':result.append((row['preview_path'],row['preview_sha256']))
    elif table=='video_media':
        data=json.loads(row['data'])
        result.extend((data[key+'_path'],data[key+'_sha256']) for key in ['poster','tail'])
    return result


class ArchiveOperations:
    def _purge_plan(self,db,selection):
        rows={name:[dict(r) for r in db.execute('SELECT * FROM "'+name+'" ORDER BY rowid')] for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()}
        projects={p['id']:p for p in rows['projects']};scenes={s['id']:s for s in rows['scenes']}
        all_cuts={c['id']:c for c in rows['cuts']}
        trashed_cuts={id for id,c in all_cuts.items() if json.loads(c['data']).get('trashed')}
        selected_projects=set();selected_scenes=set()
        selected_cuts=set()
        if selection.scope=='trash':
            if selection.resource_id is not None:raise StoreError('invalid_input','Il cestino completo non richiede un elemento singolo.',422)
            selected_projects={id for id,p in projects.items() if p['trashed']}
            selected_scenes={id for id,s in scenes.items() if s['trashed'] or s['project_id'] in selected_projects}
            selected_cuts=trashed_cuts
        elif selection.scope=='cut':
            id=str(selection.resource_id)
            if id not in all_cuts:raise StoreError('not_found','Cut non trovato.',404)
            if id not in trashed_cuts:raise StoreError('not_trashed','Sposta prima il cut nel cestino.',409)
            selected_cuts={id}
        else:
            source=projects if selection.scope=='project' else scenes;id=str(selection.resource_id)
            if id not in source:raise StoreError('not_found','Elemento del cestino non trovato.',404)
            if not source[id]['trashed']:raise StoreError('not_trashed','Sposta prima l’elemento nel cestino.',409)
            if selection.scope=='project':
                selected_projects={id};selected_scenes={sid for sid,s in scenes.items() if s['project_id']==id}
            else:selected_scenes={id}
        cuts=selected_cuts|{c['id'] for c in rows['cuts'] if c['scene_id'] in selected_scenes}
        references={r['id'] for r in rows['project_references'] if r['project_id'] in selected_projects}
        versions={v['id'] for v in rows['versions'] if v['cut_id'] in cuts}
        removed=set(cuts)|selected_scenes|selected_projects|references|versions|{u['id'] for u in rows['project_units'] if u['project_id'] in selected_projects}
        commands={r['id'] for r in rows['commands'] if r['resource_id'] in removed or
                  (r['operation']=='create_cut' and json.loads(r['result'])['value']['id'] in cuts)}
        def deleted(table,row):
            if table=='projects':return row['id'] in selected_projects
            if table=='scenes':return row['id'] in selected_scenes
            if table=='cuts':return row['id'] in cuts
            if table in {'versions','jobs','approvals','assistance_jobs','cut_outputs'}:return row['cut_id'] in cuts
            if table in {'project_references','project_units','project_camera_presets','library_trash'}:return row['project_id'] in selected_projects
            if table=='reference_proxies':return row['reference_id'] in references
            if table=='scene_subjects':return row['scene_id'] in selected_scenes
            if table=='version_subjects':return row['version_id'] in versions
            if table=='commands':return row['id'] in commands
            return False
        involved=set();retained=set();blockers=[];unknown=False
        for table,items in rows.items():
            if table in {'media','audio_media','video_media','sessions','pending_file_deletions','assistance_cache'}:continue
            for row in items:
                tokens=set(strings(row))
                if deleted(table,row):involved|=tokens
                else:
                    retained|=tokens
                    if table in {'cuts','versions','jobs','project_units'} and tokens & removed:
                        owner=next((c for c in rows['cuts'] if c['id']==(row['id'] if table=='cuts' else row.get('cut_id'))),None)
                        label=f"Cut {owner['number']} · {owner['title']}" if owner else 'Un riferimento della libreria'
                        blockers.append(label+' conserva un collegamento alla sorgente da eliminare. Mantieni la sorgente oppure includi nel cestino anche gli elementi dipendenti che non vuoi conservare.')
                    if table=='versions' and not json.loads(row['data']).get('input_snapshot'):unknown=True
        for table in ['jobs','assistance_jobs']:
            if any(json.loads(row['data'])['status'] in {'queued','running'} for row in rows[table]):blockers.append('Attendi il termine dei lavori in coda prima della cancellazione definitiva.')
        media=[];files=[];retained_media=0
        for table in ['media','audio_media','video_media']:
            for row in rows[table]:
                if not {row['id'],row['sha256']} & involved:continue
                if unknown or {row['id'],row['sha256']} & retained:retained_media+=1;continue
                media.append((table,row['id']));files.extend(managed_files(table,row))
        if not cuts and not selected_projects and not selected_scenes:blockers.append('Il cestino selezionato è vuoto.')
        # L'impronta include revisioni, completamenti di job, versioni e ricevute;
        # le sessioni LAN non modificano il contenuto del piano.
        fingerprint=digest({table:items for table,items in rows.items() if table!='sessions'})
        plan=dict(selection=selection.model_dump(mode='json'),plan_hash=digest([fingerprint,selection.model_dump(mode='json')]),
            projects=len(selected_projects),scenes=len(selected_scenes),cuts=len(cuts),versions=len(versions),
            media_to_remove=len(media),files_to_remove=len(set(files)),media_retained=retained_media,
            warnings=['Media conservati per prudenza: esistono versioni storiche senza snapshot completo.'] if unknown else [],
            blockers=list(dict.fromkeys(blockers)),labels=[projects[id]['name'] for id in sorted(selected_projects)]+[f"Scena {scenes[id]['number']} · {scenes[id]['title']}" for id in sorted(selected_scenes) if scenes[id]['project_id'] not in selected_projects])
        plan['labels'] += [f"{scenes[cut['scene_id']]['title']} / Cut {cut['number']} · {cut['title']}"
                           for cut in rows['cuts'] if cut['id'] in selected_cuts and cut['scene_id'] not in selected_scenes]
        return plan,dict(projects=selected_projects,scenes=selected_scenes,cuts=cuts,references=references,removed=removed,
                         commands=commands,media=media,files=list(set(files)))

    def purge_preview(self,selection):
        with closing(self.connect()) as db:
            db.execute('BEGIN');return self._purge_plan(db,selection)[0]

    def purge(self,command):
        payload_hash=digest(command.model_dump(mode='json'))
        with self.transaction() as db:
            old=db.execute('SELECT * FROM commands WHERE id=?',(str(command.command_id),)).fetchone()
            if old:
                if old['operation']!='purge' or old['payload_hash']!=payload_hash:raise StoreError('command_conflict','Il comando è già stato usato con dati diversi.')
                result=json.loads(old['result'])
            else:
                plan,work=self._purge_plan(db,command.selection)
                if plan['plan_hash']!=command.plan_hash:raise StoreError('purge_stale','Il contenuto del cestino è cambiato. Riapri l’anteprima prima di confermare.',409)
                if plan['blockers']:raise StoreError('purge_blocked',' '.join(plan['blockers']),409)
                def delete_in(table,column,values):
                    for value in values:db.execute(f'DELETE FROM {table} WHERE {column}=?',(value,))
                for version in work['removed']:db.execute('DELETE FROM version_subjects WHERE version_id=?',(version,))
                delete_in('scene_subjects','scene_id',work['scenes'])
                for table in ['cut_outputs','approvals','assistance_jobs','jobs','versions']:delete_in(table,'cut_id',work['cuts'])
                delete_in('commands','id',work['commands']);delete_in('cuts','id',work['cuts'])
                delete_in('reference_proxies','reference_id',work['references'])
                for table in ['project_units','project_references']:delete_in(table,'project_id',work['projects'])
                delete_in('scenes','id',work['scenes']);delete_in('projects','id',work['projects'])
                for table,id in work['media']:db.execute(f'DELETE FROM {table} WHERE id=?',(id,))
                for relative,sha in work['files']:db.execute('INSERT OR IGNORE INTO pending_file_deletions VALUES (?,?)',(relative,sha))
                db.execute('DELETE FROM assistance_cache')
                default=db.execute("SELECT value FROM settings WHERE key='default_cut'").fetchone()
                if default and default[0] in work['cuts']:db.execute("DELETE FROM settings WHERE key='default_cut'")
                result=dict(projects=plan['projects'],scenes=plan['scenes'],cuts=plan['cuts'],versions=plan['versions'],files_scheduled=plan['files_to_remove'],media_retained=plan['media_retained'],removed_ids=sorted(work['removed']))
                db.execute('INSERT INTO commands VALUES (?,?,?,?,?)',(str(command.command_id),'purge','trash',payload_hash,json.dumps(result)))
        self.cleanup_files()
        with closing(self.connect()) as db:result['pending_files']=db.execute('SELECT count(*) FROM pending_file_deletions').fetchone()[0]
        return result

    def cleanup_files(self):
        """Ogni voce proviene da una cancellazione già confermata e registrata."""
        with self.transaction() as db:
            live={path for table in ['media','audio_media','video_media'] for row in db.execute('SELECT * FROM '+table) for path,_ in managed_files(table,row)}
            for row in db.execute('SELECT * FROM pending_file_deletions').fetchall():
                relative=row['relative_path'];parts=PurePosixPath(relative).parts
                if relative in live:
                    db.execute('DELETE FROM pending_file_deletions WHERE relative_path=?',(relative,));continue
                if len(parts)!=2 or parts[0] not in {'media','audio','video'} or parts[1] in {'.','..'}:continue
                try:
                    removed = remove_managed_file(self.directory, *parts, row['sha256'])
                except FileNotFoundError:db.execute('DELETE FROM pending_file_deletions WHERE relative_path=?',(relative,))
                except OSError:pass
                else:
                    if removed:
                        db.execute('DELETE FROM pending_file_deletions WHERE relative_path=?',(relative,))
