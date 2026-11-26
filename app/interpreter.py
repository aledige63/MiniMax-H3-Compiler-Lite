"""Client Ollama locale, una chiamata e nessuna riparazione automatica."""
import hashlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from app.compiler import StructuralError, render
from app.direction import guide_key, guide_opening
from app.shots import marked_request, shot_cues
from app.domain import CompileInput, CompileResult, Metrics
from app.narrative import NarrativePlan, response_schema
from app.voice import voice_phrases, voice_sources, voice_translations
from app.physical import detail_entries
from app.scale import scale_entries

SYSTEM_PROMPT = Path(__file__).with_name("prompts").joinpath("interpreter.txt").read_text(encoding='utf-8')
# No personal model is preselected in a fresh installation. Keep the empty
# string compatible with existing settings/health DTOs; saved choices win.
DEFAULT_TEXT_MODEL = ""
INFERENCE_LOCK = threading.Lock()


def input_hash(data: CompileInput) -> str:
    return hashlib.sha256(data.model_dump_json().encode()).hexdigest()


def model_context(data: CompileInput) -> dict:
    data = data.effective()
    # Non inviare parole del dialogo, schema di archivio, documenti guida o prompt precedenti.
    context = {
        "request": data.request,
        "active_references": [
            {"token": u.token, "name": u.name, "role": u.role,
             "description_en": data.description_for(u),
             "sources": [({"origin": "declared_continuity_context", "attribute": s.attribute} if s.origin == 'context'
                          else {"token": f"<Picture {data.slot_for(s)}>", "attribute": s.attribute})
                         for s in u.sources]}
            for u in data.active_units
        ],
        "dialogues": [{"id": d.id, "placeholder": "{{dialogue:" + d.id + "}}", "speaker": d.speaker_label, "delivery": d.delivery,
                       "language": d.language, "dialogue_char_count": len(d.text)}
                      for d in data.dialogues],
        "continuity": {"mode": data.continuity.mode, "declared_state": data.continuity.declared_state},
        "declared_duration_s": data.declared_duration_s,
    }
    if data.pictures is not None:
        context["pictures"] = [{"token": f"<Picture {p.slot}>", "role": p.role,
                                "description_en": p.description_en} for p in data.active_pictures]
    details = detail_entries(data)
    if details:
        context['physical_details'] = {key: dict(subject=unit.token, operation=detail.operation,
            description=detail.description, body_location=detail.body_location, origin=detail.origin,
            picture=next((f'<Picture {p.slot}>' for p in data.pictures or [] if p.id == detail.picture_id), None))
            for key, (unit, detail) in details.items()}
    scales = scale_entries(data)
    if scales:
        context['scales'] = {key: dict(subject=unit.token, measurements=unit.scale.measurements,
            comparison=unit.scale.comparison,
            reference_subject=f'<Subject {unit.scale.reference_subject}>' if unit.scale.reference_subject else None,
            picture=next((f'<Picture {p.slot}>' for p in data.pictures or [] if p.id == unit.scale.picture_id), None))
            for key, unit in scales.items()}
    if data.custom_soundscape:
        context["soundscape_text"] = data.custom_soundscape
    if data.audio_references:
        context["dialogues"] += [{"id": a.id, "placeholder": "{{dialogue:" + a.id + "}}", "speaker": f"<Subject {a.speaker_subject}>", "language": a.language,
                                  "dialogue_char_count": len(a.transcript), "audio": a.token,
                                  "target_start_s": a.offset_s, "measured_segment_s": a.useful_duration_s}
                                 for a in data.audio_references if a.role == "speech"]
        context["audio_references"] = [{"token": a.token, "role": a.role, "mode": a.mode,
            "description_en": a.description_en, "speaker": f"<Subject {a.speaker_subject}>" if a.speaker_subject else None,
            "source_start_s": a.segment_start_s, "source_end_s": a.end_s, "target_start_s": a.offset_s}
            for a in data.audio_references]
    directions = [dict(source_id=source.id, speaker=getattr(source, 'speaker_label', f'<Subject {source.speaker_subject}>'),
                       fixed_phrases=voice_phrases(source, {}))
                  for source in voice_sources(data).values() if source.voice_tone.strip() or source.voice_emotion or source.voice_mode]
    if directions:
        context['voice_directions'] = directions
    if voice_translations(data):
        context['voice_tones_to_translate'] = voice_translations(data)
    if data.continuity.seamless: context['continuity']['seamless'] = True
    continuation = next((v for v in data.active_videos if v.id == data.continuity.video_id), None)
    if continuation:
        context['continuity']['source_video'] = continuation.token
    if data.active_videos:
        context['videos'] = [{'token': v.token, 'role': v.role, 'description_en': v.description_en,
                             'duration_s': v.duration_s} for v in data.active_videos]
    if data.camera and data.camera.active:
        context['camera_direction'] = dict(data.camera.context(), id='main', placeholder='{{camera:main}}')
    guides=[]
    for kind, refs in [('picture',data.active_picture_guides),('video',data.active_video_guides)]:
        for ref in refs:
            g=ref.guidance
            guides.append(dict(id=guide_key(ref,kind), placeholder='{{guide:'+guide_key(ref,kind)+'}}', token=f'<{kind.title()} {ref.slot}>', role=ref.role,
                mappings=[m.model_dump(exclude_none=True) for m in g.mappings], anchor=g.anchor, at_s=g.at_s,
                verbatim_prompt_en=g.prompt_en))
            if kind == 'video' and ref.role in {'subject_motion', 'camera_and_subject_motion'}:
                guides[-1]['subject_bindings'] = [dict(subject=f'<Subject {m.subject}>', proxy=m.figure.strip(),
                    appearance='declared Subject references', motion='this guide',
                    replacement='in place from the proxy first appearance') for m in g.mappings]
                opening = guide_opening(ref)
                if opening:
                    guides[-1]['opening_en'] = opening
                    guides[-1]['opening_authority'] = 'guide only; do not add another opening for the mapped Subjects'
    if guides: context['direction_guides']=guides
    cues = shot_cues(data.request, data.shot_presets, data.declared_duration_s)
    if cues:
        context["request"] = marked_request(data.request, cues)
        context["shot_sequence"] = [
            dict(id=cue["id"], placeholder="{{shot:" + cue["id"] + "}}",
                 at_s=cue["at_s"], has_camera_preset=cue["preset"] is not None,
                 camera_notes=cue["preset"].camera.notes if cue["preset"] else "") for cue in cues]
    return context


