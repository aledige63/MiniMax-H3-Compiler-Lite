"""Regia dichiarata e guide: metadati brevi, nessuna inferenza o geometria dedotta."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

OPTIONS = json.loads(Path(__file__).with_name('static').joinpath('direction-options.json').read_text(encoding='utf-8'))
IMAGE_GUIDE_ROLES = {'style','spatial_map','composition_previz','initial_composition','frame_anchor'}
VIDEO_GUIDE_ROLES = {'camera','subject_motion','camera_and_subject_motion'}
GUIDE_EVENT = re.compile(r'\{\{guide:((?:picture|video)_[1-9][0-9]*)\}\}(?:[ \t]*\.+)?')
CAMERA_EVENT = re.compile(r'\{\{camera:main\}\}(?:[ \t]*\.+)?')


def camera_instruction(camera):
    context = camera.context()
    phrases = []
    scope = {'throughout': 'Maintain the following camera setup throughout the cut.',
             'opening': 'Use the following camera setup at the opening.',
             'during_dialogue': 'Use the following camera setup during the following dialogue.'}
    if camera.placement in scope:
        phrases.append(scope[camera.placement])
    if camera.framing:
        framing = context['framing']
        target = f" of {context['target']}" if camera.subject else ''
        article = 'an' if framing[0].lower() in 'aeiou' else 'a'
        phrases.append(f'Use {article} {framing}{target}.')
    if camera.angle:
        angle = context['angle']
        article = 'an' if angle[0].lower() in 'aeiou' else 'a'
        phrases.append(f'Use {article} {angle}.')
    if camera.movement:
        motion = ' '.join(context[key] for key in ('movement', 'amplitude', 'speed') if key in context)
        phrases.append(f'The camera {motion}.')
    if camera.subject and not camera.framing:
        phrases.append(f"The camera targets {context['target']}.")
    return ' '.join(phrases)


class DirectionDTO(BaseModel):
    model_config = ConfigDict(extra='forbid',frozen=True,strict=True)


class CameraDirection(DirectionDTO):
    framing: str | None = None
    angle: str | None = None
    movement: str | None = None
    amplitude: str | None = None
    speed: str | None = None
    subject: int | None = Field(default=None,ge=1)
    placement: Literal['as_requested','throughout','opening','during_dialogue','after_dialogue'] = 'as_requested'
    dialogue_id: str | None = None
    notes: str = Field(default='',max_length=1200)

    @model_validator(mode='after')
    def valid_choices(self):
        for key in ['framing','angle','movement','amplitude','speed']:
            value=getattr(self,key)
            if value is not None and value not in {v['value'] for v in OPTIONS[key]}:
                raise PydanticCustomError('direction_error','Scelta di regia non disponibile: {field}.',{'field':key})
        if (self.amplitude or self.speed) and (not self.movement or self.movement=='static'):
            raise PydanticCustomError('direction_error','Ampiezza e velocità richiedono un movimento, distinto dalla camera fissa.')
        if self.placement in {'during_dialogue','after_dialogue'} and not self.dialogue_id:
            raise PydanticCustomError('direction_error','Scegli la battuta a cui collegare il movimento della camera.')
        if self.dialogue_id and self.placement not in {'during_dialogue','after_dialogue'}:
            raise PydanticCustomError('direction_error','La battuta si usa soltanto per la regia durante/dopo il dialogo.')
        return self

    @property
    def active(self):
        return bool(self.framing or self.angle or self.movement or self.notes.strip())

    def context(self):
        value={key:next(v['en'] for v in OPTIONS[key] if v['value']==getattr(self,key)) for key in ['framing','angle','movement','amplitude','speed'] if getattr(self,key)}
        value['placement']=self.placement
        if self.subject:value['target']=f'<Subject {self.subject}>'
        if self.dialogue_id:value['dialogue_id']=self.dialogue_id
        if self.notes.strip():value['notes']=self.notes
        return value


class GuideMapping(DirectionDTO):
    figure: str = Field(default='',max_length=200)
    role: Literal['figure','start','destination','camera_start','camera_direction','motion'] = 'figure'
    subject: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def explicit_target(self):
        if any(c in self.figure for c in '<>{}\r\n'):
            raise PydanticCustomError('guide_error','Descrivi la figura/segno della guida su una riga, senza token H3.')
        return self


class GuideUsage(DirectionDTO):
    enabled: bool = False
    mappings: list[GuideMapping] = Field(default_factory=list,max_length=12)
    prompt_en: str = Field(default='',max_length=2500)
    anchor: Literal['first','last','keyframe'] | None = None
    at_s: float | None = Field(default=None,ge=0,le=15,allow_inf_nan=False)
    workflow: str = Field(default='',max_length=400)
    continuity_checked: bool = False

    @model_validator(mode='after')
    def safe_template(self):
        if self.enabled and ('{{' in self.prompt_en or re.search(r'<d>|</d>|\[Shot\s|(?:subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music)\s*:',self.prompt_en)):
            raise PydanticCustomError('guide_error','Il prompt guida non può contenere dialoghi, nuove sezioni, shot o segnaposto riservati.')
        if self.enabled and len({m.figure.strip().casefold() for m in self.mappings})!=len(self.mappings):
            raise PydanticCustomError('guide_error','Ogni figura della guida deve avere un mapping univoco.')
        return self


def guide_key(reference,kind):return f'{kind}_{reference.slot}'


def subject_motion_bindings(data):
    """Associazioni dichiarate delle sole guide Video attive, senza leggere i video."""
    bindings = {}
    for reference in data.active_video_guides:
        if reference.role not in {'subject_motion', 'camera_and_subject_motion'}:
            continue
        for mapping in reference.guidance.mappings:
            bindings.setdefault(mapping.subject, []).append((reference, mapping))
    return bindings


def guide_opening(reference):
    """Legge l'etichetta esplicita del testo guida, senza dedurne presenze o tempi."""
    if reference.role not in {'subject_motion', 'camera_and_subject_motion'}:
        return None
    for line in reference.guidance.prompt_en.splitlines():
        match = re.match(r'^\s*Opening(?:\s+(?:frame|composition))?\s*:\s*(\S.*)$', line, re.IGNORECASE)
        if match:
            return match[1].strip()
    return None


