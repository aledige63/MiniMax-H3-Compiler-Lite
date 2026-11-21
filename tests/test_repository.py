import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.contracts import AddItemCommand, DraftCommand, WebCompileCommand
from app.domain import CompileInput, CompileResult
from app.legacy_store import LegacyRepository as Repository
from app.store import digest

CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("m0_cases.json").read_text())


def legacy_archive(directory, duplicate_slot=False):
    Repository(directory)
    path = Path(directory) / "workspace.json"
    state = json.loads(path.read_text())
    for key in ["picture_registry_version", "picture_ids", "subject_numbers", "legacy_picture_ids"]:
        state.pop(key, None)
    legacy_input = json.loads(json.dumps(CASES[0]["input"]))
    if duplicate_slot:
        legacy_input["active_units"][1]["sources"][0]["picture_slot"] = 1
    state.update(draft_input=legacy_input, revision=12, next_subject=4, next_dialogue=2, state="proposal")
    generated_id, manual_id, job_id = [str(uuid4()) for _ in range(3)]
    common = {"input_hash": "hash-storico-da-non-ricalcolare", "input_revision": 10,
              "duration_s": 8.0, "duration_origin": "estimated", "structural_checks_passed": True,
              "user_approved": False, "issues": []}
    state["versions"] = [{"id": generated_id, "origin": "generated", "text": "PROMPT STORICO <Subject 1>\n", **common},
                         {"id": manual_id, "origin": "manual", "text": "\n  CORREZIONE  manuale esatta.\n", **common}]
    state["latest_candidate_id"], state["manual_version_id"] = generated_id, manual_id
    state["jobs"] = {job_id: {"id": job_id, "cut_id": state["id"], "status": "succeeded",
        "input_revision": 10, "input_hash": common["input_hash"], "model": "modello-storico",
        "result": CompileResult(status="proposal", input_hash=common["input_hash"], prompt=state["versions"][0]["text"]).model_dump(mode="json"),
        "candidate_id": generated_id, "stale": True, "input": json.loads(json.dumps(legacy_input))}}
    state["latest_job_id"] = job_id
    command = DraftCommand(command_id=uuid4(), expected_revision=11, input=legacy_input)
    response = {key: json.loads(json.dumps(state[key])) for key in
                ["id", "revision", "draft_input", "state", "latest_candidate_id", "manual_version_id", "versions"]}
    response["latest_job"] = None
    state["commands"] = {str(command.command_id): {
        "payload_hash": digest({"operation": "draft", "cut_id": state["id"], "command": command.model_dump(mode="json")}),
        "job_id": None, "response": response}}
    previous = json.dumps(state, ensure_ascii=False, indent=2).encode()
    path.write_bytes(previous)
    return state, command, previous


