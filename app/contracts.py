"""Contratto HTTP M2, distinto dal contratto minimo di interpretazione M0."""
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.domain import CompileCommand, CompileResult, DialogueDelivery, DTO, ManualPromptCommand, Metrics, NarratorVoice
from app.direction import CameraDirection
from app.shots import CameraPreset


class SaveCameraPresetCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    expected_preset_revision: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=120)
    camera: CameraDirection


class DraftCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    # Una bozza incompleta deve poter essere conservata. CompileInput si valida
    # soltanto prima dell'inferenza, senza perdere i campi non ancora confermati.
    input: dict[str, Any]


class AddItemCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    kind: Literal["unit", "dialogue", "picture", "audio", "video"]


class AddSourceCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    subject: int = Field(ge=1)


class InlineDialogueChoice(DTO):
    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    language: str = Field(pattern=r"^[A-Za-z][A-Za-z -]*$")
    speaker_subject: int | None = Field(default=None, ge=1)
    delivery: DialogueDelivery = Field(default="on_screen", exclude_if=lambda value: value == "on_screen")
    narrator_voice: NarratorVoice | None = Field(default=None, exclude_if=lambda value: value is None)


class ImportDialoguesCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    source_request: str
    dialogues: list[InlineDialogueChoice] = Field(min_length=1, max_length=30)
    confirmed: Literal[True]


class WebCompileCommand(CompileCommand):
    model: str | None = Field(default=None, min_length=1)


class WebManualPromptCommand(ManualPromptCommand):
    base_candidate_id: UUID | None = None


class PromptVersion(DTO):
    id: UUID
    origin: Literal["generated", "manual"]
    text: str
    input_hash: str
    input_revision: int
    duration_s: float | None = None
    duration_origin: Literal["declared", "estimated", "measured"] | None = None
    structural_checks_passed: bool
    user_approved: bool = False
    issues: list[str] = Field(default_factory=list)
    # Snapshot separato dal testo: serve al riuso dei riferimenti e alla futura
    # migrazione SQLite. None significa versione storica senza snapshot noto.
    input_snapshot: dict[str, Any] | None = None
    base_candidate_id: UUID | None = None
    media_snapshot: dict[str, Any] = Field(default_factory=dict)


class JobView(DTO):
    id: UUID
    cut_id: UUID
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    input_revision: int
    input_hash: str
    model: str
    result: CompileResult | None = None
    candidate_id: UUID | None = None
    stale: bool = False


class CutView(DTO):
    id: UUID
    revision: int
    draft_input: dict[str, Any]
    state: Literal["draft", "queued", "compiling", "proposal", "clarification_needed", "error", "confirmed"]
    latest_job: JobView | None = None
    latest_candidate_id: UUID | None = None
    manual_version_id: UUID | None = None
    versions: list[PromptVersion] = Field(default_factory=list)
    catalogue_issues: list[str] = Field(default_factory=list)
    scene_id: UUID | None = None
    project_id: UUID | None = None
    number: int = 1
    title: str = "Cut 1"
    confirmed_version_id: UUID | None = None
    unit_ids: dict[str, str] = Field(default_factory=dict)
    media_by_picture: dict[str, Any] = Field(default_factory=dict)
    reference_revisions: dict[str, int] = Field(default_factory=dict)
    unit_revisions: dict[str, int] = Field(default_factory=dict)
    confirmation_issues: dict[str, list[str]] = Field(default_factory=dict)
    tokens: list[dict[str, str]] = Field(default_factory=list)
    proxy_by_picture: dict[str, Any] = Field(default_factory=dict)
    assistance_jobs: list[dict[str, Any]] = Field(default_factory=list)
    audio_media: dict[str, Any] = Field(default_factory=dict)
    video_media: dict[str, Any] = Field(default_factory=dict)
    context_media: dict[str, Any] | None = None
    output_by_version: dict[str, Any] = Field(default_factory=dict)
    previous_cut: dict[str, Any] | None = None
    reference_updates: list[str] = Field(default_factory=list)
    camera_presets: list[CameraPreset] = Field(default_factory=list)


class NamedCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=120)


class CreateCutCommand(NamedCommand):
    # Mantiene l'impronta dei comandi precedenti quando l'opzione è omessa.
    inherit_references: bool = Field(default=False, exclude_if=lambda value: not value)


class RevisionCommand(DTO):
    command_id: UUID
    expected_revision: int = Field(ge=0)


class TrashCommand(RevisionCommand):
    trashed: bool


class LibraryTrashCommand(TrashCommand):
    expected_reference_revision: int = Field(ge=1)


class ExportSelection(DTO):
    scope: Literal['cut','scene','project']
    resource_id: UUID
    policy: Literal['confirmed','latest'] = 'confirmed'
    versions: dict[str, UUID] = Field(default_factory=dict)
    reference_notes: bool = True


class PurgeSelection(DTO):
    scope: Literal['trash','cut','scene','project'] = 'trash'
    resource_id: UUID | None = None


class PurgeCommand(DTO):
    command_id: UUID
    selection: PurgeSelection
    plan_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]
    confirmation: Literal['ELIMINA']


class FinalizeCommand(RevisionCommand):
    finalized: bool


class ConfirmVersionCommand(RevisionCommand):
    version_id: UUID
    acknowledge_reference_changes: bool = False


class ReuseCommand(RevisionCommand):
    kind: Literal["picture", "unit"]
    reference_id: UUID
    # Se le dipendenze del Subject non sono ancora nel cut, slot assegnati
    # esplicitamente dal client dopo aver mostrato il riepilogo all'utente.
    slots: dict[str, int] = Field(default_factory=dict)


class AttachMediaCommand(RevisionCommand):
    media_id: UUID


class AttachOutputCommand(AttachMediaCommand):
    version_id: UUID


class ReuseContextCommand(RevisionCommand):
    subject: int = Field(ge=1)


class PasswordCommand(DTO):
    password: str = Field(min_length=1, max_length=256)


class AccessSettingsCommand(DTO):
    enabled: bool
    current_password: str = Field(default='', max_length=256, repr=False)
    password: str = Field(default='', max_length=256, repr=False)


class ConnectionSettingsCommand(RevisionCommand):
    ollama_url: str = Field(max_length=500)
    api_key: str | None = Field(default=None, max_length=1024, repr=False)
    remove_api_key: bool = False
    timeout_s: int = Field(default=120, ge=10, le=600)


class ConnectionTrialCommand(DTO):
    kind: Literal['text', 'vision']
    model: str = Field(min_length=1, max_length=300)


class AssistanceCommand(RevisionCommand):
    kind: Literal["image_analyze", "image_character_sheet", "image_object_sheet", "vision_trial", "description_translate", "audio_asr"]
    target_id: str | None = None
    model: str = Field(min_length=1)
    force: bool = False


class AssistanceResult(DTO):
    status: Literal["proposal", "error"]
    text: str | None = None
    language: str | None = None
    recognized: dict[str, bool] | None = None
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    metrics: Metrics | None = None


class ModelSettingsCommand(RevisionCommand):
    text_model: str = Field(min_length=1)
    vision_model: str | None = None


class CutSummary(DTO):
    id: UUID
    scene_id: UUID
    number: int
    title: str
    revision: int
    state: str
    confirmed_version_id: UUID | None
    duration_s: float | None = None
    duration_origin: Literal["declared", "estimated", "measured"] | None = None
    selected_version_id: str | None = None
    output_duration_s: float | None = None


class SceneView(DTO):
    id: UUID
    project_id: UUID
    number: int
    title: str
    revision: int
    finalized: bool
    trashed: bool
    cuts: list[CutSummary] = Field(default_factory=list)
    trashed_cuts: list[CutSummary] = Field(default_factory=list)


class ProjectView(DTO):
    id: UUID
    name: str
    revision: int
    created_at: str
    updated_at: str
    trashed: bool
    scenes: list[SceneView] = Field(default_factory=list)


class HealthView(DTO):
    app_ok: Literal[True] = True
    ollama_available: bool
    default_model: str


class ModelView(DTO):
    name: str
    digest: str
