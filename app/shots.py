"""Inquadrature del progetto e richiami temporizzati nella richiesta."""
import json
import re
from contextlib import closing
from uuid import uuid4

from pydantic import Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from app.direction import CameraDirection, DirectionDTO
from app.store import StoreError

TAG = re.compile(r"(?<![\w#])#([a-zA-Z][a-zA-Z0-9_]*)\b")
REQUEST_SHOT = re.compile(r"\[shot\s+(?P<number>\d+)\]|(?<![\w#])#(?P<tag>[a-zA-Z][a-zA-Z0-9_]*)\b", re.IGNORECASE)
SHOT_EVENT = re.compile(r"\{\{shot:(s[1-9][0-9]*)\}\}(?:[ \t]*\.+)?[ \t]*")
TIME_PREFIX = re.compile(
    r"\b(?:a|at|al secondo)\s+(?P<time>\d{1,2}:\d{2}(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?)"
    r"\s*(?:second[oi]|seconds?|s)?\s*(?:[,\-]\s*)?"
    r"(?:(?:passa|passare|taglia|vai)\s+a\s+|(?:usa|use)\s+)?$",
    re.IGNORECASE,
)
TIME_SUFFIX = re.compile(
    r"\s*(?:a|at|al secondo)\s+(?P<time>\d{1,2}:\d{2}(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?)"
    r"(?![\d.:])\s*(?:second[oi]|seconds?|s)?\s*[,\-]?\s*", re.IGNORECASE,
)


class CameraPreset(DirectionDTO):
    id: str = Field(min_length=1)
    tag: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    camera: CameraDirection

    @model_validator(mode="after")
    def reusable_camera(self):
        if not self.name.strip() or not self.camera.active:
            raise PydanticCustomError("shot_error", "Assegna un nome e almeno una scelta di regia all’inquadratura.")
        if self.camera.subject or self.camera.dialogue_id or self.camera.placement != "as_requested":
            raise PydanticCustomError("shot_error", "Il Subject e il momento della ripresa si indicano nella richiesta del cut.")
        if any(char in self.name + self.camera.notes for char in "<>{}") or re.search(r"\[Shot|\b\w+_\w+\s*:", self.camera.notes):
            raise PydanticCustomError("shot_error", "Nome e note dell’inquadratura devono essere testo semplice, senza tag o sezioni.")
        return self


def shot_cues(request, presets, duration=None):
    """I tempi provengono dal testo dell'utente, mai da stime del modello."""
    by_tag = {preset.tag: preset for preset in presets}
    if len(by_tag) != len(presets):
        raise PydanticCustomError("shot_error", "La libreria del cut contiene tag di inquadratura duplicati.")
    cues = []
    previous_end = 0
    for match in REQUEST_SHOT.finditer(request):
        tag = match['tag']
        if tag and tag not in by_tag:
            raise PydanticCustomError("shot_error", "Inquadratura #{tag} non disponibile nella libreria del progetto.", {"tag": tag})
        # Un tag subito dopo [Shot N] specifica la regia dello stesso Shot.
        if tag and cues and cues[-1]['tag'] is None and not request[previous_end:match.start()].strip():
            cues[-1].update(tag=tag, preset=by_tag[tag], end=match.end())
            previous_end = match.end()
            continue
        if match['number'] is not None and int(match['number']) != len(cues) + 1:
            raise PydanticCustomError('shot_error', 'Numera gli Shot in ordine da 1, senza salti o duplicati.')
        prefix = TIME_PREFIX.search(request[previous_end:match.start()])
        start = match.start()
        end = match.end()
        suffix = TIME_SUFFIX.match(request, end) if match['number'] is not None else None
        if prefix and suffix:
            raise PydanticCustomError('shot_error', 'Indica un solo tempo per ogni Shot, prima o dopo il marcatore.')
        timing = suffix or prefix
        seconds = 0.0
        if timing:
            value = timing["time"].replace(",", ".")
            if ":" in value:
                minutes, fraction = value.split(":")
                if float(fraction) >= 60:
                    raise PydanticCustomError("shot_error", "Usa tempi nel formato minuti:secondi.millisecondi.")
                seconds = int(minutes) * 60 + float(fraction)
            else:
                seconds = float(value)
            if prefix:
                start = previous_end + prefix.start()
            if suffix:
                end = suffix.end()
        elif cues:
            raise PydanticCustomError("shot_error", "Indica il tempo del cambio d’inquadratura, per esempio «[Shot 2] At 00:03.500,» oppure «A 3,5 secondi passa a #tag».")
        if not cues and seconds != 0:
            raise PydanticCustomError("shot_error", "La prima inquadratura apre il cut. Inizia con [Shot 1] o un tag senza tempo, oppure a zero secondi.")
        if cues and seconds <= cues[-1]["at_s"]:
            raise PydanticCustomError("shot_error", "I tempi dei cambi d’inquadratura devono essere strettamente crescenti.")
        if seconds >= (duration if duration is not None else 15):
            raise PydanticCustomError("shot_error", "Il cambio d’inquadratura deve precedere la fine del cut.")
        cues.append(dict(id=f"s{len(cues)+1}", at_s=seconds, tag=tag,
                         start=start, end=end, preset=by_tag[tag] if tag else None))
        previous_end = end
    return cues