class RestartTests(unittest.TestCase):
    def test_partial_interface_upgrade_keeps_legacy_sources_convertible(self):
        with tempfile.TemporaryDirectory() as directory:
            original, _, _ = legacy_archive(directory)
            original["draft_input"]["pictures"] = []
            path = Path(directory) / "workspace.json"
            path.write_text(json.dumps(original, ensure_ascii=False))
            cut = Repository(directory).workspace()
            self.assertEqual(len(cut.draft_input["pictures"]), 4)
            self.assertTrue(all(s.get("picture_id") for u in cut.draft_input["active_units"] for s in u["sources"]))
            self.assertEqual(cut.versions[1].text, original["versions"][1]["text"])

    def test_picture_migration_preserves_history_and_writes_exact_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            original, _, previous = legacy_archive(directory)
            repository = Repository(directory)
            current = repository.workspace()
            stored = json.loads((Path(directory) / "workspace.json").read_text())
            self.assertEqual(current.revision, original["revision"])
            self.assertEqual(current.draft_input["request"], original["draft_input"]["request"])
            self.assertEqual([u["subject"] for u in current.draft_input["active_units"]], [1, 2, 3])
            self.assertEqual(len(current.draft_input["pictures"]), 4)
            self.assertEqual(len(current.draft_input["active_units"][0]["sources"]), 2)
            for key in ["versions", "jobs", "commands", "latest_candidate_id", "manual_version_id"]:
                self.assertEqual(stored[key], original[key])
            self.assertEqual((Path(directory) / "workspace.before-picture-registry.json").read_bytes(), previous)
            self.assertEqual(repository.text(current.id, original["manual_version_id"]), "\n  CORREZIONE  manuale esatta.\n")
            self.assertIsNone(current.versions[0].input_snapshot)
            self.assertIsNone(current.versions[1].input_snapshot)
            ids = [p["id"] for p in current.draft_input["pictures"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(set(ids).issubset(stored["picture_ids"]))
            reopened = Repository(directory)
            self.assertEqual(reopened.workspace().draft_input, current.draft_input)
            self.assertEqual(len(list(Path(directory).glob("workspace.before-picture-registry*.json"))), 1)

    def test_duplicate_legacy_slots_remain_distinct_and_require_review(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_archive(directory, duplicate_slot=True)
            cut = Repository(directory).workspace()
            pictures = cut.draft_input["pictures"]
            slot_one = [p for p in pictures if p["slot"] == 1]
            self.assertEqual(len(slot_one), 2)
            self.assertNotEqual(slot_one[0]["id"], slot_one[1]["id"])
            self.assertIn("Picture 1", " ".join(cut.catalogue_issues))
            with self.assertRaises(ValidationError) as error:
                CompileInput.model_validate(cut.draft_input)
            self.assertIn("Picture 1", str(error.exception))

    def test_historical_idempotent_cut_response_is_upgraded_without_rewriting_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            original, command, _ = legacy_archive(directory)
            repository = Repository(directory)
            cut = repository.workspace()
            before = json.loads((Path(directory) / "workspace.json").read_text())
            response = repository.save_draft(cut.id, command)
            retry = repository.save_draft(cut.id, command)
            self.assertEqual(response, retry)
            self.assertIn("pictures", response.draft_input)
            self.assertEqual(response.revision, original["revision"])
            self.assertEqual(response.draft_input["request"], command.input["request"])
            self.assertTrue(all(s.get("picture_id") for u in response.draft_input["active_units"] for s in u["sources"]))
            self.assertEqual(response.versions[1].text, original["versions"][1]["text"])
            after = json.loads((Path(directory) / "workspace.json").read_text())
            self.assertEqual(before, after)
            self.assertTrue({p["id"] for p in response.draft_input["pictures"]}.issubset(after["picture_ids"]))

    def test_picture_ids_remain_registered_when_image_is_deleted_and_reopened(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(directory)
            cut = repository.workspace()
            cut = repository.add_item(cut.id, AddItemCommand(command_id=uuid4(), expected_revision=cut.revision, kind="picture"))
            old_id = cut.draft_input["pictures"][0]["id"]
            data = cut.draft_input
            data["pictures"] = []
            cut = repository.save_draft(cut.id, DraftCommand(command_id=uuid4(), expected_revision=cut.revision, input=data))
            repository = Repository(directory)
            new = repository.add_item(cut.id, AddItemCommand(command_id=uuid4(), expected_revision=cut.revision, kind="picture"))
            self.assertEqual(new.draft_input["pictures"][0]["slot"], 1)
            self.assertNotEqual(new.draft_input["pictures"][0]["id"], old_id)
            stored = json.loads((Path(directory) / "workspace.json").read_text())
            self.assertIn(old_id, stored["picture_ids"])

    def test_old_provisional_counter_does_not_survive_as_a_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(directory)
            cut = repository.workspace()
            for _ in range(3):
                cut = repository.add_item(cut.id, AddItemCommand(command_id=uuid4(), expected_revision=cut.revision, kind="unit"))
            cut = repository.save_draft(cut.id, DraftCommand(command_id=uuid4(), expected_revision=cut.revision,
                                                            input={"request": "", "active_units": [], "pictures": [], "dialogues": []}))
            reopened = Repository(directory)
            new = reopened.add_item(cut.id, AddItemCommand(command_id=uuid4(), expected_revision=cut.revision, kind="unit"))
            self.assertEqual(new.draft_input["active_units"][0]["subject"], 1)

    def test_interrupted_job_is_failed_without_silent_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(directory)
            cut = repository.workspace()
            command = WebCompileCommand(command_id=uuid4(), cut_id=cut.id, expected_revision=0,
                                        input=CompileInput(request="Una stanza vuota.", pictures=[], declared_duration_s=4.0), model="local-test")
            job, created = repository.compile(cut.id, command)
            repository.start_job(job.id)
            reopened = Repository(directory)
            current = reopened.job(job.id)
            self.assertEqual(current.status, "failed")
            self.assertEqual(current.result.error_code, "interrupted")
            self.assertEqual(reopened.workspace().state, "error")
            self.assertEqual(reopened.workspace().draft_input["request"], "Una stanza vuota.")
            self.assertFalse((Path(directory) / "workspace.tmp").exists())


if __name__ == "__main__":
    unittest.main()
