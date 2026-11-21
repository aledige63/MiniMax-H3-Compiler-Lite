import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.compiler import SECTIONS, StructuralError, render
from app.domain import CompileInput, Interpretation
from app.interpreter import OllamaClient, OllamaError, input_hash, model_context

CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("m0_cases.json").read_text())


def data(index=0):
    return CompileInput.model_validate(CASES[index]["input"])


def plan(index=0):
    return Interpretation.model_validate(CASES[index]["expected_plan"])


def structured_plan():
    return dict(narrative_parts=[
        {"action_en": "<Subject 1> is sitting on the sofa and looks toward the camera."},
        {"dialogue_id": "d1"},
        {"action_en": "While <Subject 1> speaks, <Subject 2> enters and stops beside her."},
    ], estimated_duration_s=8.0, question=None)


def response(content=None, reason="stop"):
    current = structured_plan() | {"summary_en": "<Subject 1> speaks while <Subject 2> enters."}
    return dict(message={"content": content or json.dumps(current)}, done=True,
                done_reason=reason, prompt_eval_count=700, eval_count=90,
                load_duration=1000000000, total_duration=2000000000)


class RendererTests(unittest.TestCase):
    def test_a01_expected_six_sections(self):
        result = render(data(), plan(), "test")
        expected = Path(__file__).with_name("fixtures").joinpath("a01_expected.txt").read_text().rstrip("\n")
        self.assertEqual(result.prompt, expected)
        self.assertTrue(result.structural_checks_passed)
        self.assertTrue(result.confirmation_allowed)
        self.assertFalse(result.user_approved)

    def test_four_cases_structure_and_dialogue_verbatim(self):
        for index in range(4):
            with self.subTest(case=CASES[index]["id"]):
                result = render(data(index), plan(index), "test")
                headings = [line[:-1] for line in result.prompt.splitlines() if line[:-1] in SECTIONS]
                self.assertEqual(headings, list(SECTIONS))
                self.assertEqual(result.prompt.count("[Shot 1] "), 1)
                self.assertNotIn("<Audio", result.prompt)
                for d in data(index).dialogues:
                    self.assertIn(f"<d>[{d.language}] {d.text}</d>.", result.prompt)

    def test_dialogue_has_one_period_immediately_after_closing_tag(self):
        for ending in ["", ".", " .", "..."]:
            p = plan().model_copy(update={"narrative_en": "{{dialogue:d1}}" + ending})
            prompt = render(data(), p, "terminator").prompt
            with self.subTest(ending=ending):
                self.assertIn("Sono pronta.</d>.\n\n", prompt)
                self.assertNotIn("</d>..", prompt)

    def test_external_period_keeps_dialogue_text_and_following_action_exact(self):
        raw = data().model_dump()
        raw["dialogues"][0]["text"] = "  Davvero?!  "
        p = plan().model_copy(update={"narrative_en": "{{dialogue:d1}}. After the line ends, <Subject 1> smiles."})
        prompt = render(CompileInput.model_validate(raw), p, "verbatim").prompt
        self.assertIn("<d>[Italian]   Davvero?!  </d>. After the line ends, <Subject 1> smiles.", prompt)
        self.assertNotIn("</d>..", prompt)

    def test_no_previous_dialogue_in_next_cut(self):
        render(data(2), plan(2), "previous")
        prompt = render(data(3), plan(3), "current").prompt
        self.assertNotIn("<d>", prompt)
        self.assertNotIn("(S1)", prompt)
        self.assertNotIn("Ciao", prompt)
        self.assertIn("overall_soundscape:\nAmbient sounds.", prompt)

    def test_missing_duplicate_unknown_or_broken_dialogue_rejected(self):
        for text in ["<Subject 1> sits.", "{{dialogue:d1}} {{dialogue:d1}}", "{{dialogue:other}}", "{{dialogue:d1}} {{broken}}"]:
            with self.subTest(text=text), self.assertRaises(StructuralError):
                render(data(), plan().model_copy(update={"narrative_en": text}), "test")

    def test_fabricated_media_or_subject_rejected(self):
        cases = [
            ("<Audio 1>", "non disponibili nel cut (<Audio 1>)"),
            ("<Video 1>", "non disponibili nel cut (<Video 1>)"),
            ("<Subject 99>", "non disponibili nel cut (<Subject 99>)"),
            ("<Subject1>", "formato errato (<Subject1>)"),
            ("<private_tag>", "tag non riconosciuto"),
            ("<d>", "ha scritto tag di dialogo"),
        ]
        for token, message in cases:
            with self.subTest(token=token), self.assertRaises(StructuralError) as error:
                render(data(), plan().model_copy(update={"narrative_en": token + ". {{dialogue:d1}}"}), "test")
            self.assertIn(message, str(error.exception))
            self.assertNotIn("private_tag", str(error.exception))

    def test_character_name_cannot_replace_token(self):
        with self.assertRaises(StructuralError):
            render(data(), plan().model_copy(update={"narrative_en": "Anna sits. {{dialogue:d1}} Marco enters."}), "test")

    def test_speakers_follow_event_order_without_subject_renumbering(self):
        raw = data().model_dump()
        raw["dialogues"].append(dict(id="d2", text="Prima io.", language="Italian", speaker_subject=2, origin="native", confirmed=True))
        p = plan().model_copy(update={"narrative_en": "{{dialogue:d2}} {{dialogue:d1}}"})
        prompt = render(CompileInput.model_validate(raw), p, "test").prompt
        self.assertIn("<Subject 2> (S1) says: <d>[Italian] Prima io.</d>. <Subject 1> (S2) says:", prompt)
        self.assertIn("<Subject 1> (S2) says:", prompt)

    def test_duration_above_limit_not_clamped(self):
        result = render(data(), plan().model_copy(update={"estimated_duration_s": 25.0}), "test")
        self.assertEqual(result.duration_s, 25)
        self.assertFalse(result.confirmation_allowed)
        self.assertTrue(result.issues)

    def test_dialogue_cannot_follow_an_unfinished_introductory_clause(self):
        for text in ["<Subject 1> says {{dialogue:d1}}.", "While {{dialogue:d1}}, <Subject 2> enters."]:
            with self.subTest(text=text), self.assertRaises(StructuralError):
                render(data(), plan().model_copy(update={"narrative_en": text}), "test")

    def test_temporal_introductory_clause_is_kept_before_dialogue(self):
        p = plan().model_copy(update={"narrative_en": "After two seconds, {{dialogue:d1}}"})
        result = render(data(), p, "test")
        self.assertIn("After two seconds, <Subject 1> (S1) says:", result.prompt)

    def test_declared_duration_does_not_hide_long_estimate(self):
        d = data().model_copy(update={"declared_duration_s": 8.0})
        result = render(d, plan().model_copy(update={"estimated_duration_s": 25.0}), "test")
        self.assertFalse(result.confirmation_allowed)
        self.assertEqual(result.duration_origin, "declared")

    def test_clarification_is_not_error(self):
        p = Interpretation(narrative_en=None, estimated_duration_s=None, question="Chi parla?")
        result = render(data(), p, "test")
        self.assertEqual(result.status, "clarification_needed")
        self.assertIsNone(result.prompt)
        self.assertFalse(result.confirmation_allowed)

    def test_no_continuation_invented_without_context(self):
        d = CompileInput(request="Una stanza vuota.")
        p = Interpretation(narrative_en="An empty room.", estimated_duration_s=4.0, question=None)
        result = render(d, p, "test")
        self.assertIn("summary:\nN/A", result.prompt)
        self.assertNotIn("continu", result.prompt.lower())

    def test_synthetic_regression_outputs_pass_current_renderer(self):
        report = json.loads(Path("tests/fixtures/renderer-regression.json").read_text())
        for run in report["runs"]:
            index = next(i for i, c in enumerate(CASES) if c["id"] == run["case"])
            stored = run["result"]
            p = Interpretation.model_validate(stored["interpretation"])
            result = render(data(index).model_copy(update={"ambient_sound": False}), p, stored["input_hash"])
            # Le misure/testi storici restano immutati; il renderer corrente usa
            # il terminatore richiesto e non aggiunge un layer generico di voce.
            current_format = re.sub(r"</d>(?:[ \t]*\.+)?", "</d>.", stored["prompt"])
            current_format = current_format.replace('overall_soundscape:\nOn-screen speech only.', 'overall_soundscape:\nN/A')
            self.assertEqual(result.prompt, current_format)
            self.assertTrue(result.structural_checks_passed)

    def test_continuity_state_only_in_model_narrative(self):
        raw = data().model_dump()
        raw["continuity"] = {"mode": "latent", "declared_state": "Anna è seduta sul divano."}
        result = render(CompileInput.model_validate(raw), plan(), "test")
        self.assertNotIn("<Video", result.prompt)
        self.assertEqual(result.prompt.count("sitting on the sofa"), 1)
        self.assertIn("video continuation", result.prompt)


