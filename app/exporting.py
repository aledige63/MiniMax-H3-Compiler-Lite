"""Esportazioni temporanee da versioni esatte, senza renderer o inferenze."""
import copy
import html
import json
import re
import secrets
import threading
import time
from contextlib import closing

from app.store import StoreError


def reference_notes(version):
    snapshot=version.get('input_snapshot')
    if not snapshot:return ['Snapshot storico non disponibile: riferimenti non ricostruiti.']
    notes=[]
    for unit in snapshot.get('active_units') or []:
        if unit.get('excluded'):continue
        sources=[]
        for source in unit.get('sources') or []:
            picture=next((p for p in snapshot.get('pictures') or [] if p['id']==source.get('picture_id')),None)
            sources.append(f"{source.get('attribute','')} da "+(f"Picture {picture['slot']}" if picture else 'contesto dichiarato' if source.get('origin')=='context' else f"Picture {source.get('picture_slot','?')}"))
        notes.append(f"Subject {unit.get('subject','?')} · {unit.get('name','')} · "+'; '.join(sources))
        scale = unit.get('scale')
        if isinstance(scale, dict):
            picture = next((p for p in snapshot.get('pictures') or [] if p['id'] == scale.get('picture_id')), None)
            target = f" · rispetto a Subject {scale['reference_subject']}" if scale.get('reference_subject') else ''
            source = f" · Picture {picture['slot']}" if picture else ''
            notes.append(f"  Dimensioni e scala · {scale.get('measurements', '')} · {scale.get('comparison', '')}{target}{source}")
        for detail in unit.get('physical_details') or []:
            operation = {'add': 'Aggiunta', 'replace': 'Sostituzione', 'modify': 'Modifica'}.get(detail.get('operation'), 'Dettaglio')
            picture = next((p for p in snapshot.get('pictures') or [] if p['id'] == detail.get('picture_id')), None)
            source = f" · Picture {picture['slot']}" if picture else ' · dal contesto' if detail.get('origin') == 'context' else ''
            notes.append(f"  {operation} · {detail.get('body_location', '')}: {detail.get('description', '')}{source}")
    for kind,key in [('Picture','pictures'),('Video','videos'),('Audio','audio_references')]:
        for item in snapshot.get(key) or []:
            if item.get('excluded'):continue
            description=item.get('description_en') or item.get('name') or 'riferimento dichiarato'
            notes.append(f'{kind} {item.get("slot", "?")} · {item.get("name") or item.get("role", "")} · {description}')
            media=version.get('media_snapshot',{}).get(('audio:' if kind=='Audio' else 'video:' if kind=='Video' else '')+item.get('id',''))
            if media:notes.append('  File archiviato · SHA-256: '+media['sha256'])
            guide=item.get('guidance') or {}
            if guide.get('enabled'):
                for mapping in guide.get('mappings',[]):
                    notes.append(f'  {mapping.get("figure", "")} → '+(f'Subject {mapping["subject"]}' if mapping.get('subject') else mapping.get('role','')))
                if guide.get('prompt_en'):notes.append('  Prompt guida: '+guide['prompt_en'])
                if guide.get('anchor'):notes.append(f"  Frame anchor: {guide['anchor']} · {guide.get('at_s') if guide.get('at_s') is not None else 'estremo del cut'} · {guide.get('workflow','')}")
    if snapshot.get('camera'):
        from app.direction import CameraDirection, OPTIONS
        try:
            camera=CameraDirection.model_validate(snapshot['camera'])
            if camera.active:
                values=[next(v['label'] for v in OPTIONS[key] if v['value']==getattr(camera,key)) for key in ['framing','angle','movement','amplitude','speed'] if getattr(camera,key)]
                if camera.subject:values.append(f'Subject {camera.subject}')
                phase={'as_requested':'come nella richiesta','throughout':'intero cut','opening':'apertura','during_dialogue':'durante la battuta','after_dialogue':'dopo la battuta'}[camera.placement]
                values.append(phase+(' '+camera.dialogue_id if camera.dialogue_id else ''))
                if camera.notes:values.append(camera.notes)
                notes.append('Regia dichiarata: '+' · '.join(values))
        except ValueError:notes.append('Regia storica conservata nello snapshot, non reinterpretata.')
    continuity=snapshot.get('continuity') or {}
    if continuity.get('mode') not in {None,'none'}:
        notes.append('Continuità · '+continuity['mode']+' · '+(continuity.get('declared_state') or ''))
    return notes


