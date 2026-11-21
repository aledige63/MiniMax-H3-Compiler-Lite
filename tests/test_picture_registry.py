import unittest

from pydantic import ValidationError

from app.compiler import render
from app.domain import CompileInput, Interpretation
from app.interpreter import model_context


def catalogue_input():
    return {"request": "<Subject 1> guarda la camera.",
            "pictures": [
                {"id": "face", "slot": 1, "name": "Ann", "role": "identity", "description_en": "a young woman with long brown hair", "confirmed": True, "linked_to_h3": True},
                {"id": "skirt", "slot": 2, "name": "Gonna", "role": "outfit", "description_en": "a black miniskirt", "confirmed": True, "linked_to_h3": True},
            ], "active_units": [{"subject": 1, "name": "Ann", "role": "character", "description_en": "Ann", "confirmed": True,
                                  "sources": [{"picture_id": "face", "attribute": "identity"}, {"picture_id": "skirt", "attribute": "outfit"}]}]}


def plan():
    return Interpretation(narrative_en="<Subject 1> looks at the camera.", estimated_duration_s=4.0, question=None)


class PictureRegistryTests(unittest.TestCase):
    def test_ann_and_skirt_are_one_subject_with_two_pictures(self):
        data = CompileInput.model_validate(catalogue_input())
        prompt = render(data, plan(), "example").prompt
        self.assertIn("<Subject 1> is a young woman with long brown hair from <Picture 1>, wearing a black miniskirt from <Picture 2>.", prompt)
        self.assertNotIn("<Subject 2>", prompt)
        self.assertEqual(prompt.count("fully_preserved"), 1)
        self.assertNotIn("<Picture 2> (appears", prompt)

    def test_one_picture_can_explicitly_define_two_subjects(self):
        raw = catalogue_input()
        raw["active_units"].append({"subject": 2, "name": "Beth", "role": "character", "description_en": "Beth", "definition_mode": "manual", "confirmed": True,
                                    "sources": [{"picture_id": "face", "attribute": "identity"}]})
        data = CompileInput.model_validate(raw)
        prompt = render(data, plan(), "shared").prompt
        self.assertIn("<Subject 2> is Beth from <Picture 1>.", prompt)
        self.assertEqual(len(data.active_pictures), 2)

    def test_two_distinct_pictures_cannot_occupy_one_slot(self):
        raw = catalogue_input()
        raw["pictures"][1]["slot"] = 1
        with self.assertRaises(ValidationError) as raised:
            CompileInput.model_validate(raw)
        self.assertEqual(raised.exception.errors()[0]["type"], "picture_slot_conflict")

    def test_unused_picture_has_no_definition_or_model_context(self):
        raw = catalogue_input()
        raw["pictures"].append({"id": "unused", "slot": 9, "description_en": "UNUSED_MARKER"})
        data = CompileInput.model_validate(raw)
        self.assertNotIn("UNUSED_MARKER", str(model_context(data)))
        self.assertNotIn("<Picture 9>", render(data, plan(), "unused").prompt)
        self.assertEqual(len(data.active_units), 1)

    def test_slot_change_follows_picture_id_without_rebinding(self):
        raw = catalogue_input()
        raw["pictures"][1]["slot"] = 7
        prompt = render(CompileInput.model_validate(raw), plan(), "moved").prompt
        self.assertIn("wearing a black miniskirt from <Picture 7>", prompt)
        self.assertNotIn("<Picture 2>", prompt)

    def test_missing_or_unconfirmed_used_picture_blocks_compile(self):
        for change in ["missing", "unconfirmed", "unlinked"]:
            raw = catalogue_input()
            if change == "missing":
                raw["pictures"].pop()
            elif change == "unconfirmed":
                raw["pictures"][1]["confirmed"] = False
            else:
                raw["pictures"][1]["linked_to_h3"] = False
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CompileInput.model_validate(raw)

    def test_repeated_binding_is_rejected_but_multiple_attributes_are_explicit(self):
        raw = catalogue_input()
        raw["active_units"][0]["sources"].append({"picture_id": "face", "attribute": "identity"})
        with self.assertRaises(ValidationError):
            CompileInput.model_validate(raw)
        raw["active_units"][0]["sources"][-1]["attribute"] = "appearance"
        CompileInput.model_validate(raw)

    def test_outfit_cannot_be_implicitly_assigned_to_object_subject(self):
        raw = catalogue_input()
        raw["active_units"][0]["role"] = "object"
        with self.assertRaises(ValidationError) as raised:
            CompileInput.model_validate(raw)
        self.assertEqual(raised.exception.errors()[0]["type"], "picture_role_conflict")


if __name__ == "__main__":
    unittest.main()
