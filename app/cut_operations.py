"""Operazioni del cut condivise tra archivio corrente e lettore storico M1."""
import copy
import math
import re
from uuid import uuid4

from pydantic import ValidationError

from app.compiler import SECTIONS
from app.contracts import JobView, PromptVersion
from app.domain import CompileInput, Continuity
from app.interpreter import DEFAULT_TEXT_MODEL, input_hash
from app.validation import validation_messages
from app.store import StoreError, digest, dto
from app.physical import unit_picture_ids


class CutOperations:
    def _legacy_source_key(self, unit, index, source):
        # Due righe legacy distinte restano due immagini anche se dichiaravano
        # lo stesso slot: non esisteva un ID che ne provasse la condivisione.
        return digest({"subject": unit.get("subject"), "index": index, "source": source})


    def _upgrade_legacy_draft(self, data, state):
        upgraded = copy.deepcopy(data)
        if upgraded.get("pictures") is not None and not isinstance(upgraded["pictures"], list):
            return upgraded
        upgraded.setdefault("pictures", [])
        if upgraded["pictures"] is None:
            upgraded["pictures"] = []
        for unit in upgraded.get("active_units", []):
            if not isinstance(unit, dict) or not isinstance(unit.get("sources"), list):
                continue
            for index, source in enumerate(unit["sources"]):
                if not isinstance(source, dict) or source.get("picture_slot") is None:
                    continue
                key = self._legacy_source_key(unit, index, source)
                picture_id = state["legacy_picture_ids"].setdefault(key, str(uuid4()))
                if picture_id not in state["picture_ids"]:
                    state["picture_ids"].append(picture_id)
                attribute = source.get("attribute", "identity")
                # La vecchia descrizione era del Subject: non inventarne una per
                # una sorgente separata d'abito/scarpe che non aveva testo proprio.
                carries_description = attribute in {"identity", "appearance", "environment", "object"}
                description = unit.get("description_en", "") if carries_description else ""
                upgraded["pictures"].append({"id": picture_id, "slot": source["picture_slot"],
                    "name": f"{unit.get('name') or 'Immagine'} · {attribute}", "role": attribute,
                    "description_en": description, "confirmed": bool(unit.get("confirmed")) and bool(description),
                    "linked_to_h3": bool(source.get("linked_to_h3"))})
                unit["sources"][index] = {"picture_id": picture_id, "attribute": attribute}
        return upgraded


    def _job_view(self, state, job):
        fields = {k: v for k, v in job.items() if k != "input"}
        fields["stale"] = job["input_revision"] != state["revision"]
        return dto(JobView, fields)


    def _catalogue_issues(self, data):
        if not data.get("request") and not any(data.get(key) for key in ("active_units", "dialogues", "audio_references", "videos")):
            return []
        try:
            CompileInput.model_validate(data)
        except ValidationError as exc:
            return validation_messages(exc, data)
        return []


    def _check_cut(self, state, cut_id):
        if str(cut_id) != state["id"]:
            raise StoreError("not_found", "Cut non trovato.", 404)


    def _registered(self, state, data):
        if not isinstance(data.get("pictures"), list):
            raise StoreError("invalid_input", "Interfaccia aggiornata: copia eventuali campi locali e ricarica la pagina prima di salvare il catalogo Picture.", 422)
        units, dialogues = data.get("active_units", []), data.get("dialogues", [])
        if not isinstance(units, list) or not isinstance(dialogues, list):
            raise StoreError("invalid_input", "Riferimenti e dialoghi devono essere elenchi.", 422)
        subjects = [u.get("subject") if isinstance(u, dict) else None for u in units]
        ids = [d.get("id") if isinstance(d, dict) else None for d in dialogues]
        if (any(type(n) is not int or n not in state["subject_numbers"] for n in subjects)
                or any(not isinstance(n, str) or not re.fullmatch(r"d[1-9][0-9]*", n)
                       or not 1 <= int(n[1:]) < state["next_dialogue"] for n in ids)):
            raise StoreError("invalid_input", "Usare gli identificatori assegnati dal server.", 422)
        pictures = data.get("pictures", [])
        if pictures is None:
            pictures = []
        if not isinstance(pictures, list) or any(not isinstance(p, dict) or not isinstance(p.get("id"), str)
                or p["id"] not in state["picture_ids"] for p in pictures):
            raise StoreError("invalid_input", "Usare le immagini aggiunte al catalogo Picture dal server.", 422)
        for unit in units:
            for picture_id in unit_picture_ids(unit):
                if picture_id not in state['picture_ids']:
                    raise StoreError("invalid_input", f"Subject {unit['subject']} richiama un'immagine mai registrata: aggiungila al catalogo Picture.", 422)
            sources = unit.get("sources")
            for source in sources if isinstance(sources, list) else []:
                if not isinstance(source, dict):
                    continue  # La bozza incompleta resta salvabile.
                picture_id = source.get("picture_id")
                if picture_id is not None and picture_id not in state["picture_ids"]:
                    raise StoreError("invalid_input", f"Subject {unit['subject']} richiama un'immagine mai registrata: aggiungila al catalogo Picture.", 422)
                if source.get("picture_slot") is not None:
                    raise StoreError("invalid_input", f"Subject {unit['subject']}: scegli la sorgente dal catalogo Picture, senza assegnarle uno slot separato.", 422)


    def _receipt_hashes(self, operation, cut_id, command):
        value = {"operation": operation, "cut_id": str(cut_id), "command": command.model_dump(mode="json")}
        candidates = [value]
        if operation == 'compile':
            previous=copy.deepcopy(value);data=previous['command']['input']
            if data.get('camera') is None and all(ref.get('guidance') is None for ref in [*(data.get('pictures') or []),*data.get('videos',[]) ]):
                data.pop('camera',None)
                for ref in [*(data.get('pictures') or []),*data.get('videos',[])]:ref.pop('guidance',None)
                candidates.append(previous)
            for candidate in list(candidates):
                compatible = copy.deepcopy(candidate); data = compatible['command']['input']
                if data.get('ambient_sound', True) and all(u.get('definition_mode', 'picture') == 'picture' for u in data.get('active_units', [])):
                    data.pop('ambient_sound', None)
                    for unit in data.get('active_units', []): unit.pop('definition_mode', None)
                    candidates.append(compatible)
        if operation == 'compile':
            for value in list(candidates):
                previous = copy.deepcopy(value); data = previous['command']['input']
                compatible = not data.get('videos')
                for field, default in Continuity().model_dump(mode='json').items():
                    if field in {'mode', 'declared_state'}: continue
                    if data['continuity'].get(field, default) != default: compatible = False
                    data['continuity'].pop(field, None)
                for unit in data.get('active_units', []):
                    for source in unit.get('sources', []):
                        if source.get('origin', 'picture') != 'picture': compatible = False
                        source.pop('origin', None)
                data.pop('videos', None)
                if compatible: candidates.append(previous)
        if operation == 'compile':
            for candidate in list(candidates):
                if candidate['command']['input'].get('audio_references'): continue
                previous = copy.deepcopy(candidate); data = previous['command']['input']
                data.pop('audio_references', None)
                defaults = {'description_language': 'English', 'use_original_language': False,
                            'original_description': None, 'original_language': None}
                compatible = True
                for picture in data.get('pictures') or []:
                    for field, default in defaults.items():
                        if picture.get(field, default) != default: compatible = False
                        picture.pop(field, None)
                if compatible: candidates.append(previous)
            for candidate in list(candidates):
                if candidate['command']['input'].get('pictures') is not None: continue
                previous = copy.deepcopy(candidate); previous['command']['input'].pop('pictures', None)
                for unit in previous['command']['input'].get('active_units', []):
                    for source in unit.get('sources', []): source.pop('picture_id', None)
                candidates.append(previous)
        return {digest(candidate) for candidate in candidates}


    def save_draft(self, cut_id, command):
        def action(state):
            self._registered(state, command.input)
            state["draft_input"] = copy.deepcopy(command.input)
            state["draft_input"]["pictures"] = state["draft_input"].get("pictures") or []
            state["state"] = "draft"
        return self._command("draft", cut_id, command, action)[0]


    def _available_subject(self, state):
        # I numeri provvisori eliminati non consumano il registro. Quelli ancora
        # usati da testo, speaker, versioni o job mantengono invece il significato.
        reserved = set()

        def reserve_text(text):
            if isinstance(text, str):
                reserved.update(int(n) for n in re.findall(r"<Subject ([1-9][0-9]*)>", text))

        def reserve_input(data):
            for unit in data.get("active_units", []):
                reserved.add(unit["subject"])
            for dialogue in data.get("dialogues", []):
                speaker = dialogue.get("speaker_subject")
                if type(speaker) is int and speaker > 0:
                    reserved.add(speaker)
            reserve_text(data.get("request"))
            reserve_text(data.get("soundscape_text"))
            continuity = data.get("continuity")
            if isinstance(continuity, dict):
                reserve_text(continuity.get("declared_state"))

        reserve_input(state["draft_input"])
        for job in state["jobs"].values():
            reserve_input(job["input"])
        for version in state["versions"]:
            reserve_text(version["text"])
            if isinstance(version.get("input_snapshot"), dict):
                reserve_input(version["input_snapshot"])
        number = 1
        while number in reserved:
            number += 1
        return number


    @staticmethod
    def _available_dialogue(state):
        used = {dialogue['id'] for dialogue in state['draft_input'].get('dialogues', [])}
        number = 1
        while f'd{number}' in used:
            number += 1
        state['next_dialogue'] = max(state['next_dialogue'], number + 1)
        return f'd{number}'

    def add_item(self, cut_id, command):
        def action(state):
            data = state["draft_input"]
            if command.kind == "unit":
                n = self._available_subject(state)
                state["next_subject"] = max(state["next_subject"], n + 1)
                if n not in state["subject_numbers"]:
                    state["subject_numbers"].append(n)
                data.setdefault("active_units", []).append({"subject": n, "name": "", "role": "character",
                    "description_en": "", "confirmed": False, "sources": []})
            elif command.kind == "picture":
                pictures = data.setdefault("pictures", [])
                if len(pictures) >= 9:
                    raise StoreError("invalid_input", "Il catalogo può contenere al massimo 9 immagini Picture.", 422)
                used = {p.get("slot") for p in pictures if type(p.get("slot")) is int}
                slot = next(n for n in range(1, 10) if n not in used)
                picture_id = str(uuid4())
                state["picture_ids"].append(picture_id)
                pictures.append({"id": picture_id, "slot": slot, "name": "", "role": "identity",
                    "description_en": "", "confirmed": False, "linked_to_h3": False})
            else:
                dialogue_id = self._available_dialogue(state)
                speaker = next((u["subject"] for u in data.get("active_units", [])
                                if u.get("role") == "character"), 0)
                data.setdefault("dialogues", []).append({"id": dialogue_id, "text": "", "language": "Italian",
                    "speaker_subject": speaker, "origin": "native", "confirmed": False})
            state["state"] = "draft"
        return self._command("item", cut_id, command, action)[0]


    def add_source(self, cut_id, command):
        def action(state):
            unit = next((u for u in state["draft_input"].get("active_units", [])
                         if u.get("subject") == command.subject), None)
            if unit is None:
                raise StoreError("not_found", "Subject non trovato nella bozza corrente.", 404)
            if not isinstance(unit.get("sources"), list):
                raise StoreError("invalid_input", f"Subject {command.subject}: correggi l'elenco delle associazioni prima di aggiungerne una.", 422)
            if unit.get("role") == "character":
                has_identity = any(isinstance(s, dict) and s.get("attribute") == "identity" for s in unit["sources"])
                attribute = "outfit" if has_identity else "identity"
            else:
                attribute = "environment" if unit.get("role") == "environment" else "object"
            unit["sources"].append({"picture_id": None, "attribute": attribute})
            unit["confirmed"] = False
            state["state"] = "draft"
        return self._command("source", cut_id, command, action)[0]


    def compile(self, cut_id, command, *, default_model=None):
        if command.cut_id != cut_id:
            raise StoreError("invalid_input", "Il cut del comando non coincide con il percorso.", 422)
        def action(state):
            raw = command.input.model_dump(mode="json")
            self._registered(state, raw)
            if raw.get("shot_presets"):
                self._check_camera_presets(state, raw["shot_presets"])
            model = command.model or default_model or DEFAULT_TEXT_MODEL
            if not model:
                raise StoreError('text_model_required', 'Scegli un modello testo in Impostazioni utente prima di compilare.', 422)
            raw["pictures"] = raw.get("pictures") or []
            state["draft_input"] = raw
            state["state"] = "queued"
            job_id = str(uuid4())
            state["jobs"][job_id] = {"id": job_id, "cut_id": state["id"], "status": "queued",
                "input_revision": state["revision"], "input_hash": input_hash(command.input),
                "model": model, "result": None,
                "candidate_id": None, "stale": False, "input": raw}
            state["latest_job_id"] = job_id
            return job_id
        return self._command("compile", cut_id, command, action)


    def save_manual(self, cut_id, command):
        def action(state):
            base = next((v for v in state["versions"] if v["id"] == str(command.base_candidate_id)), None)
            if command.base_candidate_id and not base:
                raise StoreError("not_found", "Versione di origine non trovata.", 404)
            data = state["draft_input"]
            duration = base["duration_s"] if base else data.get("declared_duration_s")
            origin = base["duration_origin"] if base else ("declared" if duration is not None else None)
            issues = []
            try:
                valid = CompileInput.model_validate(data)
            except ValidationError as exc:
                valid = None
                issues.extend(validation_messages(exc, data))
            headings = re.findall(r"(?m)^([a-z_]+):\s*$", command.text)
            if headings != list(SECTIONS):
                issues.append("Il testo deve contenere le sei sezioni nell'ordine previsto.")
            known = {f"<Subject {u['subject']}>" for u in data.get("active_units", [])}
            known |= {f"<Picture {p.get('slot')}>" for p in data.get("pictures", []) if isinstance(p, dict)}
            known |= {f"<Audio {a.get('slot')}>" for a in data.get('audio_references', []) if isinstance(a, dict)}
            known |= {f"<Video {v.get('slot')}>" for v in data.get('videos', []) if isinstance(v, dict) and (v.get('id') == (data.get('continuity') or {}).get('video_id') or (v.get('guidance') or {}).get('enabled'))}
            tokens = re.findall(r"<(?:Subject|Picture|Video|Audio)[^>]*>", command.text)
            starts = re.findall(r"<(?:Subject|Picture|Video|Audio)", command.text)
            if set(tokens) - known or len(tokens) != len(starts):
                issues.append("Il testo richiama riferimenti non disponibili nella bozza.")
            finite_duration = isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration)
            if not finite_duration or not 4 <= duration <= 15:
                issues.append("Specificare una durata utile fra 4 e 15 secondi.")
            if base and not base["structural_checks_passed"]:
                issues.append("La proposta di origine contiene controlli da rivedere.")
            version = PromptVersion(id=uuid4(), origin="manual", text=command.text,
                input_hash=input_hash(valid) if valid else digest(data), input_revision=state["revision"] - 1,
                duration_s=duration if finite_duration else None,
                duration_origin=origin, structural_checks_passed=not issues, issues=issues,
                input_snapshot=copy.deepcopy(data), base_candidate_id=command.base_candidate_id).model_dump(mode="json")
            state["versions"].append(version)
            state["manual_version_id"] = version["id"]
            state["state"] = "proposal" if not issues else "draft"
        return self._command("manual", cut_id, command, action)[0]