class ContractTests(unittest.TestCase):
    def test_unavailable_or_unconfirmed_references_rejected(self):
        for mutation in ["unlinked", "unconfirmed", "speaker", "duplicate"]:
            raw = data().model_dump()
            if mutation == "unlinked":
                raw["active_units"][0]["sources"][0]["linked_to_h3"] = False
            elif mutation == "unconfirmed":
                raw["dialogues"][0]["confirmed"] = False
            elif mutation == "speaker":
                raw["dialogues"][0]["speaker_subject"] = 3
            else:
                raw["active_units"].append(raw["active_units"][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                CompileInput.model_validate(raw)

    def test_question_must_not_contain_partial_plan(self):
        with self.assertRaises(ValidationError):
            Interpretation(narrative_en="A person walks.", estimated_duration_s=8.0, question="Chi?")

    def test_minimal_context_excludes_dialogue_words(self):
        context = json.dumps(model_context(data()))
        self.assertNotIn("Sono pronta.", context)
        self.assertIn("dialogue_char_count", context)
        self.assertNotIn("confirmed", context)

    def test_extra_plan_fields_rejected(self):
        with self.assertRaises(ValidationError):
            Interpretation.model_validate({**plan().model_dump(), "camera": "close-up"})

    def test_nonfinite_estimate_rejected(self):
        with self.assertRaises(ValidationError):
            Interpretation(narrative_en="Walk.", estimated_duration_s=float("inf"), question=None)


class ClientTests(unittest.TestCase):
    def run_client(self, reply):
        client = OllamaClient()
        fake = patch.object(client, "_request", side_effect=[{"models": [{"name": "local", "digest": "sha256:test"}]}, reply])
        with fake as request:
            result = client.compile(data(), "local")
        return result, request

    def test_exactly_one_inference_and_no_dialogue_words(self):
        result, request = self.run_client(response())
        self.assertEqual(request.call_count, 2)  # inventario + UNA inferenza
        self.assertEqual(request.call_args_list[1].args[0], "/api/chat")
        payload = request.call_args_list[1].args[1]
        self.assertFalse(payload["think"])
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertNotIn("Sono pronta.", json.dumps(payload))
        self.assertEqual(result.metrics.inference_calls, 1)
        self.assertEqual(result.metrics.digest, "sha256:test")
        self.assertEqual(result.input_hash, input_hash(data()))

    def test_invalid_json_no_retry(self):
        result, request = self.run_client(response("not json"))
        self.assertEqual(result.error_code, "unreadable_json")
        self.assertEqual(request.call_count, 2)
        self.assertFalse(result.confirmation_allowed)

    def test_truncation_distinct_from_missing_data(self):
        for reply, expected in [(response(reason="length"), "truncated_response"),
                                (response('{"narrative_en": "Walk."}'), "missing_essential_data"),
                                (OllamaError("timeout"), "timeout"),
                                (OllamaError("context_exhausted"), "context_exhausted")]:
            result, request = self.run_client(reply)
            self.assertEqual(result.error_code, expected)
            self.assertEqual(result.status, "error")
            self.assertEqual(request.call_count, 2)

    def test_uninstalled_model_has_zero_inferences(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=[]), patch.object(client, "_request") as request:
            result = client.compile(data(), "missing")
        request.assert_not_called()
        self.assertEqual(result.metrics.inference_calls, 0)
        self.assertEqual(result.error_code, "model_unavailable")

    def test_render_and_copy_require_zero_model_calls(self):
        with patch.object(OllamaClient, "_request") as request:
            result = render(data(), plan(), "test")
            copied = result.prompt
        request.assert_not_called()
        self.assertEqual(copied, result.prompt)

    def test_no_cloud_endpoint(self):
        with self.assertRaises(ValueError):
            OllamaClient("https://example.com")

    def test_invalid_message_envelope(self):
        result, request = self.run_client(dict(done=True, done_reason="stop", message=[]))
        self.assertEqual(result.error_code, "invalid_response")
        self.assertEqual(request.call_count, 2)

    def test_service_unreachable_without_inference(self):
        client = OllamaClient()
        with patch.object(client, "models", side_effect=OllamaError("service_unreachable")):
            result = client.compile(data())
        self.assertEqual(result.error_code, "service_unreachable")
        self.assertEqual(result.metrics.inference_calls, 0)

    def test_shipped_cli_example_matches_a01(self):
        sample = Path(__file__).with_name("fixtures").joinpath("a01_input.json").read_text()
        self.assertEqual(CompileInput.model_validate_json(sample), data())


if __name__ == "__main__":
    unittest.main()
