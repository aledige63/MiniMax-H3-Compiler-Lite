"""DTO condivisi: dati certi separati dal piccolo piano del modello."""
from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError
from app.direction import CameraDirection, GuideUsage, IMAGE_GUIDE_ROLES, VIDEO_GUIDE_ROLES, validate_direction
from app.shots import CameraPreset, shot_cues
from app.validation import completion_issues
from app.voice import validate_voice_fields
from app.image_profiles import CATEGORIES, LEVELS, VIEWS


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ImageAnalysisSettings(DTO):
    category: str = Field(default='auto', exclude_if=lambda value: value == 'auto', json_schema_extra={'enum': sorted(CATEGORIES)})
    level: str = Field(default='compact', exclude_if=lambda value: value == 'compact', json_schema_extra={'enum': sorted(LEVELS)})
    attribute: str = Field(default='', max_length=300, exclude_if=lambda value: not value)
    view: str = Field(default='', exclude_if=lambda value: not value, json_schema_extra={'enum': sorted(VIEWS)})

    @model_validator(mode='after')
    def valid_choices(self):
        if self.category not in CATEGORIES or self.level not in LEVELS or self.view not in VIEWS:
            raise ValueError('Scegli categoria, livello e vista disponibili per l’analisi immagine.')
        if any(char in self.attribute for char in '<>{}\r\n'):
            raise ValueError('L’attributo da analizzare deve essere testo semplice su una riga, senza tag.')
        return self


class PictureReference(DTO):
    id: str = Field(min_length=1)
    slot: int = Field(ge=1, le=9)
    name: str = ""
    role: Literal["identity", "appearance", "outfit", "shoes", "environment", "object", "scale_reference", "style", "spatial_map", "composition_previz", "initial_composition", "frame_anchor"] = "identity"
    description_en: str = ""
    confirmed: bool = False
    linked_to_h3: bool = False
    description_language: str = "English"
    use_original_language: bool = False
    original_description: str | None = None
    original_language: str | None = None
    guidance: GuideUsage | None = None
    analysis: ImageAnalysisSettings | None = Field(default=None, exclude_if=lambda value: value is None or not value.model_dump())
    excluded: Literal[False] = Field(default=False, exclude_if=lambda value: not value)


class ExcludedPicture(DTO):
    """Un riferimento escluso conserva anche una bozza ancora incompleta."""
    model_config = ConfigDict(extra='allow', frozen=True, strict=True)
    id: str = Field(min_length=1)
    slot: int = Field(ge=1, le=9)
    excluded: Literal[True]


class ExcludedUnit(DTO):
    model_config = ConfigDict(extra='allow', frozen=True, strict=True)
    subject: int = Field(ge=1)
    excluded: Literal[True]


class Source(DTO):
    # Forma precedente per fixture/CLI M0; nel catalogo nuovo si usa solo l'ID.
    picture_slot: int | None = Field(default=None, ge=1, le=9)
    picture_id: str | None = None
    attribute: Literal["identity", "appearance", "outfit", "shoes", "environment", "object"]
    linked_to_h3: bool = False
    origin: Literal["picture", "context"] = "picture"

    @model_validator(mode="after")
    def explicit_origin(self):
        if self.origin == "context" and (self.picture_id is not None or self.picture_slot is not None):
            raise PydanticCustomError('continuity_error', "Una sorgente dal contesto non usa una Picture fittizia.")
        return self


class PhysicalDetail(DTO):
    id: str = Field(pattern=r"^p[1-9][0-9]*$")
    description: str = Field(min_length=1, max_length=500)
    body_location: str = Field(min_length=1, max_length=150)
    operation: Literal["add", "replace", "modify"]
    picture_id: str | None = None
    origin: Literal["picture", "context"] = "picture"

    @model_validator(mode="after")
    def explicit_detail(self):
        for text in (self.description, self.body_location):
            if not text.strip() or any(c in text for c in "<>{}[]\r\n"):
                raise ValueError("Descrizione e posizione del dettaglio fisico devono essere testo semplice su una riga, senza tag.")
        if self.origin == "context" and self.picture_id is not None:
            raise ValueError("Un dettaglio dal contesto non richiede una Picture fittizia.")
        return self


class PhysicalDetailTranslation(DTO):
    description_en: str = Field(min_length=1, max_length=500)
    body_location_en: str = Field(min_length=1, max_length=150)