class OllamaError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaClient:
    def __init__(self, base_url="http://127.0.0.1:11434", timeout_s=120, keep_alive="5m", *, remote=False):
        parsed = urlparse(base_url)
        if not remote and (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("M0 usa esclusivamente Ollama locale.")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.keep_alive = keep_alive

    def _request(self, path, payload=None):
        req = urllib.request.Request(self.base_url + path,
                                     data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            # Nessun proxy, cloud fallback o retry.
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=self.timeout_s) as r:
                result = json.load(r)
                if not isinstance(result, dict):
                    raise OllamaError("invalid_response")
                return result
        except urllib.error.HTTPError as exc:
            # Il corpo diagnostico non viene registrato: potrebbe contenere input.
            body = exc.read().decode(errors="replace").lower()
            code = "context_exhausted" if "context" in body and any(w in body for w in ("exceed", "large", "length")) else "http_error"
            raise OllamaError(code) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise OllamaError("timeout") from exc
        except urllib.error.URLError as exc:
            raise OllamaError("timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "service_unreachable") from exc
        except (ValueError, UnicodeError) as exc:
            raise OllamaError("invalid_response") from exc

    def models(self):
        models = self._request("/api/tags").get("models")
        if not isinstance(models, list) or any(not isinstance(m, dict) or
                not isinstance(m.get("name"), str) or not isinstance(m.get("digest"), str) for m in models):
            raise OllamaError("invalid_response")
        return models

    def compile(self, data: CompileInput, model: str = DEFAULT_TEXT_MODEL) -> CompileResult:
        fingerprint = input_hash(data)
        data = data.effective()
        context = json.dumps(model_context(data), ensure_ascii=False, separators=(",", ":"))
        metrics = dict(model=model, digest="", inference_calls=0, input_hash=fingerprint,
                       input_chars=len(SYSTEM_PROMPT) + len(context), queue_s=0.0, wall_s=0.0)
        start = time.perf_counter()
        try:
            installed = next((m for m in self.models() if m["name"] == model), None)
            if installed is None:
                raise OllamaError("model_unavailable")
            metrics["digest"] = installed["digest"]
            waiting = time.perf_counter()
            with INFERENCE_LOCK:
                metrics["queue_s"] = time.perf_counter() - waiting
                metrics["inference_calls"] = 1
                response = self._request("/api/chat", {
                    "model": model, "stream": False, "think": False,
                    "keep_alive": self.keep_alive,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                 {"role": "user", "content": context}],
                    "format": response_schema(data),
                    "options": {"num_ctx": 8192, "num_predict": 1200, "temperature": 0},
                })
            for field, source in (("load_s", "load_duration"), ("prompt_eval_s", "prompt_eval_duration"),
                                  ("eval_s", "eval_duration"), ("total_s", "total_duration")):
                metrics[field] = response[source] / 1e9 if source in response else None
            metrics.update(prompt_tokens=response.get("prompt_eval_count"),
                           output_tokens=response.get("eval_count"), done_reason=response.get("done_reason"))
            if response.get("done_reason") == "length" or response.get("done") is not True:
                raise OllamaError("truncated_response")
            message = response.get("message")
            if not isinstance(message, dict):
                raise OllamaError("invalid_response")
            raw = message.get("content", "")
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise OllamaError("unreadable_json") from exc
            try:
                structured = NarrativePlan.model_validate(parsed)
            except ValidationError as exc:
                raise OllamaError("missing_essential_data") from exc
            try:
                plan = structured.interpretation()
                result = render(data, plan, fingerprint)
            except StructuralError as exc:
                # Diagnostica del renderer, mai la prosa grezza del modello.
                raise OllamaError("invalid_structure",str(exc)) from exc
        except OllamaError as exc:
            metrics["error_code"] = exc.code
            result = CompileResult(status="error", input_hash=fingerprint, error_code=exc.code,
                                   issues=[exc.detail or PUBLIC_ERRORS.get(exc.code, "Risposta del modello non utilizzabile.")])
        metrics["wall_s"] = time.perf_counter() - start
        return result.model_copy(update={"metrics": Metrics(**metrics)})


PUBLIC_ERRORS = {
    "service_unreachable": "Il servizio selezionato non è raggiungibile.",
    "http_error": "Il servizio selezionato ha restituito un errore HTTP.",
    "service_unconfigured": "Configura il servizio selezionato in Impostazioni utente.",
    "invalid_credentials": "La chiave API non è valida o non ha i permessi richiesti.",
    "rate_limited": "Limite o credito API esaurito. Verifica il servizio e riprova esplicitamente.",
    "model_refusal": "Il modello ha rifiutato la richiesta. Nessuna proposta generata.",
    "capability_unavailable": "Il modello non supporta la funzione richiesta.",
    "timeout": "Tempo di attesa del modello esaurito.",
    "model_unavailable": "Modello non installato: sceglierne uno disponibile.",
    "context_exhausted": "Il contesto disponibile è insufficiente.",
    "truncated_response": "La risposta del modello è stata interrotta.",
    "unreadable_json": "Il modello ha restituito un JSON illeggibile.",
    "missing_essential_data": "Nella risposta mancano dati essenziali o il contratto non è rispettato.",
    "invalid_structure": "Controlli strutturali non superati: rivedere o ricompilare.",
    "invalid_response": "La risposta del servizio non è leggibile.",
}