def guide_text(reference,kind):
    token=f'<{kind.title()} {reference.slot}>';g=reference.guidance
    if kind=='video':
        instruction={'camera':f'Use only the camera movement from {token}.',
                     'subject_motion':f'Use the mapped Subject motion from {token}.',
                     'camera_and_subject_motion':f'Use the camera movement and mapped Subject motion from {token}.'}[reference.role]
    else:
        instruction={'style':f'Use {token} as the visual-style guide.',
            'spatial_map':f'Use the declared spatial mapping in {token}.',
            'composition_previz':f'Use {token} as a composition reference.',
            'initial_composition':f'Use {token} for the initial composition.',
            'frame_anchor':f'The shot {"begins from" if g.anchor=="first" else "ends on" if g.anchor=="last" else "has its keyframe at "+str(g.at_s)+"s corresponding to"} {token}.'}[reference.role]
    instructions=[instruction]
    for mapping in g.mappings:
        if mapping.role in {'camera_start','camera_direction'}:
            meaning='the camera starting position' if mapping.role=='camera_start' else 'the camera direction'
        else:
            subject=f'<Subject {mapping.subject}>'
            meaning={'figure':subject,'start':f'the starting position of {subject}','destination':f'the destination of {subject}','motion':f'the motion of {subject}'}[mapping.role]
        instructions.append(f'In {token}, "{mapping.figure.strip()}" identifies {meaning}.')
    if kind == 'video' and reference.role in {'subject_motion', 'camera_and_subject_motion'}:
        instructions.append('Each mapped Subject replaces its guide proxy in place from the proxy’s first visible appearance, '
            'using the Subject’s declared appearance. Preserve the proxy’s placement, orientation, trajectory and entry/exit timing. '
            'The proxy shapes are not additional scene objects.')
        if guide_opening(reference):
            instructions.append('The following declared opening governs initial presence and placement. '
                'A Subject whose proxy enters later remains outside the frame until that entry.')
    if g.prompt_en:instructions.append(g.prompt_en)
    text=' '.join(instructions)
    return text if text.rstrip().endswith(('.', '!', '?')) else text+'.'