class SubjectScale(DTO):
    measurements: str = Field(default='', max_length=500)
    comparison: str = Field(default='', max_length=700)
    # L'UUID è l'identità; il numero è risolto nella scena del cut.
    reference_subject_id: str | None = None
    reference_subject: int | None = Field(default=None, ge=1)
    picture_id: str | None = None

    @model_validator(mode='after')
    def explicit_scale(self):
        if not (self.measurements.strip() or self.comparison.strip()):
            raise ValueError('Dimensioni e scala: indica le misure oppure un confronto dimensionale.')
        for text in (self.measurements, self.comparison):
            if any(c in text for c in '<>{}[]\r\n'):
                raise ValueError('Misure e confronto dimensionale devono essere testo semplice su una riga, senza tag.')
        if (self.reference_subject_id or self.reference_subject is not None or self.picture_id) and not self.comparison.strip():
            raise ValueError('Descrivi il confronto dimensionale mostrato nella Picture o riferito all’altro Subject.')
        if self.reference_subject_id and self.reference_subject is None:
            raise ValueError('Il Subject di confronto non è disponibile: aggiungilo al cut oppure scegli un altro riferimento.')
        if self.reference_subject is not None and not self.reference_subject_id:
            raise ValueError('Scegli il Subject di confronto dal menu per conservarne l’identità.')
        return self


class ScaleTranslation(DTO):
    measurements_en: str = Field(max_length=500)
    comparison_en: str = Field(max_length=700)