class ExportService:
    def __init__(self,repository,*,clock=time.monotonic):
        self.repository=repository;self.clock=clock;self.documents={};self.lock=threading.RLock()

    def prepare(self,selection):
        # La preparazione e l'invalidazione del cestino non possono pubblicare
        # tardivamente una copia temporanea di contenuti appena eliminati.
        with self.repository.lock:return self._prepare(selection)

    def _prepare(self,selection):
        repo=self.repository
        with closing(repo.connect()) as db:
            db.execute('BEGIN')
            if selection.scope=='cut':
                cut=repo._load(db,selection.resource_id,active=True)
                scene=repo._entity(db,'scenes',cut['scene_id']);project=repo._entity(db,'projects',cut['project_id'])
                scenes=[scene];only=cut['id']
            elif selection.scope=='scene':
                scene=repo._entity(db,'scenes',selection.resource_id);project=repo._entity(db,'projects',scene['project_id'])
                scenes=[scene];only=None
            else:
                project=repo._entity(db,'projects',selection.resource_id)
                scenes=db.execute('SELECT * FROM scenes WHERE project_id=? AND trashed=0 ORDER BY number',(project['id'],)).fetchall();only=None
            items=[];known_cuts=set()
            for scene in scenes:
                for row in db.execute('SELECT * FROM cuts WHERE scene_id=? ORDER BY number',(scene['id'],)):
                    if only and row['id']!=only:continue
                    state=json.loads(row['data'])
                    if state.get('trashed'):continue
                    known_cuts.add(row['id'])
                    saved=[json.loads(v[0]) for v in db.execute('SELECT data FROM versions WHERE cut_id=? ORDER BY rowid',(row['id'],))]
                    approved={r[0] for r in db.execute('SELECT version_id FROM approvals WHERE cut_id=?',(row['id'],))}
                    selected=str(selection.versions[row['id']]) if row['id'] in selection.versions else state.get('confirmed_version_id') if selection.policy=='confirmed' else saved[-1]['id'] if saved else None
                    version=next((v for v in saved if v['id']==selected),None)
                    if selected and version is None:raise StoreError('invalid_selection','La versione scelta non appartiene al cut.',422)
                    status='Nessuna versione confermata' if selection.policy=='confirmed' else 'Nessun prompt salvato'
                    if version:
                        status='Confermata' if selected==state.get('confirmed_version_id') else 'Approvata in precedenza' if selected in approved else 'Da rivedere'
                        if selected==state.get('confirmed_version_id') and state.get('state')!='confirmed':status+=' · bozza successiva separata'
                    options=[dict(id=v['id'],number=i+1,origin=v['origin'],approved=v['id'] in approved,duration_s=v.get('duration_s')) for i,v in enumerate(saved)]
                    items.append(dict(cut_id=row['id'],scene_id=scene['id'],scene_number=scene['number'],scene_title=scene['title'],number=row['number'],title=row['title'],
                        version_id=selected,version_number=next((i+1 for i,v in enumerate(saved) if v['id']==selected),None),status=status,origin=version['origin'] if version else None,text=version['text'] if version else None,
                        duration_s=version.get('duration_s') if version else None,duration_origin=version.get('duration_origin') if version else None,
                        snapshot_known=bool(version and version.get('input_snapshot')),references=reference_notes(version) if version and selection.reference_notes else [],versions=options))
            if set(selection.versions)-known_cuts:raise StoreError('invalid_selection','La selezione contiene cut fuori dall’esportazione.',422)
            title=project['name'] if selection.scope=='project' else f"{project['name']} · Scena {scenes[0]['number']} · {scenes[0]['title']}"
            if selection.scope=='cut':title+=f" · Cut {items[0]['number']} · {items[0]['title']}"
            document=dict(scope=selection.scope,project_id=project['id'],title=title,items=items,reference_notes=selection.reference_notes,
                total_duration_s=round(sum(i['duration_s'] or 0 for i in items),3),duration_complete=all(i['duration_s'] is not None for i in items))
        if sum(len(i['text'] or '') for i in items)>5_000_000:raise StoreError('export_limit','Esportazione troppo grande: scegli una scena alla volta.',422)
        with self.lock:
            self._expire();token=secrets.token_urlsafe(24)
            if len(self.documents)>=30:self.documents.pop(next(iter(self.documents)))
            self.documents[token]=(self.clock(),document)
        return dict(id=token,**copy.deepcopy(document))

    def _expire(self):
        for key,(created,_) in list(self.documents.items()):
            if self.clock()-created>1800:self.documents.pop(key,None)

    def get(self,token):
        with self.lock:
            self._expire()
            if token not in self.documents:raise StoreError('export_expired','Esportazione scaduta o rimossa. Preparala di nuovo dall’app.',404)
            return copy.deepcopy(self.documents[token][1])

    def invalidate(self,removed):
        with self.lock:
            for key,(_,document) in list(self.documents.items()):
                ids={document['project_id']}|{i[k] for i in document['items'] for k in ['cut_id','scene_id']}
                if ids & set(removed):self.documents.pop(key,None)


