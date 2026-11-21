import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.compiler import StructuralError, render
from app.domain import CompileInput, CurrentInterpretation
from app.interpreter import model_context
from app.repository import Repository
from app.shots import CameraPreset
from test_api import FakeOllama
from test_picture_registry import catalogue_input


def preset(tag, framing):
    return CameraPreset(id=str(uuid4()), name=tag, tag=tag, revision=1,
                        camera={"framing": framing, "angle": "eye_level", "movement": "static"})


class ShotRenderingTests(unittest.TestCase):
    def setUp(self):
        self.raw = catalogue_input()
        self.raw.update(
            request="#full su <Subject 1>. A 3,5 secondi passa a #close su <Subject 1>. At 00:07.000, #full su <Subject 1>.",
            shot_presets=[preset("full", "full").model_dump(), preset("close", "close").model_dump()],
            declared_duration_s=10.0,
            dialogues=[dict(id="d1", text="  Sono pronta!  ", language="Italian", speaker_subject=1, confirmed=True)],
        )
        self.plan = CurrentInterpretation(
            narrative_en="{{shot:s1}} <Subject 1> is seated. {{dialogue:d1}} {{shot:s2}} <Subject 1> opens her eyes. {{shot:s3}} <Subject 1> stands.",
            summary_en="<Subject 1> speaks as the view alternates between a full shot and a close-up.",
            estimated_duration_s=10.0, question=None)

    def test_reused_preset_produces_three_timed_shots_with_verbatim_dialogue(self):
        data = CompileInput.model_validate(self.raw)
        context = model_context(data)
        self.assertEqual([shot["at_s"] for shot in context["shot_sequence"]], [0, 3.5, 7])
        self.assertNotIn("#full", context["request"])
        self.assertNotIn("Sono pronta", json.dumps(context))
        prompt = render(data, self.plan, "shots").prompt
        self.assertIn("[Shot 1] Use a full shot.", prompt)
        self.assertIn("[Shot 2] At 00:03.500, the camera cuts to a close-up", prompt)
        self.assertIn("[Shot 3] At 00:07.000, the camera cuts to a full shot", prompt)
        self.assertEqual(prompt.count("<d>[Italian]   Sono pronta!  </d>."), 1)
        self.assertNotIn("{{", prompt)
        self.assertEqual(prompt.count("the camera cuts to"), 2)
        self.assertEqual(prompt.count("The camera holds a static shot."), 3)
        self.assertEqual(prompt.count("Use an eye-level angle."), 3)
        self.assertIn("<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3])", prompt)

    def test_invalid_tags_missing_times_and_nonincreasing_or_out_of_range_times(self):
        for request in [
            "#unknown", "#full. #close", "#full. A 5 secondi #close. A 4 secondi #full",
            "#full. A 3 secondi #close. A 3 secondi #full", "#full. A 10 secondi #close",
            "A 2 secondi #full", "#full. At 00:63.000 #close",
        ]:
            with self.subTest(request=request), self.assertRaises(ValidationError):
                CompileInput.model_validate(self.raw | {"request": request})
        with self.assertRaises(ValidationError):
            CompileInput.model_validate(self.raw | {"camera": {"movement": "static"}})

    def test_explicit_shots_without_presets_keep_boundaries_times_and_dialogue(self):
        raw = self.raw | dict(shot_presets=[], request=(
            '[Shot 1] <Subject 1> è seduta e pronuncia d1. '
            '[shot 2] At 00:03.500, primo piano sul volto di <Subject 1>. '
            '[Shot 3] A 7 secondi, <Subject 1> si alza.'))
        inputs = CompileInput.model_validate(raw)
        context = model_context(inputs)
        self.assertEqual([shot['at_s'] for shot in context['shot_sequence']], [0, 3.5, 7])
        self.assertTrue(all(not shot['has_camera_preset'] for shot in context['shot_sequence']))
        self.assertNotIn('[Shot', context['request'])
        self.assertIn('primo piano', context['request'])
        result = render(inputs, self.plan, 'explicit-shots')
        self.assertTrue(result.structural_checks_passed)
        self.assertIn('[Shot 2] At 00:03.500, the shot changes.', result.prompt)
        self.assertIn('[Shot 3] At 00:07.000, the shot changes.', result.prompt)
        self.assertEqual(result.prompt.count('<d>[Italian]   Sono pronta!  </d>.'), 1)
        self.assertNotIn('Use a full shot.', result.prompt)

    def test_explicit_shot_with_adjacent_preset_is_one_shot(self):
        inputs = CompileInput.model_validate(self.raw | dict(request=(
            '[Shot 1] #full su <Subject 1>. '
            '[Shot 2] At 00:03.500, #close sul volto. '
            'At 00:07.000, #full su <Subject 1>.')))
        context = model_context(inputs)
        self.assertEqual([shot['id'] for shot in context['shot_sequence']], ['s1', 's2', 's3'])
        self.assertTrue(all(shot['has_camera_preset'] for shot in context['shot_sequence']))
        prompt = render(inputs, self.plan, 'explicit-preset').prompt
        self.assertEqual(prompt.count('Use a full shot.'), 1)
        self.assertIn('[Shot 2] At 00:03.500, the camera cuts to a close-up.', prompt)

    def test_explicit_shot_numbers_and_times_are_checked_before_inference(self):
        for request in (
            '[Shot 2] Una stanza.', '[Shot 0] Una stanza.',
            '[Shot 1] Una stanza. [Shot 3] At 00:03.000, La porta.',
            '[Shot 1] Una stanza. [Shot 2] La porta.',
            '[Shot 1] Una stanza. [Shot 2] At 00:03:000, La porta.',
            '[Shot 1] Una stanza. [Shot 2] At 00:03.000, La porta. [Shot 3] At 00:02.000, La finestra.',
        ):
            with self.subTest(request=request), self.assertRaises(ValidationError):
                CompileInput.model_validate(self.raw | {'request': request, 'shot_presets': []})

    def test_model_cannot_drop_repeat_reorder_or_invent_shot_boundaries(self):
        for narrative in [
            "{{shot:s1}} <Subject 1> waits.",
            "{{shot:s1}} <Subject 1> waits. {{shot:s3}} {{shot:s2}} {{dialogue:d1}}",
            "{{shot:s1}} {{shot:s2}} {{shot:s2}} {{shot:s3}} {{dialogue:d1}}",
            "{{shot:s1}} {{shot:s2}} {{shot:s3}} {{shot:s4}} {{dialogue:d1}}",
        ]:
            with self.subTest(narrative=narrative), self.assertRaises(StructuralError):
                render(CompileInput.model_validate(self.raw), self.plan.model_copy(update={"narrative_en": narrative}), "bad")
        raw = copy.deepcopy(self.raw)
        raw["declared_duration_s"] = None
        result = render(CompileInput.model_validate(raw), self.plan.model_copy(update={"estimated_duration_s": 6.0}), "short")
        self.assertFalse(result.confirmation_allowed)
        self.assertIn("ultimo cambio", result.issues[0])


class ShotLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fake = FakeOllama()
        self.app = create_app(self.temp.name, self.fake)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8767")
        self.client.__enter__()
        self.cut = self.client.get("/api/workspace").json()["id"]
        self.project = self.view()["project_id"]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def view(self):
        return self.client.get(f"/api/cuts/{self.cut}").json()

    def save(self, tag="close", camera=None, revision=0):
        project = next(p for p in self.client.get("/api/projects").json() if p["id"] == self.project)
        payload = dict(command_id=str(uuid4()), expected_revision=project["revision"],
                       expected_preset_revision=revision, name="Primo piano", camera=camera or {"framing": "close"})
        return self.client.put(f"/api/projects/{self.project}/camera-presets/{tag}", json=payload), payload

    def test_save_replay_conflict_cross_cut_reuse_and_historical_snapshot(self):
        response, command = self.save()
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()["camera_presets"][0]
        self.assertEqual(self.client.put(f"/api/projects/{self.project}/camera-presets/close", json=command).json(), response.json())
        scene = self.client.get("/api/projects").json()[0]["scenes"][0]
        second = self.client.post(f"/api/scenes/{scene['id']}/cuts", json=dict(
            command_id=str(uuid4()), expected_revision=scene["revision"], name="Secondo")).json()
        self.assertEqual(second["camera_presets"], [snapshot])
        inputs = dict(request="#close su una stanza vuota.", active_units=[], pictures=[], dialogues=[],
                      shot_presets=[snapshot], declared_duration_s=6.0)
        self.fake.plan = CurrentInterpretation(
            narrative_en="{{shot:s1}} A close-up shows an empty room.",
            summary_en="An empty room is shown.", estimated_duration_s=6.0, question=None)
        job = self.client.post(f"/api/cuts/{self.cut}/compile", json=dict(
            command_id=str(uuid4()), expected_revision=self.view()["revision"], cut_id=self.cut, input=inputs, model="local-test"))
        self.assertEqual(job.status_code, 202, job.text)
        self.app.state.worker.pending.join()
        before = self.view()["versions"][-1]
        updated, _ = self.save(camera={"framing": "full"}, revision=1)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(self.view()["versions"][-1], before)
        self.assertEqual(before["input_snapshot"]["shot_presets"], [snapshot])
        stale = self.client.post(f"/api/cuts/{self.cut}/compile", json=dict(
            command_id=str(uuid4()), expected_revision=self.view()["revision"], cut_id=self.cut, input=inputs))
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.fake.calls, 1)
        stale_save, _ = self.save(revision=1)
        self.assertEqual(stale_save.status_code, 409)
        other = self.client.post("/api/projects", json=dict(
            command_id=str(uuid4()), expected_revision=0, name="Altro progetto")).json()
        other_cut = other["scenes"][0]["cuts"][0]["id"]
        self.assertEqual(self.client.get(f"/api/cuts/{other_cut}").json()["camera_presets"], [])
        forbidden = self.client.post(f"/api/cuts/{other_cut}/compile", json=dict(
            command_id=str(uuid4()), expected_revision=0, cut_id=other_cut, input=inputs))
        self.assertEqual(forbidden.status_code, 409, forbidden.text)
        self.assertEqual(self.fake.calls, 1)

    def test_migration_from_schema_six_preserves_existing_rows_and_creates_backup(self):
        path = Path(self.temp.name) / "workspace.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            before = db.execute("SELECT * FROM cuts").fetchall()
            db.execute("DROP TABLE project_camera_presets")
            db.execute("UPDATE settings SET value='6' WHERE key='schema_version'")
        upgraded = Repository(self.temp.name)
        with closing(upgraded.connect()) as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT * FROM cuts")], before)
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], "8")
        with closing(sqlite3.connect(Path(self.temp.name) / "workspace.before-camera-presets.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], "6")

    def test_purging_project_removes_its_presets(self):
        self.assertEqual(self.save()[0].status_code, 200)
        project = self.client.get("/api/projects").json()[0]
        self.client.put(f"/api/projects/{self.project}/trash", json=dict(
            command_id=str(uuid4()), expected_revision=project["revision"], trashed=True))
        selection = dict(scope="project", resource_id=self.project)
        plan = self.client.post("/api/trash/preview", json=selection).json()
        self.assertEqual(plan["blockers"], [])
        response = self.client.post("/api/trash/purge", json=dict(
            command_id=str(uuid4()), selection=selection, plan_hash=plan["plan_hash"],
            confirmed=True, confirmation="ELIMINA"))
        self.assertEqual(response.status_code, 200, response.text)
        with closing(self.app.state.repository.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM project_camera_presets").fetchone()[0], 0)
