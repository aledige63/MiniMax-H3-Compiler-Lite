import json
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import create_app
from app.compiler import render
from app.domain import CompileInput, CompileResult, CurrentInterpretation, Interpretation
from app.interpreter import input_hash

CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("m0_cases.json").read_text())


class FakeOllama:
    def __init__(self):
        self.calls = 0
        self.mode = "proposal"
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()

    def models(self):
        return [{"name": "local-test", "digest": "test-digest"}]

    def compile(self, data, model):
        self.calls += 1
        self.last_input = data
        self.entered.set()
        self.release.wait(timeout=3)
        if self.mode == "error":
            return CompileResult(status="error", input_hash=input_hash(data), error_code="timeout", issues=["Tempo esaurito."])
        if self.mode == "question":
            return render(data, Interpretation(narrative_en=None, estimated_duration_s=None, question="Chi entra per primo?"), input_hash(data))
        return render(data, getattr(self, "plan", Interpretation.model_validate(CASES[0]["expected_plan"])), input_hash(data))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fake = FakeOllama()
        self.app = create_app(data_dir=Path(self.temp.name), client=self.fake)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8767")
        self.client.__enter__()
        self.workspace = self.client.get("/api/workspace").json()
        self.cut = self.workspace["id"]

    def tearDown(self):
        self.fake.release.set()
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def command(self, **extra):
        current = self.client.get("/api/workspace").json()
        if isinstance(extra.get("input"), dict):
            extra["input"] = {"pictures": [], **extra["input"]}
        return {"command_id": str(uuid4()), "expected_revision": current["revision"], **extra}

    def prepare(self):
        for kind in ["picture"] * 4 + ["unit", "unit", "unit", "dialogue"]:
            response = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind=kind))
            self.assertEqual(response.status_code, 200, response.text)
        self.input = json.loads(json.dumps(CASES[0]["input"]))
        self.input["pictures"] = response.json()["draft_input"]["pictures"]
        descriptions = ["Anna", "a skirt", "Marco", "the room"]
        roles = ["identity", "outfit", "identity", "environment"]
        for picture, description, role in zip(self.input["pictures"], descriptions, roles):
            picture.update(name=description, description_en=description, role=role, confirmed=True, linked_to_h3=True)
        by_slot = {picture["slot"]: picture["id"] for picture in self.input["pictures"]}
        for unit in self.input["active_units"]:
            unit["sources"] = [{"picture_id": by_slot[source["picture_slot"]], "attribute": source["attribute"]}
                               for source in unit["sources"]]
        response = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=self.input))
        self.assertEqual(response.status_code, 200, response.text)

    def compile(self):
        command = self.command(cut_id=self.cut, input=self.input, model="local-test")
        response = self.client.post(f"/api/cuts/{self.cut}/compile", json=command)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json(), command

    def completed(self, job):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = self.client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] in {"succeeded", "failed"}:
                return current
            time.sleep(.01)
        self.fail("Job non terminato")

    def test_minimum_flow_and_exact_copy_without_inference(self):
        self.prepare()
        summary = '<Subject 1> speaks from the sofa as <Subject 2> enters and stops beside her.'
        self.fake.plan = CurrentInterpretation(**CASES[0]['expected_plan'], summary_en=summary)
        job, _ = self.compile()
        finished = self.completed(job)
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished['result']['interpretation']['summary_en'], summary)
        candidate = finished["candidate_id"]
        text = self.client.get(f"/api/cuts/{self.cut}/text", params={"version_id": candidate}).text
        self.assertIn("<d>[Italian] Sono pronta.</d>.", text)
        self.assertIn('summary:\n[reference generation] ' + summary, text)
        manual = "  " + text + "\n\n"
        saved = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=manual, base_candidate_id=candidate))
        self.assertEqual(saved.status_code, 200, saved.text)
        version = saved.json()["manual_version_id"]
        copied = self.client.get(f"/api/cuts/{self.cut}/text", params={"version_id": version})
        self.assertEqual(copied.text, manual)
        self.assertEqual(self.fake.calls, 1)
        self.assertFalse(saved.json()["versions"][-1]["user_approved"])

    def test_http_retry_idempotent_and_explicit_recompile_new_call(self):
        self.prepare()
        job, command = self.compile()
        self.completed(job)
        retry = self.client.post(f"/api/cuts/{self.cut}/compile", json=command)
        self.assertEqual(retry.json()["id"], job["id"])
        self.assertEqual(self.fake.calls, 1)
        next_job, _ = self.compile()
        self.completed(next_job)
        self.assertNotEqual(next_job["id"], job["id"])
        self.assertEqual(self.fake.calls, 2)
        command["model"] = "other"
        self.assertEqual(self.client.post(f"/api/cuts/{self.cut}/compile", json=command).status_code, 409)

    def test_generated_version_keeps_input_snapshot_after_catalogue_edits(self):
        self.prepare()
        job, _ = self.compile()
        finished = self.completed(job)
        workspace = self.client.get("/api/workspace").json()
        generated = next(v for v in workspace["versions"] if v["id"] == finished["candidate_id"])
        self.assertEqual(CompileInput.model_validate(generated["input_snapshot"]), self.fake.last_input)
        self.assertEqual(input_hash(CompileInput.model_validate(generated["input_snapshot"])), generated["input_hash"])
        edited = json.loads(json.dumps(self.input))
        edited["pictures"][0].update(slot=9, description_en="a corrected description")
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=edited))
        updated = self.client.get("/api/workspace").json()
        stored = next(v for v in updated["versions"] if v["id"] == generated["id"])
        self.assertEqual(stored, generated)
        with TestClient(create_app(Path(self.temp.name), self.fake), base_url="http://127.0.0.1:8767") as reopened:
            saved = reopened.get("/api/workspace").json()
            self.assertEqual(next(v for v in saved["versions"] if v["id"] == generated["id"]), generated)
        self.assertEqual(self.fake.calls, 1)

    def test_manual_version_records_current_snapshot_and_explicit_origin(self):
        self.prepare()
        job, _ = self.compile()
        finished = self.completed(job)
        before = self.client.get("/api/workspace").json()
        generated = next(v for v in before["versions"] if v["id"] == finished["candidate_id"])
        edited = json.loads(json.dumps(self.input))
        edited["pictures"][0]["description_en"] = "description revised by the user"
        draft = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=edited)).json()
        exact = "  Testo manuale da conservare.\n"
        response = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact, base_candidate_id=generated["id"]))
        self.assertEqual(response.status_code, 200, response.text)
        manual = response.json()["versions"][-1]
        self.assertEqual(manual["text"], exact)
        self.assertEqual(manual["input_snapshot"], draft["draft_input"])
        self.assertEqual(manual["base_candidate_id"], generated["id"])
        self.assertEqual(response.json()["versions"][0]["input_snapshot"], generated["input_snapshot"])
        self.assertEqual(self.fake.calls, 1)

    def test_invalid_manual_draft_snapshot_is_preserved_without_reinterpretation(self):
        raw = {"request": "", "pictures": [], "active_units": [], "dialogues": []}
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw)).json()
        exact = "\nUna bozza manuale  non normalizzata.\n"
        response = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact))
        self.assertEqual(response.status_code, 200)
        version = response.json()["versions"][-1]
        self.assertEqual(version["input_snapshot"], saved["draft_input"])
        self.assertIsNone(version["base_candidate_id"])
        self.assertFalse(version["structural_checks_passed"])
        copied = self.client.get(f"/api/cuts/{self.cut}/text", params={"version_id": version["id"]})
        self.assertEqual(copied.text, exact)
        self.assertEqual(self.fake.calls, 0)

    def test_manual_snapshot_keeps_subject_numbers_without_parsing_manual_text(self):
        self.prepare()
        exact = "Bozza manuale senza token da reinterpretare.\n"
        response = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact))
        self.assertEqual(response.status_code, 200)
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(
            input={"request": "", "pictures": [], "active_units": [], "dialogues": []}))
        new = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        self.assertEqual(new["draft_input"]["active_units"][0]["subject"], 1)
        self.assertEqual(new["versions"][0]["text"], exact)
        self.assertEqual(self.fake.calls, 0)

    def test_late_result_preserves_manual_and_newer_draft(self):
        self.prepare()
        self.fake.release.clear()
        job, _ = self.compile()
        self.assertTrue(self.fake.entered.wait(timeout=1))
        response = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text="  TESTO MANUALE\n"))
        self.assertEqual(response.status_code, 200)
        manual_id = response.json()["manual_version_id"]
        edited = dict(self.input, request="Una richiesta più recente.")
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=edited))
        self.fake.release.set()
        completed = self.completed(job)
        current = self.client.get("/api/workspace").json()
        self.assertTrue(completed["stale"])
        self.assertEqual(current["draft_input"]["request"], "Una richiesta più recente.")
        self.assertEqual(current["manual_version_id"], manual_id)
        self.assertIsNone(current["latest_candidate_id"])
        self.assertEqual(current["versions"][0]["text"], "  TESTO MANUALE\n")
        self.assertIsNotNone(completed["candidate_id"])

    def test_conflicting_browser_revision_does_not_overwrite(self):
        command = self.command(input={"request": "Prima bozza"})
        self.assertEqual(self.client.put(f"/api/cuts/{self.cut}/draft", json=command).status_code, 200)
        stale = dict(command, command_id=str(uuid4()), input={"request": "Secondo browser"})
        response = self.client.put(f"/api/cuts/{self.cut}/draft", json=stale)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["current_revision"], 1)
        self.assertEqual(self.client.get("/api/workspace").json()["draft_input"]["request"], "Prima bozza")

    def test_error_preserves_previous_candidate_and_manual(self):
        self.prepare()
        first, _ = self.compile()
        first = self.completed(first)
        saved = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text="Una bozza manuale"))
        manual_id = saved.json()["manual_version_id"]
        self.fake.mode = "error"
        failed, _ = self.compile()
        failed = self.completed(failed)
        current = self.client.get("/api/workspace").json()
        self.assertEqual(current["state"], "error")
        self.assertEqual(current["latest_candidate_id"], first["candidate_id"])
        self.assertEqual(current["manual_version_id"], manual_id)
        self.assertIsNone(failed["candidate_id"])

    def test_clarification_is_separate_from_error(self):
        self.prepare()
        self.fake.mode = "question"
        job, _ = self.compile()
        finished = self.completed(job)
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(self.client.get("/api/workspace").json()["state"], "clarification_needed")
        self.assertIsNone(finished["candidate_id"])

    def test_invalid_draft_saved_and_invalid_compile_has_zero_calls(self):
        self.prepare()
        raw = dict(self.input, request="")
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
        self.assertEqual(saved.status_code, 200)
        response = self.client.post(f"/api/cuts/{self.cut}/compile", json=self.command(cut_id=self.cut, input=raw))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fake.calls, 0)
        self.assertEqual(self.client.get("/api/workspace").json()["draft_input"]["request"], "")

    def test_invalid_manual_reference_is_preserved_as_unvalidated_draft(self):
        self.prepare()
        job, _ = self.compile()
        completed = self.completed(job)
        exact = completed["result"]["prompt"].replace("<Subject 1>", "<Subject>") + "\n"
        saved = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact, base_candidate_id=completed["candidate_id"])).json()
        self.assertFalse(saved["versions"][-1]["structural_checks_passed"])
        copied = self.client.get(f"/api/cuts/{self.cut}/text", params={"version_id": saved["manual_version_id"]})
        self.assertEqual(copied.text, exact)
        self.assertEqual(self.fake.calls, 1)

    def test_incomplete_sources_and_duration_do_not_prevent_manual_save(self):
        self.prepare()
        raw = json.loads(json.dumps(self.input))
        raw["active_units"][0]["sources"] = "ancora da scegliere"
        raw["declared_duration_s"] = "non definita"
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
        self.assertEqual(saved.status_code, 200)
        exact = "Bozza manuale con <Subject 1>.\n"
        manual = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact))
        self.assertEqual(manual.status_code, 200, manual.text)
        self.assertEqual(manual.json()["versions"][-1]["text"], exact)
        self.assertFalse(manual.json()["versions"][-1]["structural_checks_passed"])

    def test_deleted_provisional_subject_number_is_reused(self):
        first = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        raw = first["draft_input"]
        raw["active_units"] = []
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
        second = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        self.assertEqual(second["draft_input"]["active_units"][0]["subject"], 1)
        raw = second["draft_input"]
        raw["active_units"][0]["subject"] = 99
        self.assertEqual(self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw)).status_code, 422)

    def test_repeated_provisional_deletions_do_not_consume_numbers(self):
        for _ in range(4):
            added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
            self.assertEqual(added["draft_input"]["active_units"][0]["subject"], 1)
            raw = added["draft_input"]
            raw["active_units"] = []
            self.assertEqual(self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw)).status_code, 200)
        self.assertEqual(self.fake.calls, 0)

    def test_reusing_a_gap_does_not_renumber_remaining_subjects(self):
        for _ in range(2):
            added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        raw = added["draft_input"]
        raw["active_units"] = raw["active_units"][1:]
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
        added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        self.assertEqual([u["subject"] for u in added["draft_input"]["active_units"]], [2, 1])

    def test_reuses_subject_two_without_changing_the_saved_version_identity(self):
        self.prepare()
        self.input["active_units"] = self.input["active_units"][:2]
        job, _ = self.compile()
        finished = self.completed(job)
        version_id = finished["candidate_id"]
        original = self.client.get("/api/workspace").json()
        raw = original["draft_input"] | {"request": "<Subject 1> è seduta.", "active_units": original["draft_input"]["active_units"][:1]}
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
        self.assertEqual(saved.status_code, 200, saved.text)
        added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        self.assertEqual([unit["subject"] for unit in added["draft_input"]["active_units"]], [1, 2])
        self.assertNotEqual(added["unit_ids"]["2"], original["unit_ids"]["2"])
        self.assertEqual(added["versions"], original["versions"])
        with closing(self.app.state.repository.connect()) as db:
            self.assertEqual(self.app.state.repository._version_subject_ids(db, version_id)["2"], original["unit_ids"]["2"])
        # Una copia identica dei campi non rende equivalente la nuova identità.
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=original["draft_input"]))
        response = self.client.post(f"/api/cuts/{self.cut}/confirm", json=self.command(version_id=version_id))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "reference_reconciliation_required")
        self.assertEqual(self.fake.calls, 1)

    def test_in_flight_job_keeps_its_identity_after_number_reuse(self):
        self.prepare()
        self.fake.release.clear()
        job, _ = self.compile()
        self.assertTrue(self.fake.entered.wait(timeout=1))
        original_id = self.client.get("/api/workspace").json()["unit_ids"]["1"]
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input={"request": "", "active_units": [], "dialogues": []}))
        added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        self.assertEqual(added["draft_input"]["active_units"][0]["subject"], 1)
        self.assertNotEqual(added["unit_ids"]["1"], original_id)
        self.fake.release.set()
        finished = self.completed(job)
        self.assertTrue(finished["stale"])
        with closing(self.app.state.repository.connect()) as db:
            self.assertEqual(self.app.state.repository._version_subject_ids(db, finished["candidate_id"])["1"], original_id)

    def test_live_draft_mentions_keep_their_subject_number(self):
        for kind in ["request", "speaker"]:
            with self.subTest(kind=kind):
                added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
                number = added["draft_input"]["active_units"][-1]["subject"]
                raw = added["draft_input"]
                raw["active_units"] = [unit for unit in raw["active_units"] if unit["subject"] != number]
                if kind == "request":
                    raw["request"] = f"<Subject {number}> entra."
                else:
                    with_dialogue = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="dialogue")).json()
                    raw["dialogues"] = with_dialogue["draft_input"]["dialogues"]
                    raw["dialogues"][-1]["speaker_subject"] = number
                self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
                blocked = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit"))
                self.assertEqual(blocked.status_code, 409, blocked.text)
                self.assertIn(f"Subject {number}", blocked.json()["detail"]["message"])
                self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(
                    input=raw | {"request": "", "dialogues": []}))
                new = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
                self.assertEqual(new["draft_input"]["active_units"][-1]["subject"], number)

    def test_reopen_preserves_manual_text_and_zero_additional_calls(self):
        self.prepare()
        job, _ = self.compile()
        finished = self.completed(job)
        exact = "\nTesto corretto  con spazi.\n"
        saved = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact, base_candidate_id=finished["candidate_id"])).json()
        with TestClient(create_app(Path(self.temp.name), self.fake), base_url="http://127.0.0.1:8767") as reopened:
            workspace = reopened.get("/api/workspace").json()
            self.assertEqual(workspace["manual_version_id"], saved["manual_version_id"])
            copied = reopened.get(f"/api/cuts/{self.cut}/text", params={"version_id": saved["manual_version_id"]})
            self.assertEqual(copied.text, exact)
        self.assertEqual(self.fake.calls, 1)

    def test_loopback_host_and_origin(self):
        command = self.command(input={"request": "x"})
        self.assertEqual(self.client.put(f"/api/cuts/{self.cut}/draft", json=command, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/workspace", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.fake.calls, 0)

    def test_picture_subject_and_binding_are_three_separate_actions(self):
        picture = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="picture")).json()
        self.assertEqual(picture["draft_input"]["active_units"], [])
        self.assertEqual(picture["draft_input"]["pictures"][0]["slot"], 1)
        unit = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        self.assertEqual(len(unit["draft_input"]["pictures"]), 1)
        self.assertEqual(unit["draft_input"]["active_units"][0]["sources"], [])
        command = self.command(subject=1)
        first = self.client.post(f"/api/cuts/{self.cut}/sources", json=command).json()
        retry = self.client.post(f"/api/cuts/{self.cut}/sources", json=command).json()
        self.assertEqual(retry, first)
        self.assertEqual(first["draft_input"]["active_units"][0]["sources"], [{"picture_id": None, "attribute": "identity"}])
        second = self.client.post(f"/api/cuts/{self.cut}/sources", json=self.command(subject=1)).json()
        self.assertEqual(second["draft_input"]["active_units"][0]["sources"][-1]["attribute"], "outfit")
        self.assertEqual(len(second["draft_input"]["pictures"]), 1)
        self.assertEqual(self.fake.calls, 0)

    def test_nine_picture_limit_does_not_limit_subjects(self):
        for _ in range(9):
            added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="picture"))
            self.assertEqual(added.status_code, 200)
        revision = added.json()["revision"]
        tenth = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="picture"))
        self.assertEqual(tenth.status_code, 422)
        self.assertIn("9", tenth.json()["detail"]["message"])
        self.assertEqual(self.client.get("/api/workspace").json()["revision"], revision)
        for _ in range(11):
            added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit"))
            self.assertEqual(added.status_code, 200)
        data = added.json()["draft_input"]
        self.assertEqual(len(data["active_units"]), 11)
        picture = data["pictures"][0]
        picture.update(description_en="A group of people", confirmed=True, linked_to_h3=True)
        for unit in data["active_units"]:
            unit.update(name=f"Persona {unit['subject']}", description_en=f"person {unit['subject']}", confirmed=True,
                        sources=[{"picture_id": picture["id"], "attribute": "identity"}])
        data["request"] = "<Subject 1> entra."
        self.assertEqual(len(CompileInput.model_validate(data).active_units), 11)
        self.assertEqual(self.fake.calls, 0)

    def test_a07_identity_and_skirt_are_sources_of_one_subject(self):
        self.prepare()
        self.input["active_units"] = self.input["active_units"][:1]
        self.input["dialogues"] = []
        self.input["request"] = "<Subject 1> cammina."
        # Due immagini inutilizzate possono essere bozze non confermate.
        for picture in self.input["pictures"][2:]:
            picture.update(description_en="", confirmed=False, linked_to_h3=False)
        self.fake.plan = Interpretation(narrative_en="<Subject 1> walks.", estimated_duration_s=5.0, question=None)
        job, _ = self.compile()
        self.assertEqual(self.completed(job)["status"], "succeeded")
        data = self.fake.last_input
        self.assertEqual(len(data.active_units), 1)
        self.assertEqual([data.slot_for(s) for s in data.active_units[0].sources], [1, 2])
        self.assertEqual([s.attribute for s in data.active_units[0].sources], ["identity", "outfit"])
        self.assertEqual(len(data.active_pictures), 2)
        self.assertEqual(self.fake.calls, 1)

    def test_same_picture_can_explicitly_identify_two_subjects(self):
        self.prepare()
        identity = self.input["pictures"][0]
        identity["description_en"] = "Anna and Marco in the same image"
        self.input["active_units"][1]["sources"][0]["picture_id"] = identity["id"]
        job, _ = self.compile()
        self.assertEqual(self.completed(job)["status"], "succeeded")
        first, second = self.fake.last_input.active_units[:2]
        self.assertEqual(first.sources[0].picture_id, second.sources[0].picture_id)
        self.assertEqual(self.fake.last_input.slot_for(second.sources[0]), 1)
        self.assertEqual(self.fake.calls, 1)

    def test_distinct_pictures_with_same_slot_block_compile_but_not_manual(self):
        self.prepare()
        self.input["pictures"][1]["slot"] = 1
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=self.input))
        self.assertEqual(saved.status_code, 200)
        response = self.client.post(f"/api/cuts/{self.cut}/compile", json=self.command(cut_id=self.cut, input=self.input))
        self.assertEqual(response.status_code, 422)
        self.assertIn("Picture 1", response.json()["detail"]["message"])
        exact = "  Testo manuale da conservare.\n"
        manual = self.client.put(f"/api/cuts/{self.cut}/manual", json=self.command(text=exact)).json()
        version = manual["versions"][-1]
        self.assertFalse(version["structural_checks_passed"])
        self.assertTrue(any("Picture 1" in issue for issue in version["issues"]))
        copied = self.client.get(f"/api/cuts/{self.cut}/text", params={"version_id": manual["manual_version_id"]})
        self.assertEqual(copied.text, exact)
        self.assertEqual(self.fake.calls, 0)

    def test_picture_slot_changes_keep_source_bindings(self):
        self.prepare()
        source_id = self.input["active_units"][0]["sources"][1]["picture_id"]
        self.input["pictures"][1]["slot"] = 5
        job, _ = self.compile()
        self.completed(job)
        source = self.fake.last_input.active_units[0].sources[1]
        self.assertEqual(source.picture_id, source_id)
        self.assertEqual(self.fake.last_input.slot_for(source), 5)

    def test_deleted_picture_leaves_missing_binding_instead_of_reassignment(self):
        self.prepare()
        missing_id = self.input["pictures"].pop(1)["id"]
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=self.input))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["draft_input"]["active_units"][0]["sources"][1]["picture_id"], missing_id)
        response = self.client.post(f"/api/cuts/{self.cut}/compile", json=self.command(cut_id=self.cut, input=self.input))
        self.assertEqual(response.status_code, 422)
        self.assertIn("Subject 1", response.json()["detail"]["message"])
        next_picture = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="picture")).json()
        replacement = next_picture["draft_input"]["pictures"][-1]
        self.assertEqual(replacement["slot"], 2)
        self.assertNotEqual(replacement["id"], missing_id)
        self.assertEqual(next_picture["draft_input"]["active_units"][0]["sources"][1]["picture_id"], missing_id)
        self.assertEqual(self.fake.calls, 0)

    def test_catalogue_and_bindings_reject_never_allocated_picture_ids(self):
        self.prepare()
        for placement in ["catalogue", "binding"]:
            raw = json.loads(json.dumps(self.input))
            if placement == "catalogue":
                raw["pictures"][0]["id"] = str(uuid4())
            else:
                raw["active_units"][0]["sources"][0]["picture_id"] = str(uuid4())
            response = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw))
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fake.calls, 0)

    def test_even_coherent_forged_catalogue_cannot_start_inference(self):
        self.prepare()
        original = self.input["pictures"][0]["id"]
        forged = str(uuid4())
        self.input["pictures"][0]["id"] = forged
        for unit in self.input["active_units"]:
            for source in unit["sources"]:
                if source["picture_id"] == original:
                    source["picture_id"] = forged
        # Il solo schema relazionale è coerente: l'autorizzazione dell'ID è del server.
        CompileInput.model_validate(self.input)
        response = self.client.post(f"/api/cuts/{self.cut}/compile", json=self.command(cut_id=self.cut, input=self.input))
        self.assertEqual(response.status_code, 422)
        self.assertIn("server", response.json()["detail"]["message"])
        self.assertEqual(self.fake.calls, 0)

    def test_missing_subject_reference_blocks_allocation_and_unallocated_number_is_rejected(self):
        added = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit")).json()
        data = added["draft_input"]
        data["request"] = "<Subject 2> entra."
        self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=data))
        blocked = self.client.post(f"/api/cuts/{self.cut}/items", json=self.command(kind="unit"))
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"]["code"], "subject_references_unresolved")
        data["active_units"][0]["subject"] = 2
        rejected = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=data))
        self.assertEqual(rejected.status_code, 422)

    def test_old_interface_write_is_rejected_without_erasing_new_catalogue(self):
        self.prepare()
        before = self.client.get("/api/workspace").json()
        command = self.command(input=CASES[0]["input"])
        command["input"].pop("pictures", None)  # Simula una scheda della vecchia UI.
        response = self.client.put(f"/api/cuts/{self.cut}/draft", json=command)
        self.assertEqual(response.status_code, 422)
        self.assertIn("Interfaccia aggiornata", response.json()["detail"]["message"])
        self.assertEqual(self.client.get("/api/workspace").json(), before)
        self.assertEqual(self.fake.calls, 0)


if __name__ == "__main__":
    unittest.main()
