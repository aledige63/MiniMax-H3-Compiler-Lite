"""Scelte vocali condivise con l'interfaccia e applicate dal renderer."""
import json
from pathlib import Path

OPTIONS = json.loads(Path(__file__).with_name('static').joinpath('voice-options.json').read_text(encoding='utf-8'))
EMOTIONS = {item['value']: item['en'] for item in OPTIONS['emotions']}
MODES = {item['value']: item['en'] for item in OPTIONS['modes']}


def voice_direction(audio):
    return audio.mode == 'reference' and audio.role in {'speech', 'voice'}


def validate_voice_fields(item):
    if item.voice_emotion and item.voice_emotion not in EMOTIONS:
        raise ValueError('Scegli un’emozione dal menu della voce.')
    if item.voice_mode and item.voice_mode not in MODES:
        raise ValueError('Scegli una modalità dal menu della voce.')
    if any(char in item.voice_tone for char in '<>{}\r\n'):
        raise ValueError('Il tono della voce deve essere testo semplice su una riga.')


def dialogue_voice_sources(data, dialogue):
    if dialogue.voice_tone.strip() or dialogue.voice_emotion or dialogue.voice_mode:
        return [dialogue]
    return [audio for audio in data.audio_references if audio.role == 'voice' and voice_direction(audio)
            and dialogue.delivery != 'narrator' and audio.speaker_subject == dialogue.speaker_subject]


def voice_sources(data):
    sources = [audio for audio in data.audio_references if audio.role == 'speech' and voice_direction(audio)]
    for dialogue in data.dialogues:
        sources.extend(dialogue_voice_sources(data, dialogue))
    return {source.id: source for source in sources}


def voice_translations(data):
    return {id: source.voice_tone.strip() for id, source in voice_sources(data).items() if source.voice_tone.strip()}


def voice_phrases(source, translated):
    return [phrase for phrase in (EMOTIONS.get(source.voice_emotion), MODES.get(source.voice_mode),
            translated.get(source.id)) if phrase]
