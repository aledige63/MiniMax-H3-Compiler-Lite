import copy
import unittest

from pydantic import ValidationError

from app.domain import CompileInput
from app.validation import validation_messages
import test_api as api_fixtures
from test_picture_registry import catalogue_input


class ValidationMessageTests(unittest.TestCase):
    def test_all_missing_confirmations_are_named_without_treating_unused_pictures_as_required(self):
        raw = catalogue_input()
        raw["active_units"][0].update(subject=4, name="Mamma", confirmed=False)
        raw["request"] = "<Subject 4> parla."
        raw["pictures"][0].update(confirmed=False, linked_to_h3=False)
        raw["pictures"].append(dict(id="unused", slot=9))
        raw["audio_references"] = [dict(id="a1", slot=2, name="Mamma", role="speech", confirmed=False, linked_to_h3=False)]
        with self.assertRaises(ValidationError) as caught:
            CompileInput.model_validate(raw)
        messages = validation_messages(caught.exception, raw)
        self.assertTrue(any("Subject 4 · Mamma" in line and "Confermo definizione" in line for line in messages))
        self.assertTrue(any("Picture 1 · Ann" in line and "Ho controllato" in line for line in messages))
        self.assertTrue(any("Picture 1 · Ann" in line and "La collegherò" in line for line in messages))
        self.assertTrue(any("Audio 2 · Mamma" in line and "file WAV o MP3" in line for line in messages))
        self.assertTrue(any("Audio 2 · Mamma" in line and "Parlante dell’audio" in line for line in messages))
        self.assertTrue(any("Audio 2 · Mamma" in line and "Trascrizione verificata" in line for line in messages))
        self.assertFalse(any("Picture 9" in line for line in messages))
        raw["active_units"][0]["confirmed"] = True
        with self.assertRaises(ValidationError) as caught:
            CompileInput.model_validate(raw)
        self.assertFalse(any("Subject 4" in line for line in validation_messages(caught.exception, raw)))

    def test_field_error_uses_reference_name_and_numeric_limit(self):
        raw = catalogue_input() | {"declared_duration_s": 20.0}
        with self.assertRaises(ValidationError) as caught:
            CompileInput.model_validate(raw)
        self.assertTrue(any("Durata dichiarata" in message and "15" in message for message in validation_messages(caught.exception, raw)))

    def test_malformed_fields_return_validation_errors_instead_of_server_exceptions(self):
        for patch in [
            {"description_en": None}, {"sources": None}, {"role": {}}, {"subject": {}},
        ]:
            raw = catalogue_input()
            raw["active_units"][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                CompileInput.model_validate(raw)


class PreflightApiTests(unittest.TestCase):
    setUp = api_fixtures.ApiTests.setUp
    tearDown = api_fixtures.ApiTests.tearDown
    command = api_fixtures.ApiTests.command
    prepare = api_fixtures.ApiTests.prepare

    def test_compile_reports_all_missing_checks_before_creating_job_or_calling_model(self):
        self.prepare()
        raw = copy.deepcopy(self.input)
        raw["active_units"][0]["confirmed"] = False
        raw["pictures"][0]["linked_to_h3"] = False
        raw["dialogues"][0]["confirmed"] = False
        before = self.client.get(f"/api/cuts/{self.cut}").json()
        response = self.client.post(f"/api/cuts/{self.cut}/compile", json=self.command(
            cut_id=self.cut, input=raw, model="local-test"))
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "incomplete_input")
        self.assertGreaterEqual(len(detail["issues"]), 3)
        self.assertTrue(any("Subject 1" in issue and "Confermo" in issue for issue in detail["issues"]))
        self.assertTrue(any("Picture 1" in issue and "collegherò" in issue for issue in detail["issues"]))
        self.assertTrue(any("Battuta d1" in issue and "Confermo" in issue for issue in detail["issues"]))
        self.assertEqual(self.fake.calls, 0)
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}").json(), before)
        saved = self.client.put(f"/api/cuts/{self.cut}/draft", json=self.command(input=raw)).json()
        self.assertTrue(any("Subject 1" in issue for issue in saved["catalogue_issues"]))
