"""Piano ordinato del modello: azioni ed eventi restano elementi distinti."""
from typing import Literal

from pydantic import Field, model_validator

from app.compiler import StructuralError
from app.direction import guide_key
from app.domain import CompileInput, CurrentInterpretation, DTO, PhysicalDetailTranslation, ScaleTranslation
from app.physical import detail_entries
from app.scale import scale_entries
from app.shots import shot_cues
from app.voice import voice_translations


class ActionPart(DTO):
    action_en: str = Field(min_length=1)


class DialoguePart(DTO):
    dialogue_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class OffScreenAudioPart(DTO):
    off_screen_audio_id: str = Field(pattern=r"^a[1-9][0-9]*$")
    listener_subject: int | None = Field(default=None, ge=1)


class ShotPart(DTO):
    shot_id: str = Field(pattern=r"^s[1-9][0-9]*$")


class GuidePart(DTO):
    guide_id: str = Field(pattern=r"^(picture|video)_[1-9][0-9]*$")


class CameraPart(DTO):
    camera_id: Literal['main']


class NarrativePlan(DTO):
    narrative_parts: list[ActionPart | DialoguePart | OffScreenAudioPart | ShotPart | GuidePart | CameraPart] | None = Field(min_length=1)
    summary_en: str | None = Field(min_length=1, max_length=700)
    soundscape_en: str | None = None
    voice_tones_en: dict[str, str] | None = None
    physical_details_en: dict[str, PhysicalDetailTranslation] | None = None
    scales_en: dict[str, ScaleTranslation] | None = None
    estimated_duration_s: float | None = Field(ge=0, allow_inf_nan=False)
    question: str | None

    @model_validator(mode="after")
    def proposal_or_question(self):
        if self.question is not None:
            if not self.question.strip() or any(value is not None for value in
                    (self.narrative_parts, self.summary_en, self.soundscape_en, self.voice_tones_en, self.physical_details_en, self.scales_en, self.estimated_duration_s)):
                raise ValueError("Una domanda non contiene una proposta parziale.")
        elif not self.narrative_parts or not (self.summary_en or "").strip() or self.estimated_duration_s is None:
            raise ValueError("La proposta richiede azioni ordinate, riassunto e stima.")
        return self

    def interpretation(self) -> CurrentInterpretation:
        if self.narrative_parts is None:
            narrative = None
        else:
            pieces = []
            for part in self.narrative_parts:
                if isinstance(part, ActionPart):
                    if not part.action_en.strip() or any(marker in part.action_en for marker in ("{{", "}}")):
                        raise StructuralError("Il modello ha inserito un evento o un’azione vuota nel campo delle azioni. Le battute, le guide e le inquadrature devono essere elementi separati.")
                    pieces.append(part.action_en)
                elif isinstance(part, DialoguePart):
                    pieces.append("{{dialogue:" + part.dialogue_id + "}}")
                elif isinstance(part, OffScreenAudioPart):
                    listener = f":{part.listener_subject}" if part.listener_subject is not None else ""
                    pieces.append("{{dialogue:" + part.off_screen_audio_id + ":off_screen" + listener + "}}")
                elif isinstance(part, ShotPart):
                    pieces.append("{{shot:" + part.shot_id + "}}")
                elif isinstance(part, CameraPart):
                    pieces.append('{{camera:main}}')
                else:
                    pieces.append("{{guide:" + part.guide_id + "}}")
            # Concatenazione in ordine, senza aggiungere punti o riscrivere azioni.
            narrative = " ".join(pieces)
        return CurrentInterpretation(narrative_en=narrative, summary_en=self.summary_en,
            soundscape_en=self.soundscape_en, voice_tones_en=self.voice_tones_en,
            physical_details_en=self.physical_details_en,
            scales_en=self.scales_en,
            estimated_duration_s=self.estimated_duration_s, question=self.question)


def response_schema(data: CompileInput) -> dict:
    data = data.effective()
    """Il decoder può scegliere solo gli eventi realmente disponibili nel cut."""
    schema = NarrativePlan.model_json_schema()
    speech_audio_ids = [audio.id for audio in data.audio_references if audio.role == "speech"]
    choices = {
        "DialoguePart": ("dialogue_id", [d.id for d in data.dialogues] + speech_audio_ids),
        "OffScreenAudioPart": ("off_screen_audio_id", speech_audio_ids),
        "ShotPart": ("shot_id", [cue["id"] for cue in shot_cues(data.request, data.shot_presets, data.declared_duration_s)]),
        "GuidePart": ("guide_id", [guide_key(ref, kind) for kind, refs in
            [("picture", data.active_picture_guides), ("video", data.active_video_guides)] for ref in refs]),
        "CameraPart": ('camera_id', ['main'] if data.camera and data.camera.active else []),
    }
    array = next(branch for branch in schema["properties"]["narrative_parts"]["anyOf"] if branch.get("type") == "array")
    allowed = []
    for branch in array["items"]["anyOf"]:
        name = branch["$ref"].rsplit("/", 1)[-1]
        if name in choices:
            field, ids = choices[name]
            if not ids:
                continue
            schema["$defs"][name]["properties"][field]["enum"] = ids
        allowed.append(branch)
    array["items"]["anyOf"] = allowed
    if speech_audio_ids:
        off_screen = schema["$defs"]["OffScreenAudioPart"]
        off_screen["required"].append("listener_subject")
        off_screen["properties"]["listener_subject"] = {
            "enum": [None] + [unit.subject for unit in data.active_units if unit.role == "character"],
        }
    properties = schema["properties"]
    tones = voice_translations(data)
    tone_schema = dict(type='object', additionalProperties=False, required=list(tones),
                       properties={id:dict(type='string', minLength=1, maxLength=500) for id in tones}) if tones else dict(type='null')
    proposal = {
        "type": "object", "additionalProperties": False,
        "required": list(properties),
        "properties": {
            "narrative_parts": array,
            "summary_en": dict(type="string", minLength=1, maxLength=700),
            "soundscape_en": dict(type="string", minLength=1) if data.custom_soundscape else dict(type="null"),
            "voice_tones_en": tone_schema,
            "physical_details_en": dict(type='object', additionalProperties=False,
                required=list(detail_entries(data)), properties={key: {'$ref': '#/$defs/PhysicalDetailTranslation'}
                    for key in detail_entries(data)}) if detail_entries(data) else dict(type='null'),
            "scales_en": dict(type='object', additionalProperties=False,
                required=list(scale_entries(data)), properties={key: {'$ref': '#/$defs/ScaleTranslation'}
                    for key in scale_entries(data)}) if scale_entries(data) else dict(type='null'),
            "estimated_duration_s": dict(type="number", minimum=0),
            "question": dict(type="null"),
        },
    }
    question = {
        "type": "object", "additionalProperties": False,
        "required": list(properties),
        "properties": {field: (dict(type="string", minLength=1) if field == "question" else dict(type="null"))
                       for field in properties},
    }
    # Il decoder sceglie una proposta completa oppure una sola domanda: mai
    # una risposta parziale con suoni obbligatori omessi o posti a null.
    return {"$defs": schema["$defs"], "anyOf": [proposal, question]}