class VisualUnit(DTO):
    subject: int = Field(ge=1)
    name: str = Field(min_length=1)
    role: Literal["character", "environment", "object"]
    description_en: str = ""
    definition_mode: Literal["picture", "manual"] = "picture"
    confirmed: bool
    sources: list[Source] = Field(min_length=1)
    physical_details: list[PhysicalDetail] = Field(default_factory=list, max_length=20, exclude_if=lambda value: not value)
    scale: SubjectScale | None = Field(default=None, exclude_if=lambda value: value is None)
    excluded: Literal[False] = Field(default=False, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def character_details(self):
        if self.physical_details and self.role != "character":
            raise ValueError("I dettagli fisici richiedono un Subject con ruolo Personaggio.")
        ids = [detail.id for detail in self.physical_details]
        if len(ids) != len(set(ids)):
            raise ValueError("Gli ID dei dettagli fisici devono essere univoci nel Subject.")
        return self

    @property
    def token(self) -> str:
        return f"<Subject {self.subject}>"


def definition_picture(unit: dict, pictures: list[dict] | None):
    """La descrizione segue la sorgente identificativa, mai l'abito per caso."""
    attribute = {"character": "identity", "environment": "environment", "object": "object"}.get(unit.get('role'))
    sources = unit.get('sources', [])
    primary = next((s for s in sources if s.get('attribute') == attribute), None)
    if primary is None:
        primary = next((s for s in sources if s.get('attribute') == 'appearance'), None)
    if not primary or primary.get('origin', 'picture') != 'picture': return None
    return next((p for p in pictures or [] if p.get('id') == primary.get('picture_id')), None)


def resolved_definition(unit: dict, pictures: list[dict] | None) -> str:
    picture = definition_picture(unit, pictures) if unit.get('definition_mode', 'picture') == 'picture' else None
    return (picture.get('description_en', '') if picture else unit.get('description_en', '')).strip()


DialogueDelivery = Literal["on_screen", "off_screen", "narrator"]
NarratorVoice = Literal["male", "female"]


class Dialogue(DTO):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str = Field(min_length=1)
    language: str = Field(pattern=r"^[A-Za-z][A-Za-z -]*$")
    speaker_subject: int | None = Field(default=None, ge=1)
    origin: Literal["native"] = "native"
    confirmed: bool
    # L'omissione del default conserva hash e ricevute delle vecchie compilazioni.
    delivery: DialogueDelivery = Field(default="on_screen", exclude_if=lambda value: value == "on_screen")
    narrator_voice: NarratorVoice | None = Field(default=None, exclude_if=lambda value: value is None)
    voice_tone: str = Field(default="", max_length=500, exclude_if=lambda value: not value)
    voice_emotion: str = Field(default="", exclude_if=lambda value: not value)
    voice_mode: str = Field(default="", exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def speaker_matches_delivery(self):
        validate_voice_fields(self)
        if self.delivery == "narrator":
            if self.speaker_subject is not None:
                raise ValueError("La voce narrante è indipendente dai Subject.")
        else:
            if self.narrator_voice is not None:
                raise ValueError("La scelta della voce è disponibile per la voce narrante.")
            if self.speaker_subject is None:
                raise ValueError("Scegli il personaggio che pronuncia la battuta.")
        return self

    @property
    def speaker_label(self) -> str:
        if self.delivery != "narrator":
            return f"<Subject {self.speaker_subject}>"
        return f"An unseen narrator with a {self.narrator_voice} voice" if self.narrator_voice else "An unseen narrator"


class Continuity(DTO):
    mode: Literal["none", "video_reference", "tail_frames", "latent"] = "none"
    declared_state: str | None = None
    previous_cut_id: str | None = None
    previous_version_id: str | None = None
    external_source: str | None = None
    video_id: str | None = None
    context_media_id: str | None = None
    context_media_kind: Literal["video", "image"] | None = None
    window_frames: int | None = Field(default=None, ge=1, le=10000)
    trim_frames: int | None = Field(default=None, ge=0, le=10000)
    sampling_prefix_frames: int | None = Field(default=None, ge=0, le=10000)
    seamless: bool = False

    @model_validator(mode="after")
    def state_matches_mode(self):
        if self.mode != "none" and not (self.declared_state or "").strip():
            raise PydanticCustomError('continuity_error', "La continuità richiede lo stato iniziale dichiarato dall’utente.")
        if self.mode == "none" and self.declared_state is not None:
            raise ValueError("Scegliere la modalità per uno stato di continuità.")
        if self.mode == "none" and (any(v is not None for v in [self.previous_cut_id, self.previous_version_id,
                self.external_source, self.video_id, self.context_media_id, self.context_media_kind,
                self.window_frames, self.trim_frames, self.sampling_prefix_frames]) or self.seamless):
            raise ValueError("Nessuna continuità non può mantenere un raccordo nascosto.")
        if self.previous_version_id and not self.previous_cut_id:
            raise ValueError("La versione di origine richiede il cut precedente.")
        if self.previous_cut_id and not self.previous_version_id:
            raise PydanticCustomError('continuity_error', "Scegli la versione precisa del cut precedente, oppure dichiara una sorgente esterna.")
        if self.previous_cut_id and self.external_source:
            raise ValueError("Scegliere un cut precedente oppure una sorgente esterna.")
        if self.mode != "video_reference" and self.video_id:
            raise ValueError("Solo il raccordo video reference assegna uno slot Video.")
        if self.mode == "video_reference" and not self.video_id:
            raise ValueError("Scegliere un Video effettivo per il raccordo video reference.")
        if bool(self.context_media_id) != bool(self.context_media_kind):
            raise ValueError("Il media di contesto richiede tipo e identificatore.")
        if self.context_media_id and self.mode not in {"tail_frames", "latent"}:
            raise ValueError("Il media di contesto appartiene al percorso frame/pixel o latente.")
        return self


class VideoReference(DTO):
    id: str = Field(pattern=r"^v[1-9][0-9]*$")
    slot: int = Field(ge=1, le=3)
    name: str = ""
    role: Literal["continuation", "camera", "subject_motion", "camera_and_subject_motion"] = "continuation"
    guidance: GuideUsage | None = None
    description_en: str = "the source clip for continuation"
    media_id: str | None = None
    duration_s: float | None = Field(default=None, gt=0, le=600, allow_inf_nan=False)
    duration_origin: Literal["declared", "measured"] = "declared"
    file_exists: bool = False
    linked_to_h3: bool = False
    confirmed: bool = False

    @property
    def token(self): return f"<Video {self.slot}>"

    @model_validator(mode="after")
    def plain_description(self):
        if any(c in self.name + self.description_en for c in "<>\r\n"):
            raise ValueError("Nome e descrizione Video devono essere testo semplice su una riga.")
        return self


class AudioReference(DTO):
    id: str = Field(pattern=r"^a[1-9][0-9]*$")
    slot: int = Field(ge=1, le=3)
    media_id: str = Field(min_length=1)
    name: str = ""
    mode: Literal["copy", "reference"] = "copy"
    role: Literal["speech", "sound", "voice"] = "speech"
    measured_duration_s: float = Field(gt=0, allow_inf_nan=False)
    sample_rate: int = Field(gt=0)
    sample_count: int = Field(gt=0)
    channels: int = Field(ge=1)
    segment_start_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    segment_end_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    offset_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    speaker_subject: int | None = Field(default=None, ge=1)
    language: str = Field(default="Italian", pattern=r"^[A-Za-z][A-Za-z -]*$")
    transcript: str = ""
    description_en: str = ""
    confirmed: bool = False
    linked_to_h3: bool = False
    exclusive_full_track: bool = False
    voice_tone: str = Field(default="", max_length=500, exclude_if=lambda value: not value)
    voice_emotion: str = Field(default="", exclude_if=lambda value: not value)
    voice_mode: str = Field(default="", exclude_if=lambda value: not value)

    @property
    def token(self):
        return f"<Audio {self.slot}>"

    @property
    def end_s(self):
        return self.segment_end_s if self.segment_end_s is not None else self.measured_duration_s

    @property
    def useful_duration_s(self):
        return self.end_s - self.segment_start_s

    @model_validator(mode="after")
    def coherent_audio(self):
        validate_voice_fields(self)
        if abs(self.measured_duration_s - self.sample_count / self.sample_rate) > 1 / self.sample_rate:
            raise ValueError("La durata audio deve corrispondere ai campioni misurati.")
        if self.end_s > self.measured_duration_s + 1 / self.sample_rate or self.end_s <= self.segment_start_s:
            raise ValueError("Il segmento audio deve essere compreso nel file misurato.")
        if self.useful_duration_s > 15 + 1 / self.sample_rate or (self.role != "voice" and self.offset_s + self.useful_duration_s > 15 + 1 / self.sample_rate):
            raise ValueError("Audio oltre 15 secondi: scegliere un segmento effettivo, senza accelerarlo o troncarlo automaticamente.")
        if not self.confirmed or not self.linked_to_h3:
            raise ValueError("Confermare contenuto e collegamento dell'audio a H3.")
        if self.role == "speech" and (not self.speaker_subject or not self.transcript.strip()):
            raise ValueError("Il parlato da file richiede trascrizione verificata e parlante esplicito.")
        if self.role == "voice" and (self.mode != "reference" or not self.speaker_subject):
            raise ValueError("Il solo timbro vocale richiede modalità riferimento e un parlante.")
        if self.role == "sound" and not self.description_en.strip():
            raise ValueError("Descrivere il ruolo sonoro richiesto per l'audio.")
        if any(c in self.transcript for c in "<>") or "{{" in self.transcript:
            raise ValueError("Delimitatori H3 riservati non ammessi nella trascrizione.")
        if any(c in self.name + self.description_en for c in "<>\r\n"):
            raise ValueError("Nome e descrizione audio devono essere testo semplice su una riga.")
        return self


class CompileInput(DTO):
    profile: Literal["H3-Base-Ref2VA"] = "H3-Base-Ref2VA"
    request: str = Field(min_length=1)
    active_units: list[VisualUnit | ExcludedUnit] = Field(default_factory=list)
    pictures: list[PictureReference | ExcludedPicture] | None = None
    dialogues: list[Dialogue] = Field(default_factory=list)
    audio_references: list[AudioReference] = Field(default_factory=list, max_length=3)
    videos: list[VideoReference] = Field(default_factory=list, max_length=3)
    continuity: Continuity = Field(default_factory=Continuity)
    declared_duration_s: float | None = Field(default=None, ge=4, le=15)
    ambient_sound: bool = True
    camera: CameraDirection | None = None
    soundscape_text: str = Field(default="", exclude_if=lambda value: value == "")
    shot_presets: list[CameraPreset] = Field(default_factory=list, exclude_if=lambda value: not value)

    @model_validator(mode="before")
    @classmethod
    def required_fields_and_confirmations(cls, value):
        if isinstance(value, dict):
            for key in ['pictures','active_units']:
                for item in value.get(key) or []:
                    if isinstance(item, dict) and 'excluded' in item and type(item['excluded']) is not bool:
                        raise ValueError('La spunta «Escludi da questo cut» deve essere attiva o disattiva.')
        issues = completion_issues(value)
        if issues:
            raise PydanticCustomError("input_incomplete", "{summary}", {"issues": issues, "summary": "\n".join(issues)})
        return value

    @model_validator(mode="after")
    def coherent_catalog(self):
        if any(u.excluded for u in self.active_units) or any(p.excluded for p in self.pictures or []):
            if len({u.subject for u in self.active_units}) != len(self.active_units):
                raise ValueError('Identificatori Subject duplicati, compresi quelli esclusi.')
            if self.pictures is not None:
                if len({p.id for p in self.pictures}) != len(self.pictures):
                    raise ValueError('Identificatori Picture duplicati, comprese quelle escluse.')
                if len({p.slot for p in self.pictures}) != len(self.pictures):
                    raise ValueError('Slot Picture duplicati, comprese quelle escluse.')
            self.effective().coherent_catalog()
            return self
        subjects = [u.subject for u in self.active_units]
        ids = [d.id for d in self.dialogues]
        if len(subjects) != len(set(subjects)) or len(ids) != len(set(ids)):
            raise ValueError("Identificatori duplicati.")
        for unit in self.active_units:
            if unit.scale and unit.scale.reference_subject is not None:
                if unit.scale.reference_subject == unit.subject or unit.scale.reference_subject not in subjects:
                    raise ValueError(f'{unit.token} — scegli un altro Subject incluso nel cut per il confronto dimensionale.')
        if self.pictures is not None:
            if any(p.guidance and p.guidance.enabled and p.role not in IMAGE_GUIDE_ROLES for p in self.pictures):
                raise PydanticCustomError('guide_error', 'Scegli un ruolo guida per attivare la guida Picture.')
            picture_ids = [p.id for p in self.pictures]
            if len(picture_ids) != len(set(picture_ids)):
                raise PydanticCustomError("picture_catalogue_error", "Un'immagine è registrata due volte nel catalogo Picture.")
            by_slot = {}
            for picture in self.pictures:
                if picture.slot in by_slot:
                    raise PydanticCustomError("picture_slot_conflict",
                        "Picture {slot} è assegnato a due immagini distinte. Correggi lo slot nel catalogo immagini.",
                        {"slot": picture.slot})
                by_slot[picture.slot] = picture.id
            catalogue = {p.id: p for p in self.pictures}
            for unit in self.active_units:
                if unit.scale and unit.scale.picture_id:
                    picture = catalogue.get(unit.scale.picture_id)
                    if picture is None:
                        raise ValueError(f'{unit.token} — la Picture di riferimento dimensionale è rimossa o esclusa: scegli un’immagine disponibile.')
                    if picture.role in IMAGE_GUIDE_ROLES:
                        raise ValueError(f'{unit.token} — scegli una Picture ordinaria per la scala; le guide mantengono il proprio ruolo e mapping.')
                for detail in unit.physical_details:
                    if detail.origin == "context" and self.continuity.mode == "none":
                        raise ValueError(f"{unit.token} — il dettaglio fisico dal contesto richiede una continuità dichiarata.")
                    if detail.picture_id is None:
                        continue
                    picture = catalogue.get(detail.picture_id)
                    if picture is None:
                        raise PydanticCustomError("picture_catalogue_error", "Subject {subject} richiama una Picture rimossa nei dettagli fisici: scegli un’immagine oppure nessuna Picture.", {"subject": unit.subject})
                    if picture.role in IMAGE_GUIDE_ROLES:
                        raise ValueError(f"{unit.token} — una Picture guida non può essere la sorgente di un dettaglio fisico.")
                    if picture.role == 'scale_reference':
                        raise ValueError(f'{unit.token} — usa il Riferimento dimensionale nel campo Dimensioni e scala, non nei dettagli fisici.')
                seen = set()
                for source in unit.sources:
                    if source.origin == "context":
                        if self.continuity.mode == "none":
                            raise PydanticCustomError('continuity_error', "Le sorgenti dal contesto richiedono una continuità dichiarata.")
                        binding = ("context", source.attribute)
                        if binding in seen: raise ValueError("Sorgente di contesto duplicata per lo stesso attributo.")
                        seen.add(binding)
                        continue
                    if source.picture_slot is not None or source.picture_id not in catalogue:
                        raise PydanticCustomError("picture_catalogue_error",
                            "Subject {subject} richiama un'immagine mancante: scegli una Picture dal catalogo.", {"subject": unit.subject})
                    binding = (source.picture_id, source.attribute)
                    if binding in seen:
                        raise PydanticCustomError("picture_catalogue_error",
                            "Subject {subject} contiene due volte la stessa associazione immagine/attributo.", {"subject": unit.subject})
                    seen.add(binding)
                    picture = catalogue[source.picture_id]
                    if picture.role in IMAGE_GUIDE_ROLES:
                        raise PydanticCustomError('guide_error', 'Una Picture guida non definisce identità o abiti di un Subject: usa il suo mapping nel pannello guide.')
                    if picture.role == 'scale_reference':
                        raise ValueError(f'{unit.token} — una Picture con ruolo Riferimento dimensionale va scelta in Dimensioni e scala, non come sorgente di identità o aspetto.')
                    if not picture.confirmed or not picture.linked_to_h3 or not picture.description_en.strip():
                        raise PydanticCustomError("picture_catalogue_error",
                            "Conferma descrizione e collegamento di Picture {slot} prima di compilare.", {"slot": picture.slot})
            for picture in self.pictures:
                if any(c in picture.name + picture.description_en for c in "<>\n\r"):
                    raise ValueError("Nomi e descrizioni Picture devono essere testo semplice su una riga.")
            for picture in self.active_pictures:
                if picture.description_language != "English" and not picture.use_original_language:
                    raise ValueError("Traduci esplicitamente la descrizione oppure conferma l'uso nella lingua scelta.")
        elif any(s.origin == "picture" and (s.picture_slot is None or s.picture_id is not None) for u in self.active_units for s in u.sources):
            raise ValueError("I riferimenti per ID richiedono il catalogo Picture.")
        if self.pictures is None and any(d.picture_id for u in self.active_units for d in u.physical_details):
            raise ValueError("I dettagli fisici con Picture richiedono il catalogo immagini per ID.")
        if self.pictures is None and any(u.scale and u.scale.picture_id for u in self.active_units):
            raise ValueError('Il riferimento dimensionale con Picture richiede il catalogo immagini per ID.')
        if self.continuity.mode == "none" and any(d.origin == "context" for u in self.active_units for d in u.physical_details):
            raise ValueError("I dettagli fisici dal contesto richiedono una continuità dichiarata.")
        if any(s.origin == "context" for u in self.active_units for s in u.sources) and self.continuity.mode == "none":
            raise PydanticCustomError('continuity_error', "Le sorgenti dal contesto richiedono una continuità dichiarata.")
        if len({v.id for v in self.videos}) != len(self.videos) or len({v.slot for v in self.videos}) != len(self.videos):
            raise ValueError("ID e slot Video devono essere univoci nel cut.")
        if self.continuity.video_id and not any(v.id == self.continuity.video_id for v in self.videos):
            raise PydanticCustomError('video_error', "Il Video di continuità non è presente nel cut.")
        if any(v.guidance and v.guidance.enabled and v.role not in VIDEO_GUIDE_ROLES for v in self.videos):
            raise PydanticCustomError('guide_error', 'Un Video di continuazione non è anche una guida: scegli il suo ruolo esplicitamente.')
        if any(v.id == self.continuity.video_id and v.role != 'continuation' for v in self.videos):
            raise PydanticCustomError('video_error', 'La continuazione richiede un Video con ruolo Continuazione; le guide non sono il video da proseguire.')
        for video in self.active_videos:
            if not (video.file_exists and video.linked_to_h3 and video.confirmed and video.description_en.strip()):
                raise PydanticCustomError('video_error', "Confermare esistenza, descrizione e collegamento del Video selezionato.")
            if video.duration_s is None or not 2 <= video.duration_s <= 15:
                raise PydanticCustomError('video_error', "Ogni ingresso Video H3 deve avere durata effettiva fra 2 e 15 secondi.")
        if sum(v.duration_s for v in self.active_videos) > 15:
            raise ValueError("La somma degli ingressi Video H3 non può superare 15 secondi.")
        characters = {u.subject for u in self.active_units if u.role == "character"}
        if len({a.slot for a in self.audio_references}) != len(self.audio_references) or len({a.id for a in self.audio_references}) != len(self.audio_references):
            raise ValueError("Slot o identificatori audio duplicati.")
        if any(a.speaker_subject is not None and a.speaker_subject not in characters for a in self.audio_references):
            raise ValueError("Il parlante dell'audio deve essere un personaggio attivo.")
        for audio in self.audio_references:
            if audio.role == "voice" and not any(d.speaker_subject == audio.speaker_subject for d in self.dialogues):
                raise ValueError(f"{audio.token} · {audio.name or 'Traccia'} — aggiungi una battuta nativa di Subject {audio.speaker_subject} per usare il riferimento di solo timbro.")
        if any(a.id in ids for a in self.audio_references):
            raise ValueError("ID audio e battute devono essere distinti.")
        if self.declared_duration_s is not None:
            for audio in self.audio_references:
                if audio.role != "voice" and audio.offset_s + audio.useful_duration_s > self.declared_duration_s + 1 / audio.sample_rate:
                    raise ValueError(f"{audio.token} · {audio.name or 'Traccia'} — il segmento audio supera la durata dichiarata di {self.declared_duration_s:g} secondi. Controlla «Inizio nel cut», il segmento sorgente o la durata del cut.")
        if any(d.delivery != "narrator" and d.speaker_subject not in characters for d in self.dialogues):
            raise ValueError("Speaker non disponibile fra i personaggi attivi.")
        if any(not u.confirmed or (self.pictures is None and any(s.origin == "picture" and not s.linked_to_h3 for s in u.sources))
               for u in self.active_units):
            raise ValueError("Confermare descrizioni e collegamenti dei riferimenti.")
        if any(not d.confirmed or not d.text.strip() or "<" in d.text or "{{" in d.text
               for d in self.dialogues):
            raise ValueError("Confermare il parlato; delimitatori H3 riservati non ammessi in M0.")
        # I campi da template non possono introdurre token o intestazioni aggiuntive.
        for u in self.active_units:
            if not self.description_for(u):
                raise PydanticCustomError('picture_catalogue_error', "Completa la definizione di Subject {subject} o la descrizione della sua Picture identificativa.", {'subject': u.subject})
            if any(c in u.description_en + u.name for c in "<>\n\r"):
                raise ValueError("Descrizioni e nomi devono essere testo semplice su una riga.")
            if u.role == "character" and not any(s.attribute == "identity" for s in u.sources):
                raise ValueError(f"{u.token} · {u.name} — aggiungi una sorgente con attributo Identità.")
            allowed = {"character": {"identity", "appearance", "outfit", "shoes"},
                       "environment": {"environment", "appearance"}, "object": {"object", "appearance"}}[u.role]
            if any(s.attribute not in allowed for s in u.sources):
                raise PydanticCustomError("picture_role_conflict",
                    "Controlla le associazioni di Subject {subject}: un abito indossato va collegato al personaggio, "
                    "non usato come sorgente Abito di un Subject oggetto.", {"subject": u.subject})
        known = {f"<Subject {n}>" for n in subjects}
        available = {
            "Subject": known, "Audio": {a.token for a in self.audio_references},
            "Video": {v.token for v in self.active_videos},
        }
        if self.pictures is not None:
            available["Picture"] = {f"<Picture {p.slot}>" for p in self.active_pictures}
        for label, text in [
            ("Richiesta", self.request),
            ("Stato iniziale di continuità", self.continuity.declared_state or ""),
            ("Note di regia", self.camera.notes if self.camera else ""),
            ("Suoni ambientali personalizzati", self.custom_soundscape),
        ]:
            for kind, tokens in available.items():
                missing = set(re.findall(rf"<{kind} \d+>", text)) - tokens
                if missing:
                    raise ValueError(f"{label} — riferimenti non disponibili nel cut: {', '.join(sorted(missing))}. Controlla le associazioni oppure scegli un richiamo dal menu #.")
        validate_direction(self)
        cues = shot_cues(self.request, self.shot_presets, self.declared_duration_s)
        if cues and self.camera and self.camera.active:
            raise PydanticCustomError("shot_error", "Con gli Shot o i tag di inquadratura, rimuovi la regia generale del cut oppure salvala come inquadratura e richiamala nello Shot.")
        if any(cue["preset"] and cue["preset"].camera.movement for cue in cues) and any(v.role in {"camera", "camera_and_subject_motion"} for v in self.active_video_guides):
            raise PydanticCustomError("shot_error", "Scegli il movimento delle inquadrature salvate oppure la guida Video camera.")
        return self

    @property
    def custom_soundscape(self) -> str:
        return self.soundscape_text.strip() if not self.ambient_sound else ""

    @property
    def included_units(self) -> list[VisualUnit]:
        return [unit for unit in self.active_units if not unit.excluded]

    def effective(self) -> CompileInput:
        """Vista operativa; l’originale conserva tutti i riferimenti nello snapshot."""
        units = self.included_units
        pictures = [p for p in self.pictures if not p.excluded] if self.pictures is not None else None
        if len(units) == len(self.active_units) and (pictures is None or len(pictures) == len(self.pictures)):
            return self
        return self.model_copy(update={'active_units': units, 'pictures': pictures})

    def picture_for(self, source: Source) -> PictureReference | None:
        if self.pictures is None:
            return None
        return next(p for p in self.pictures if p.id == source.picture_id)

    def description_for(self, unit: VisualUnit) -> str:
        return resolved_definition(unit.model_dump(), [p.model_dump() for p in self.pictures] if self.pictures is not None else None)

    def slot_for(self, source: Source) -> int:
        picture = self.picture_for(source)
        return picture.slot if picture is not None else source.picture_slot

    @property
    def active_pictures(self) -> list[PictureReference]:
        used = {s.picture_id for u in self.included_units for s in u.sources}
        used |= {d.picture_id for u in self.included_units for d in u.physical_details}
        used |= {u.scale.picture_id for u in self.included_units if u.scale}
        used |= {p.id for p in self.active_picture_guides}
        return [p for p in self.pictures or [] if not p.excluded and p.id in used]

    @property
    def active_picture_guides(self) -> list[PictureReference]:
        return [p for p in self.pictures or [] if not p.excluded and p.role in IMAGE_GUIDE_ROLES and p.guidance and p.guidance.enabled]

    @property
    def active_video_guides(self) -> list[VideoReference]:
        return [v for v in self.videos if v.role in VIDEO_GUIDE_ROLES and v.guidance and v.guidance.enabled]

    @property
    def active_videos(self) -> list[VideoReference]:
        return [v for v in self.videos if v.id == self.continuity.video_id or v in self.active_video_guides]


class Interpretation(DTO):
    narrative_en: str | None
    estimated_duration_s: float | None = Field(ge=0, allow_inf_nan=False)
    question: str | None
    # Assente nei piani storici M0–M3: non ricostruire i prompt già conservati.
    summary_en: str | None = Field(default=None, min_length=1, max_length=700)
    soundscape_en: str | None = Field(default=None, exclude_if=lambda value: value is None)
    voice_tones_en: dict[str, str] | None = Field(default=None, exclude_if=lambda value: value is None)
    physical_details_en: dict[str, PhysicalDetailTranslation] | None = Field(default=None, exclude_if=lambda value: value is None)
    scales_en: dict[str, ScaleTranslation] | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def proposal_or_question(self):
        if self.question is not None:
            if not self.question.strip() or self.narrative_en is not None or self.estimated_duration_s is not None or self.summary_en is not None or self.soundscape_en is not None or self.voice_tones_en is not None or self.physical_details_en is not None or self.scales_en is not None:
                raise ValueError("Una domanda non contiene una proposta parziale.")
        elif not (self.narrative_en or "").strip() or self.estimated_duration_s is None:
            raise ValueError("La proposta richiede narrazione e stima.")
        return self


class CurrentInterpretation(Interpretation):
    """Contratto delle nuove inferenze; Interpretation legge anche lo storico."""
    summary_en: str | None = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def require_summary(self):
        if self.question is None and not (self.summary_en or "").strip():
            raise ValueError("La nuova proposta richiede un riassunto dell’azione.")
        return self


class CompileCommand(DTO):
    command_id: UUID
    cut_id: UUID
    expected_revision: int = Field(ge=0)
    input: CompileInput


class ConfirmCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    candidate_id: UUID
    user_approved: Literal[True]


class ManualPromptCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    text: str = Field(min_length=1)


class Metrics(DTO):
    model: str
    digest: str
    task: Literal["text_compile", "image_analyze", "image_character_sheet", "vision_trial", "description_translate", "audio_asr"] = "text_compile"
    inference_calls: int
    input_hash: str
    input_chars: int
    queue_s: float
    wall_s: float
    load_s: float | None = None
    prompt_eval_s: float | None = None
    eval_s: float | None = None
    total_s: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    done_reason: str | None = None
    error_code: str | None = None
    cache_hit: bool = False


class CompileResult(DTO):
    status: Literal["proposal", "clarification_needed", "error"]
    input_hash: str
    interpretation: Interpretation | None = None
    prompt: str | None = None
    duration_s: float | None = None
    duration_origin: Literal["declared", "estimated", "measured"] | None = None
    structural_checks_passed: bool = False
    user_approved: Literal[False] = False
    confirmation_allowed: bool = False
    issues: list[str] = Field(default_factory=list)
    error_code: str | None = None
    metrics: Metrics | None = None