def filename(document):
    return (re.sub(r'[^\w .-]','_',document['title']).strip(' .')[:130] or 'Esportazione')+'.txt'


def text_document(document):
    if document['scope']=='cut':
        if not document['items'][0]['text']:raise StoreError('export_empty','Scegli una versione salvata del cut.',422)
        return document['items'][0]['text']
    parts=[document['title'],'Raccolta di prompt salvati. Metadati e riferimenti restano esterni ai singoli prompt.',duration_summary(document)]
    for item in document['items']:
        parts.append(f"Scena {item['scene_number']} · {item['scene_title']} / Cut {item['number']} · {item['title']}\n"+item_summary(item))
        parts.append(item['text'] if item['text'] is not None else '[Nessun prompt selezionato]')
        if item['references']:parts.append('Note dei riferimenti dello snapshot:\n'+'\n'.join(item['references']))
    return '\n\n'.join(parts)


def duration_summary(document):
    return f"Durata utile totale selezionata: {document['total_duration_s']:g} s"+(' · incompleta: alcuni cut non hanno una durata disponibile.' if not document['duration_complete'] else '.')


def item_summary(item):
    origin={'manual':'manuale','generated':'generata'}.get(item['origin'],'nessuna versione')
    duration={'declared':'dichiarata','measured':'da audio misurato','estimated':'stimata'}.get(item['duration_origin'],'durata sconosciuta')
    return f"Versione {item['version_number'] or '—'} · {origin} · {item['status']} · {item['duration_s'] if item['duration_s'] is not None else '—'} s · {duration}"


def print_document(document):
    esc=lambda value:html.escape(str(value),quote=True)
    sections=[]
    for item in document['items']:
        heading=f"Scena {item['scene_number']} · {item['scene_title']} / Cut {item['number']} · {item['title']}"
        meta=item_summary(item)
        notes=''.join('<li>'+esc(line)+'</li>' for line in item['references'])
        sections.append('<article><h2>'+esc(heading)+'</h2><p class="meta">'+esc(meta)+'</p>'+('<pre>'+esc(item['text'])+'</pre>' if item['text'] is not None else '<p>Nessun prompt selezionato.</p>')+('<aside><h3>Note dei riferimenti dello snapshot</h3><ul>'+notes+'</ul></aside>' if notes else '')+'</article>')
    return '<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(document['title'])+'</title><link rel="stylesheet" href="/static/print.css"><script defer src="/static/print.js"></script></head><body><nav><button id="print">Stampa / salva PDF</button><p>Scegli Salva come PDF nel browser. Controlla tutte le pagine nell’anteprima di stampa. Questa vista temporanea scade dopo 30 minuti.</p></nav><header><p>MINIMAX H3 · COMPILER LITE</p><h1>'+esc(document['title'])+'</h1><p>Versioni salvate selezionate · nessuna rigenerazione</p><p>'+esc(duration_summary(document))+'</p></header>'+''.join(sections)+'</body></html>'
