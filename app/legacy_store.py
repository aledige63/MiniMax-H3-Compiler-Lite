"""Lettore storico M1, usato soltanto per migrazioni e prove di compatibilità."""
import copy
import json
import os
import threading
from pathlib import Path
from uuid import uuid4

from app.cut_operations import CutOperations
from app.store import StoreError, digest, dto
from app.contracts import CutView, PromptVersion
from app.domain import CompileInput, CompileResult

class LegacyRepository(CutOperations):
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "workspace.json"
        self.lock = threading.RLock()
        if self.path.exists():
            self._state = json.loads(self.path.read_text(encoding='utf-8'))
            if self._state.get("picture_registry_version") != 1:
                self._migrate_picture_registry()
        else:
            self._state = {"id": str(uuid4()), "revision": 0, "draft_input": {
                "profile": "H3-Base-Ref2VA", "request": "", "active_units": [], "pictures": [], "dialogues": [],
                "continuity": {"mode": "none", "declared_state": None}, "declared_duration_s": None},
                "state": "draft", "next_subject": 1, "next_dialogue": 1,
                "picture_registry_version": 1, "picture_ids": [], "subject_numbers": [], "legacy_picture_ids": {},
                "jobs": {}, "latest_job_id": None, "versions": [],
                "latest_candidate_id": None, "manual_version_id": None, "commands": {}}
            self._persist(self._state)
        # Nessun lavoro riparte in silenzio dopo un riavvio.
        changed = False
        for job in self._state["jobs"].values():
            if job["status"] in {"queued", "running"}:
                job["status"] = "failed"
                job["result"] = CompileResult(status="error", input_hash=job["input_hash"],
                    error_code="interrupted", issues=["Compilazione interrotta dal riavvio: ricompilare esplicitamente."]).model_dump(mode="json")
                if job["input_revision"] == self._state["revision"]:
                    self._state["state"] = "error"
                changed = True
        if changed:
            self._persist(self._state)

    def _migrate_picture_registry(self):
        # Una copia byte-per-byte precede ogni cambiamento alla bozza nuova M1.
        # Non vengono letti dati o cartelle del vecchio prototipo.
        previous = self.path.read_bytes()
        backup = self.path.with_name("workspace.before-picture-registry.json")
        counter = 1
        while backup.exists():
            backup = self.path.with_name(f"workspace.before-picture-registry-{counter}.json")
            counter += 1
        with backup.open("xb") as handle:
            os.chmod(backup, 0o600)
            handle.write(previous)
            handle.flush()
            os.fsync(handle.fileno())
        state = copy.deepcopy(self._state)
        state["picture_registry_version"] = 1
        state["picture_ids"] = []
        state["legacy_picture_ids"] = {}
        state["subject_numbers"] = []

        def register_input(data):
            if not isinstance(data, dict):
                return
            for unit in data.get("active_units", []):
                n = unit.get("subject") if isinstance(unit, dict) else None
                if type(n) is int and n > 0 and n not in state["subject_numbers"]:
                    state["subject_numbers"].append(n)
            upgraded = self._upgrade_legacy_draft(data, state)
            for picture in upgraded.get("pictures", []):
                if isinstance(picture, dict) and isinstance(picture.get("id"), str) and picture["id"] not in state["picture_ids"]:
                    state["picture_ids"].append(picture["id"])

        register_input(state["draft_input"])
        # Pre-registra gli ID per le risposte storiche, senza cambiarle sul disco.
        # Un retry potrà così restituire una bozza nuova con ID server validi.
        for receipt in state["commands"].values():
            response = receipt.get("response")
            if isinstance(response, dict) and isinstance(response.get("draft_input"), dict):
                register_input(response["draft_input"])
        for job in state["jobs"].values():
            register_input(job["input"])
        state["draft_input"] = self._upgrade_legacy_draft(state["draft_input"], state)
        self._persist(state)
        self._state = state

    def _persist(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump(state, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _view(self, state):
        job = state["jobs"].get(state["latest_job_id"])
        return dto(CutView, {k: state[k] for k in ("id", "revision", "draft_input", "state",
            "latest_candidate_id", "manual_version_id", "versions")} | {
            "latest_job": self._job_view(state, job).model_dump(mode="json") if job else None,
            "catalogue_issues": self._catalogue_issues(state["draft_input"])})

    def workspace(self):
        with self.lock:
            return self._view(self._state)

    def job(self, job_id):
        with self.lock:
            job = self._state["jobs"].get(str(job_id))
            if not job:
                raise StoreError("not_found", "Lavoro non trovato.", 404)
            return self._job_view(self._state, job)

    def text(self, cut_id, version_id):
        with self.lock:
            self._check_cut(self._state, cut_id)
            for version in self._state["versions"]:
                if version["id"] == str(version_id):
                    return version["text"]
            raise StoreError("not_found", "Versione non trovata.", 404)

    def _command(self, operation, cut_id, command, action):
        with self.lock:
            self._check_cut(self._state, cut_id)
            payload_hash = digest({"operation": operation, "cut_id": str(cut_id),
                                   "command": command.model_dump(mode="json")})
            accepted_hashes = self._receipt_hashes(operation, cut_id, command)
            receipt = self._state["commands"].get(str(command.command_id))
            if receipt:
                if receipt["payload_hash"] not in accepted_hashes:
                    raise StoreError("command_conflict", "Questo comando è già stato usato con dati diversi.")
                if receipt["job_id"]:
                    return self._job_view(self._state, self._state["jobs"][receipt["job_id"]]), False
                response = copy.deepcopy(receipt["response"])
                response["draft_input"] = self._upgrade_legacy_draft(response["draft_input"], self._state)
                response["catalogue_issues"] = self._catalogue_issues(response["draft_input"])
                return dto(CutView, response), False
            if command.expected_revision != self._state["revision"]:
                raise StoreError("revision_conflict", "La bozza è cambiata: recuperare la versione server senza perdere il testo locale.",
                                 current_revision=self._state["revision"])
            state = copy.deepcopy(self._state)
            state["revision"] += 1
            job_id = action(state)
            response = self._job_view(state, state["jobs"][job_id]) if job_id else self._view(state)
            state["commands"][str(command.command_id)] = {"payload_hash": payload_hash,
                "job_id": job_id, "response": response.model_dump(mode="json")}
            self._persist(state)
            self._state = state
            return response, True

    def start_job(self, job_id):
        with self.lock:
            state = copy.deepcopy(self._state)
            job = state["jobs"][str(job_id)]
            if job["status"] != "queued":
                return None
            job["status"] = "running"
            if job["input_revision"] == state["revision"]:
                state["state"] = "compiling"
            self._persist(state)
            self._state = state
            return CompileInput.model_validate(job["input"]), job["model"]

    def finish_job(self, job_id, result):
        with self.lock:
            state = copy.deepcopy(self._state)
            job = state["jobs"][str(job_id)]
            job["result"] = result.model_dump(mode="json")
            job["status"] = "failed" if result.status == "error" else "succeeded"
            current = job["input_revision"] == state["revision"]
            if result.status == "proposal":
                version = PromptVersion(id=uuid4(), origin="generated", text=result.prompt,
                    input_hash=job["input_hash"], input_revision=job["input_revision"], duration_s=result.duration_s,
                    duration_origin=result.duration_origin, structural_checks_passed=result.structural_checks_passed,
                    issues=result.issues, input_snapshot=copy.deepcopy(job["input"])).model_dump(mode="json")
                state["versions"].append(version)
                job["candidate_id"] = version["id"]
                if current:
                    state["latest_candidate_id"] = version["id"]
            if current:
                state["state"] = result.status
            self._persist(state)
            self._state = state