def validate_direction(data):
    """Vincoli fra scelte certe; il modello chiarisce i conflitti nel testo libero."""
    units={u.subject for u in data.included_units}
    dialogues={d.id for d in data.dialogues}|{a.id for a in data.audio_references if a.role=='speech'}
    camera=data.camera
    if camera and camera.active:
        if camera.subject is not None and camera.subject not in units:
            raise PydanticCustomError('direction_error','Il destinatario della camera deve essere un Subject attivo.')
        if camera.dialogue_id and camera.dialogue_id not in dialogues:
            raise PydanticCustomError('direction_error','La battuta selezionata per la camera non è disponibile nel cut.')
    pictures=data.active_picture_guides
    videos=data.active_video_guides
    camera_videos=[v for v in videos if v.role in {'camera','camera_and_subject_motion'}]
    if len(camera_videos)>1 or camera_videos and camera and camera.movement:
        raise PydanticCustomError('direction_error','Scegli una sola sorgente per il movimento camera: menu oppure un Video guida. Inquadratura e angolazione restano combinabili.')
    motion_targets=set()
    for ref in [*pictures,*videos]:
        g=ref.guidance
        if any(not m.figure.strip() or (m.role in {'camera_start','camera_direction'}) == (m.subject is not None) for m in g.mappings):
            raise PydanticCustomError('guide_error','Completa ogni figura: testo del segno e Subject esplicito; i segni della camera non identificano un Subject.')
        if ref.role=='style' and g.mappings:raise PydanticCustomError('guide_error','La guida di stile non assegna figure ai Subject.')
        if ref.role!='frame_anchor' and (g.anchor is not None or g.at_s is not None or g.workflow or g.continuity_checked):
            raise PydanticCustomError('guide_error','I parametri frame anchor richiedono il ruolo Frame anchor.')
        if not (ref.confirmed and ref.linked_to_h3 and ref.description_en.strip()):
            raise PydanticCustomError('guide_error','Conferma descrizione, mapping e collegamento della guida attiva.')
        if any(m.subject is not None and m.subject not in units for m in g.mappings):
            raise PydanticCustomError('guide_error','Il mapping della guida richiama un Subject non attivo.')
        if ref.role in {'spatial_map','composition_previz','initial_composition','subject_motion','camera_and_subject_motion'} and not g.mappings:
            raise PydanticCustomError('guide_error','La guida richiede un mapping esplicito delle figure o dei segni.')
        if ref.role in {'subject_motion','camera_and_subject_motion'}:
            if any(m.role!='motion' for m in g.mappings):raise PydanticCustomError('guide_error','Il Video guida di movimento richiede mapping di tipo Movimento Subject.')
            targets={m.subject for m in g.mappings}
            if targets & motion_targets:raise PydanticCustomError('guide_error','Un Subject non può ricevere il movimento da due Video guida attivi.')
            motion_targets |= targets
        if ref.role=='camera' and g.mappings:raise PydanticCustomError('guide_error','Una guida sola camera non assegna figure ai Subject.')
        if ref.role=='frame_anchor':
            if not g.anchor or not g.workflow.strip():raise PydanticCustomError('guide_error','Il frame anchor richiede posizione del frame e workflow compatibile dichiarato.')
            if g.anchor=='keyframe' and (g.at_s is None or g.at_s<=0):raise PydanticCustomError('guide_error','Il keyframe richiede un tempo esplicito maggiore di zero.')
            if g.anchor!='keyframe' and g.at_s is not None:raise PydanticCustomError('guide_error','Il tempo esplicito appartiene al keyframe; primo/ultimo frame seguono gli estremi del cut.')
            if data.continuity.seamless and not g.continuity_checked:raise PydanticCustomError('guide_error','Verifica e dichiara la compatibilità del frame anchor con il raccordo seamless.')
    anchors=[p.guidance.anchor for p in pictures if p.role=='frame_anchor']
    if any(anchors.count(a)>1 for a in ['first','last']):raise PydanticCustomError('guide_error','Scegli un solo primo frame e un solo ultimo frame per il cut.')
    known={f'<Subject {u}>' for u in units}|{f'<Picture {p.slot}>' for p in data.active_pictures}|{v.token for v in data.active_videos}|{a.token for a in data.audio_references}
    for ref in [*pictures,*videos]:
        if set(re.findall(r'<[^>]*>',ref.guidance.prompt_en))-known or '<' in re.sub(r'<[^>]*>','',ref.guidance.prompt_en):raise PydanticCustomError('guide_error','Il prompt guida usa riferimenti H3 non attivi o malformati.')