def marked_request(request, cues):
    for cue in reversed(cues):
        request = request[:cue["start"]] + "{{shot:" + cue["id"] + "}}" + request[cue["end"]:]
    return request


def timecode(seconds):
    milliseconds = round(seconds * 1000)
    minutes, remainder = divmod(milliseconds, 60000)
    return f"{minutes:02d}:{remainder // 1000:02d}.{remainder % 1000:03d}"


def shot_instruction(cue, index):
    camera = cue["preset"].camera.context() if cue['preset'] else {}
    framing = camera.get("framing")
    view = ("an " if framing and framing[0].lower() in "aeiou" else "a ") + framing if framing else None
    if index:
        opening = f'[Shot {index+1}] At {timecode(cue["at_s"])}, '
        opening += f"the camera cuts to {view}." if view else "the shot changes."
    else:
        opening = "[Shot 1]"
        if view:
            opening += f" Use {view}."
    instructions = [opening]
    angle = camera.get("angle")
    if angle:
        instructions.append(f'Use {"an" if angle[0].lower() in "aeiou" else "a"} {angle}.')
    if camera.get("movement"):
        motion = " ".join(camera[key] for key in ["movement", "amplitude", "speed"] if key in camera)
        instructions.append(f"The camera {motion}.")
    return " ".join(instructions) + " "


class ShotLibraryOperations:
    def _camera_presets(self, db, project_id):
        return [json.loads(row["data"]) for row in db.execute(
            "SELECT data FROM project_camera_presets WHERE project_id=? ORDER BY rowid", (str(project_id),))]

    def save_camera_preset(self, project_id, tag, command):
        def action(db):
            project = self._entity(db, "projects", project_id, command.expected_revision)
            row = db.execute("SELECT * FROM project_camera_presets WHERE project_id=? AND tag=?",
                             (str(project_id), tag)).fetchone()
            old = json.loads(row["data"]) if row else None
            if command.expected_preset_revision != (old["revision"] if old else 0):
                raise StoreError("camera_preset_changed", "L’inquadratura è cambiata. Riaprila dalla libreria prima di salvarla.", 409)
            try:
                preset = CameraPreset(id=row["id"] if row else str(uuid4()), tag=tag,
                                      name=command.name.strip(), revision=old["revision"] + 1 if old else 1,
                                      camera=command.camera)
            except ValidationError as exc:
                raise StoreError("invalid_input", "Controlla nome, tag e scelte di regia dell’inquadratura.", 422) from exc
            data = preset.model_dump_json()
            if row:
                db.execute("UPDATE project_camera_presets SET data=? WHERE id=?", (data, row["id"]))
            else:
                db.execute("INSERT INTO project_camera_presets VALUES (?,?,?,?)",
                           (preset.id, str(project_id), tag, data))
            db.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (str(project_id),))
            return dict(camera_presets=self._camera_presets(db, project_id), revision=project["revision"] + 1)
        return self._entity_command(f"camera_preset:{tag}", project_id, command, action)

    def _check_camera_presets(self, state, snapshots):
        # Controllo nella transazione del comando, prima dell'avvio del job.
        with closing(self.connect()) as db:
            current = {p["id"]: p for p in self._camera_presets(db, state["project_id"])}
        for preset in snapshots:
            if current.get(preset["id"]) != preset:
                raise StoreError("camera_preset_changed", "Un’inquadratura è cambiata nella libreria. Ricarica il cut e ricompila.", 409)
