import unittest

from app.compiler import render
from app.domain import CompileInput, CurrentInterpretation
from test_m0 import data


class AudioCopyTests(unittest.TestCase):
    def inputs(self):
        raw = data().model_dump()
        raw.update(dialogues=[], ambient_sound=False, soundscape_text='Traffico soffuso e bussare alla porta.')
        base = dict(media_id='fixture', measured_duration_s=4.0, sample_rate=8000, sample_count=32000,
            channels=1, mode='copy', role='speech', confirmed=True, linked_to_h3=True, exclusive_full_track=True)
        raw['audio_references'] = [dict(base, id='a8', slot=2, speaker_subject=2, transcript='  Apri, per favore!  '),
                                   dict(base, id='a9', slot=1, speaker_subject=1, transcript='Un attimo.')]
        return raw

    def plan(self):
        return CurrentInterpretation(narrative_en='{{dialogue:a8}} <Subject 1> looks left. {{dialogue:a9}} Then, <Subject 1> smiles.',
            summary_en='<Subject 2> and <Subject 1> exchange lines copied from <Audio 2> and <Audio 1>.',
            soundscape_en='Soft traffic noise and a knock at the door.', estimated_duration_s=8.0, question=None)

    def test_both_complete_recordings_are_explicitly_copied_unchanged_with_partial_retention(self):
        inputs = CompileInput.model_validate(self.inputs())
        prompt = render(inputs, self.plan(), 'whole-recordings-in-mix').prompt
        retention = prompt.split('retention_analysis:\n')[1].split('\n\ndetailed_description:')[0]
        detailed = prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        soundscape = prompt.split('overall_soundscape:\n')[1].split('\n\n')[0]
        for audio in inputs.audio_references:
            instruction = f'Copy the entire speech recording from {audio.token} unchanged, preserving its original voice, words, timing and delivery.'
            self.assertIn(f'{audio.token} (appears in [Shot 1]): partially_copy - {instruction}', retention)
            self.assertLess(detailed.index(instruction), detailed.index(f'<d>[Italian] {audio.transcript}</d>.'))
            self.assertIn('Do not truncate, regenerate or time-stretch the recording.', detailed)
        self.assertNotIn('fully_copy', retention)
        self.assertEqual(detailed.count('</d>.'), 2)
        self.assertIn('</d>. Then, <Subject 1> smiles.', detailed)
        self.assertEqual(soundscape, 'Soft traffic noise and a knock at the door.')

    def test_explicitly_selected_segment_is_not_claimed_to_be_the_entire_recording(self):
        raw = self.inputs()
        raw['audio_references'][1].update(segment_start_s=1.0, segment_end_s=2.5, offset_s=4.25)
        prompt = render(CompileInput.model_validate(raw), self.plan(), 'selected-segment').prompt
        self.assertIn('Copy the selected speech segment (1–2.5s) from <Audio 1> unchanged', prompt)
        self.assertNotIn('Copy the entire speech recording from <Audio 1>', prompt)
        detailed = prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertIn("From 0s to 4s, <Subject 2>'s natural lip movements match the audible words in <Audio 2>.", detailed)
        self.assertIn("From 4.25s to 5.75s, <Subject 1>'s natural lip movements match the audible words in <Audio 1>. "
                      "At 4.25s, <Subject 1> (S2) says: <d>[Italian] Un attimo.</d>. Then, <Subject 1> smiles.", detailed)

    def test_reference_mode_does_not_promise_copy_of_original_signal(self):
        raw = self.inputs()
        for audio in raw['audio_references']:
            audio.update(mode='reference', exclusive_full_track=False)
        prompt = render(CompileInput.model_validate(raw), self.plan(), 'reference-performance').prompt
        self.assertNotIn('Copy the entire speech recording', prompt)
        self.assertIn('reference for a new performance', prompt)
        self.assertIn(': reference - supplied speech segment.', prompt)
        self.assertIn("<Subject 2>'s natural lip movements match the words of the new performance.", prompt)
        self.assertNotIn('the audible words in <Audio 2>', prompt)

    def test_sole_complete_soundtrack_keeps_fully_copy_when_all_conditions_are_met(self):
        raw = self.inputs()
        raw.update(soundscape_text='', declared_duration_s=4.0, audio_references=raw['audio_references'][:1])
        plan = self.plan().model_copy(update=dict(narrative_en='{{dialogue:a8}}', summary_en='<Subject 2> speaks.',
            soundscape_en=None, estimated_duration_s=4.0))
        prompt = render(CompileInput.model_validate(raw), plan, 'sole-soundtrack').prompt
        self.assertIn(': fully_copy - Copy the entire speech recording from <Audio 2> unchanged', prompt)
        self.assertIn('overall_soundscape:\nN/A\n\n', prompt)
