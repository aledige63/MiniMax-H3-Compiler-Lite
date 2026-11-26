"""Assemblaggio puro: nessuna inferenza, nessun riordino della narrazione."""
import re
from collections import Counter

from app.domain import CompileInput, CompileResult, Interpretation, definition_picture
from app.direction import CAMERA_EVENT, GUIDE_EVENT, camera_instruction, guide_key, guide_text, guide_opening, subject_motion_bindings
from app.shots import SHOT_EVENT, TAG, shot_cues, shot_instruction
from app.voice import dialogue_voice_sources, voice_direction, voice_phrases, voice_sources, voice_translations
from app.physical import detail_entries, detail_key, detail_phrase
from app.scale import scale_entries, scale_phrase, numeric_values, SCALE_RETENTION

SECTIONS = ("subject_definitions", "summary", "retention_analysis",
            "detailed_description", "overall_soundscape", "non_diegetic_music")
PLACEHOLDER = re.compile(
    r"\{\{dialogue:([a-z][a-z0-9_]*)(?P<off_screen>:off_screen(?::(?P<listener>[1-9][0-9]*))?)?\}\}"
)
# Il terminatore appartiene al formato H3, non alle parole autorevoli del parlato.
# Assorbe un eventuale punto già emesso dal modello, evitando il doppio terminatore.
DIALOGUE_EVENT = re.compile(PLACEHOLDER.pattern + r"(?:[ \t]*\.+)?")
OPENING_STATEMENT = re.compile(
    r'\b(?:(?:the\s+)?(?:scene|shot)\s+(?:opens?|begins?|starts?)|'
    r'at\s+(?:the\s+)?(?:opening|start|beginning)|initially|(?:first|opening|initial)\s+frame)\b',
    re.IGNORECASE,
)


class StructuralError(ValueError):
    pass


def restates_guide_opening(data, text):
    """Riconosce una seconda apertura LLM; non riscrive né interpreta il testo guida."""
    subjects = {f'<Subject {subject}>' for subject, bindings in subject_motion_bindings(data).items()
                if any(guide_opening(reference) for reference, _ in bindings)}
    if not subjects:
        return False
    # Scritte visibili citate sono dati, non istruzioni sull'apertura.
    prose = re.sub(r'''"[^"]*"|“[^”]*”|(?<!\w)'[^']*'(?!\w)|‘[^’]*’''', '', text)
    for sentence in re.split(r'(?<=[.!?])\s+', prose):
        tokens = set(re.findall(r'<Subject [1-9][0-9]*>', sentence))
        if OPENING_STATEMENT.search(sentence) and (not tokens or tokens & subjects):
            return True
    return False


def speech_copy_instruction(audio):
    full_source = audio.segment_start_s == 0 and abs(audio.end_s - audio.measured_duration_s) <= 1 / audio.sample_rate
    scope = "the entire speech recording" if full_source else f"the selected speech segment ({audio.segment_start_s:g}–{audio.end_s:g}s)"
    return (f"Copy {scope} from {audio.token} unchanged, preserving its original voice, words, timing and delivery. "
            "Do not truncate, regenerate or time-stretch the recording.")


def speech_label(dialogue, from_audio=False):
    label = (f"Audio {dialogue.slot}" + (f" · {dialogue.name}" if dialogue.name else "")) if from_audio else f"Battuta {dialogue.id}"
    return label + (f" (Subject {dialogue.speaker_subject})" if dialogue.speaker_subject is not None else " (voce narrante)")


def render(data: CompileInput, plan: Interpretation, input_hash: str) -> CompileResult:
    data = data.effective()
    if plan.question is not None:
        return CompileResult(status="clarification_needed", input_hash=input_hash,
                             interpretation=plan, issues=[plan.question])
    narrative = plan.narrative_en
    assert narrative is not None
    scales = scale_entries(data)
    translated_scales = plan.scales_en or {}
    if set(translated_scales) != set(scales):
        raise StructuralError('Manca la traduzione di Dimensioni e scala oppure il modello ha aggiunto indicazioni non richieste. Ricompila il prompt.')
    for key, translation in translated_scales.items():
        unit = scales[key]
        for original, text in [(unit.scale.measurements, translation.measurements_en), (unit.scale.comparison, translation.comparison_en)]:
            if bool(original.strip()) != bool(text.strip().strip('.')) or any(c in text for c in '<>{}[]\r\n') or any(section + ':' in text for section in SECTIONS):
                raise StructuralError(f'{unit.token} — la traduzione di Dimensioni e scala è incompleta o contiene tag/sezioni. Ricompila il prompt.')
            if numeric_values(original) != numeric_values(text):
                raise StructuralError(f'{unit.token} — la traduzione di Dimensioni e scala ha cambiato le misure numeriche. Ricompila il prompt.')
    details = detail_entries(data)
    translated_details = plan.physical_details_en or {}
    if set(translated_details) != set(details):
        raise StructuralError('Manca la traduzione di un dettaglio fisico oppure il modello ha aggiunto dettagli non richiesti. Ricompila il prompt.')
    for key, translation in translated_details.items():
        for text in (translation.description_en, translation.body_location_en):
            if not text.strip().strip('.') or any(c in text for c in '<>{}[]\r\n') or any(section + ':' in text for section in SECTIONS):
                unit, detail = details[key]
                raise StructuralError(f'{unit.token} · dettaglio {detail.id}: la traduzione deve essere testo semplice su una riga, senza tag o sezioni.')
    camera = data.camera if data.camera and data.camera.active else None
    camera_events = list(CAMERA_EVENT.finditer(narrative))
    if camera and len(camera_events) != 1:
        reason = 'omesso' if not camera_events else 'ripetuto'
        raise StructuralError(f'Il modello ha {reason} le scelte del pannello Regia. Devono comparire una sola volta nella fase richiesta. Ricompila il prompt.')
    if not camera and camera_events:
        raise StructuralError('Il modello ha inserito un evento di regia generale senza scelte nel pannello Regia.')
    if camera:
        event = camera_events[0]
        prefix = narrative[:event.start()].strip()
        if prefix and prefix[-1] not in '.!?' and not prefix.endswith('}}'):
            raise StructuralError('La regia deve iniziare dopo una frase completa.')
        if camera.placement in {'opening', 'throughout'} and prefix:
            raise StructuralError('La regia di apertura o dell’intero cut deve precedere le azioni.')
        if camera.placement in {'during_dialogue', 'after_dialogue'}:
            line = next((match for match in PLACEHOLDER.finditer(narrative) if match[1] == camera.dialogue_id), None)
            if line is None:
                raise StructuralError('Manca la battuta a cui è collegata la regia.')
            if camera.placement == 'during_dialogue':
                between = narrative[event.end():line.start()]
                ordered = event.end() <= line.start()
            else:
                between = narrative[line.end():event.start()]
                ordered = line.end() <= event.start()
            if not ordered or PLACEHOLDER.search(between):
                raise StructuralError('La regia deve seguire la fase richiesta rispetto alla battuta selezionata, senza altre battute interposte.')
    cues = shot_cues(data.request, data.shot_presets, data.declared_duration_s)
    if SHOT_EVENT.findall(narrative) != [cue["id"] for cue in cues]:
        raise StructuralError("Ogni inquadratura richiamata deve comparire una volta, nell’ordine della richiesta.")
    if cues and not narrative.lstrip().startswith("{{shot:s1}}"):
        raise StructuralError("La narrazione deve iniziare con la prima inquadratura richiamata.")
    if cues and TAG.search(narrative):
        raise StructuralError("Il modello deve sostituire i tag delle inquadrature con i marcatori di shot forniti.")
    for event in SHOT_EVENT.finditer(narrative):
        prefix = narrative[:event.start()].rstrip()
        if prefix and prefix[-1] not in ".!?" and not prefix.endswith("}}"):
            raise StructuralError("Ogni cambio d’inquadratura deve iniziare dopo una frase completa.")
    dialogue_events = list(PLACEHOLDER.finditer(narrative))
    events = [event[1] for event in dialogue_events]
    dialogue_by_id = {d.id: d for d in data.dialogues}
    audio_speech = {a.id: a for a in data.audio_references if a.role == "speech"}
    dialogue_by_id.update(audio_speech)
    if sorted(events) != sorted(dialogue_by_id):
        if not dialogue_by_id:
            raise StructuralError('Il modello ha inserito battute non registrate. Usa «Recupera battute dalla richiesta» oppure i campi «Dialoghi nativi», poi ricompila.')
        counts = Counter(events)
        missing = [speech_label(d, key in audio_speech) for key, d in dialogue_by_id.items() if not counts[key]]
        repeated = [f"{speech_label(d, key in audio_speech)} ({counts[key]} occorrenze)"
                    for key, d in dialogue_by_id.items() if counts[key] > 1]
        details = []
        if missing:
            details.append("Il modello ha omesso: " + "; ".join(missing) + ".")
        if repeated:
            details.append("Il modello ha ripetuto: " + "; ".join(repeated) + ".")
        if any(key not in dialogue_by_id for key in events):
            details.append("Il modello ha aggiunto battute non registrate nel cut.")
        raise StructuralError(" ".join(details) + " Ogni battuta registrata deve comparire una sola volta. "
                              "Verifica che la richiesta richiami tutte le battute da conservare; "
                              "rimuovi dal cut quelle non più necessarie, poi ricompila.")
    for event in dialogue_events:
        if event["off_screen"] and event[1] not in audio_speech:
            raise StructuralError("Il modello ha assegnato un evento Audio fuori campo a una battuta nativa. Usa la modalità selezionata nei Dialoghi nativi.")
        if event["listener"]:
            listener = int(event["listener"])
            if listener == audio_speech[event[1]].speaker_subject or not any(
                unit.subject == listener and unit.role == "character" for unit in data.active_units
            ):
                raise StructuralError("L’ascoltatore della voce fuori campo deve essere un personaggio attivo distinto dal parlante.")
        prefix = narrative[:event.start()].rstrip()
        if prefix and prefix[-1] not in ".!?,;" and not prefix.endswith("}}"):
            dialogue = dialogue_by_id[event[1]]
            label = speech_label(dialogue, event[1] in audio_speech)
            raise StructuralError(
                f"{label}: il modello ha inserito il parlato dentro una frase non conclusa, "
                "anziché come frase autonoma. Il programma aggiunge già il parlante e le parole esatte. "
                "Le conferme sono complete: ricompila per ottenere una nuova risposta del modello."
            )
    guides={guide_key(ref,kind):(ref,kind) for kind,refs in [('picture',data.active_picture_guides),('video',data.active_video_guides)] for ref in refs}
    if sorted(GUIDE_EVENT.findall(narrative)) != sorted(guides):
        raise StructuralError('Ogni guida attiva deve comparire una sola volta con il suo segnaposto.')
    for event in GUIDE_EVENT.finditer(narrative):
        prefix=narrative[:event.start()].rstrip()
        if prefix and prefix[-1] not in '.!?' and not prefix.endswith('}}'):
            raise StructuralError('Il segnaposto della guida deve essere una frase completa, non parte di una proposizione.')
    without_events = PLACEHOLDER.sub("", CAMERA_EVENT.sub('', GUIDE_EVENT.sub('', SHOT_EVENT.sub('', narrative))))
    if restates_guide_opening(data, without_events):
        raise StructuralError('Il modello ha aggiunto una seconda apertura per i Subject già regolati dalla guida Video. '
            'L’apertura dichiarata nella guida deve restare l’unica. Ricompila il prompt.')
    if "{{" in without_events or "}}" in without_events:
        raise StructuralError("Segnaposto non valido.")
    known = {u.token for u in data.active_units}
    known |= {f"<Picture {p.slot}>" for p in data.active_pictures}
    known |= {a.token for a in data.audio_references}
    known |= {v.token for v in data.active_videos}
    custom_soundscape = ""
    if data.custom_soundscape:
        custom_soundscape = (plan.soundscape_en or "").strip()
        if not custom_soundscape:
            raise StructuralError("Manca la traduzione dei suoni ambientali personalizzati. Ricompila il prompt.")
        if any(marker in custom_soundscape for marker in ("{{", "}}", "<d>", "</d>", "[Shot", "(S")):
            raise StructuralError("I suoni ambientali tradotti contengono dialoghi o marcatori riservati.")
        if any(section + ":" in custom_soundscape for section in SECTIONS):
            raise StructuralError("I suoni ambientali tradotti contengono intestazioni di sezione.")
        if set(re.findall(r"<[^>]*>", custom_soundscape)) - known:
            raise StructuralError("I suoni ambientali tradotti richiamano riferimenti non disponibili.")
        if any(char in re.sub(r"<[^>]*>", "", custom_soundscape) for char in "<>"):
            raise StructuralError("I suoni ambientali tradotti contengono riferimenti incompleti.")
    elif plan.soundscape_en is not None:
        raise StructuralError("Il modello ha proposto suoni ambientali personalizzati senza una richiesta nel campo dedicato.")
    if any(re.search(rf"(?<!\w){re.escape(u.name)}(?!\w)", without_events, re.IGNORECASE)
           for u in data.active_units if u.role == "character"):
        raise StructuralError("Usare il token Subject al posto del nome del personaggio.")
    tokens = re.findall(r"<[^>]*>", without_events)
    if re.search(r'<d>|</d>', without_events):
        raise StructuralError(
            'Il modello ha scritto tag di dialogo nella descrizione dettagliata. '
            'Deve usare il segnaposto della battuta registrata.'
        )
    unavailable = set(tokens) - known
    if unavailable:
        canonical = sorted(
            token for token in unavailable
            if re.fullmatch(r'<(?:Subject|Picture|Audio|Video) [1-9][0-9]*>', token)
        )
        if canonical:
            detail = ', '.join(canonical[:6])[:160]
            raise StructuralError(
                f'La descrizione dettagliata contiene riferimenti non disponibili nel cut ({detail}). '
                'Il modello deve usare soltanto quelli forniti.'
            )
        malformed = sorted(
            token for token in unavailable
            if re.fullmatch(r'</?(?:Subject|Picture|Audio|Video)\s*\d+\s*>', token, re.IGNORECASE)
        )
        if malformed:
            detail = ', '.join(' '.join(token.split()) for token in malformed[:6])[:160]
            raise StructuralError(
                f'La descrizione dettagliata contiene un token con formato errato ({detail}). '
                'Il modello deve copiare i token forniti senza aggiungere tag di chiusura.'
            )
        raise StructuralError(
            'La descrizione dettagliata contiene un tag non riconosciuto. '
            'Il modello deve usare soltanto i token dei riferimenti forniti.'
        )
    if '<' in re.sub(r'<[^>]*>', '', without_events):
        raise StructuralError('La descrizione dettagliata contiene un riferimento con formato incompleto.')
    if any(v.token in without_events for v in data.active_videos if v.id == data.continuity.video_id):
        raise StructuralError("Il collegamento al Video di continuità viene composto dai dati confermati, non riscritto nella narrazione.")
    if any(s + ":" in narrative for s in SECTIONS) or re.search(r"\[Shot|\(S\d+\)|<d>|\n", narrative):
        raise StructuralError("Il modello deve restituire un solo paragrafo senza sezioni.")
    if plan.summary_en is not None:
        summary_text = plan.summary_en
        if restates_guide_opening(data, summary_text):
            raise StructuralError('Summary: il modello ha aggiunto un’apertura per i Subject già regolati dalla guida Video. '
                'Il riassunto deve descrivere lo sviluppo senza ridefinire l’apertura. Ricompila il prompt.')
        summary_tokens = re.findall(r"<[^>]*>", summary_text)
        if not summary_text.strip():
            raise StructuralError('Summary: il modello ha restituito un riassunto vuoto.')
        if re.search(r'<d>|</d>|\{\{dialogue:',summary_text):
            raise StructuralError('Summary: il modello ha inserito tag o segnaposto di dialogo; il parlato appartiene alla descrizione dettagliata.')
        unavailable = set(summary_tokens) - known
        if unavailable:
            # Mostrare soltanto token canonici, mai tag arbitrari o prosa LLM.
            canonical = sorted(t for t in unavailable if re.fullmatch(r'<(?:Subject|Picture|Audio|Video) [1-9][0-9]*>',t))
            detail = ' ('+', '.join(canonical[:6])+')' if canonical else ''
            raise StructuralError('Summary: il modello ha inserito un riferimento non disponibile o un tag non valido'+detail+'.')
        if '<' in re.sub(r'<[^>]*>','',summary_text):
            raise StructuralError('Summary: il modello ha scritto un riferimento con parentesi o formato incompleti.')
        if re.search(r'[\r\n]',summary_text):
            raise StructuralError('Summary: il modello ha diviso il riassunto su più righe; è richiesto un solo paragrafo.')
        if re.search(r'[{}]',summary_text):
            raise StructuralError('Summary: il modello ha inserito parentesi graffe o segnaposto, non ammessi nel riassunto.')
        if re.search(r'\[Shot|\(S\d+\)',summary_text):
            raise StructuralError('Summary: il modello ha inserito marcatori di shot o speaker, riservati alla descrizione dettagliata.')
        if summary_text.lstrip().startswith('['):
            raise StructuralError('Summary: il modello ha aggiunto un prefisso fra parentesi quadre; la modalità viene già composta dal programma.')
        if any(s + ':' in summary_text for s in SECTIONS):
            raise StructuralError('Summary: il modello ha inserito intestazioni di sezione dentro il riassunto.')
        if any(re.search(rf'(?<!\w){re.escape(u.name)}(?!\w)',summary_text,re.IGNORECASE)
               for u in data.active_units if u.role == 'character'):
            raise StructuralError('Summary: il modello ha usato il nome del personaggio invece del token Subject.')

    speakers: dict[int | str, int] = {}
    translated_tones = plan.voice_tones_en or {}
    expected_tones = voice_translations(data)
    tone_sources_by_id = voice_sources(data)
    missing_tones = set(expected_tones) - set(translated_tones)
    if missing_tones:
        labels = ', '.join(speech_label(source, hasattr(source, 'slot')) for id, source in tone_sources_by_id.items() if id in missing_tones)
        raise StructuralError(f'{labels}: manca la traduzione del campo «Tono e modalità della voce». Ricompila il prompt.')
    if set(translated_tones) - set(expected_tones):
        raise StructuralError('La traduzione del tono è associata a una battuta o a un Audio che non la richiede. Ricompila il prompt.')
    for source_id, phrase in translated_tones.items():
        if (not phrase.strip() or len(phrase) > 500 or any(char in phrase for char in '<>{}[]\r\n')
                or phrase.rstrip().endswith(('.', '!', '?', ':', ';'))
                or re.search(r'\(S\d+\)|\b(?:' + '|'.join(SECTIONS) + r'):', phrase)):
            source = tone_sources_by_id[source_id]
            label = speech_label(source, hasattr(source, 'slot'))
            raise StructuralError(f'{label}: la traduzione del tono deve essere una breve espressione, senza dialoghi o marcatori. Ricompila.')

    def speech(match):
        d = dialogue_by_id[match[1]]
        copy_instruction = ""
        lip_sync_cue = ""
        if match[1] in audio_speech:
            tone_sources = [d] if voice_direction(d) else []
            key = d.speaker_subject
            label, verb = f"<Subject {key}>", "says"
            timing, text = f"At {d.offset_s:g}s, ", d.transcript
            if d.mode == "copy":
                copy_instruction = speech_copy_instruction(d) + " "
            if match["off_screen"]:
                verb = "says in an off-screen voiceover"
            elif d.mode == "copy":
                target_end = d.offset_s + d.useful_duration_s
                lip_sync_cue = (f"From {d.offset_s:g}s to {target_end:g}s, {label}'s natural lip movements match "
                                f"the audible words in {d.token}. ")
            else:
                lip_sync_cue = f"{label}'s natural lip movements match the words of the new performance. "
        else:
            tone_sources = dialogue_voice_sources(data, d)
            label = d.speaker_label
            key = label if d.delivery == "narrator" else d.speaker_subject
            verb = "says" if d.delivery == "on_screen" else "says in an off-screen voiceover"
            timing, text = "", d.text
        number = speakers.setdefault(key, len(speakers) + 1)
        visibility = ", who remains outside the frame," if match["off_screen"] else ""
        listener_cue = ""
        if match["listener"]:
            listener_cue = f"<Subject {match['listener']}> listens with lips completely closed throughout the off-screen line. "
        phrases = [phrase for audio in tone_sources for phrase in voice_phrases(audio, translated_tones)]
        tone = ', ' + ', '.join(phrases) if phrases else ''
        return (listener_cue + copy_instruction + lip_sync_cue + timing + f"{label} (S{number}){visibility} {verb}{tone}: "
                f"<d>[{d.language}] {text}</d>.")

    narrative = DIALOGUE_EVENT.sub(speech, narrative)
    narrative = CAMERA_EVENT.sub(lambda match: camera_instruction(camera), narrative)
    narrative = GUIDE_EVENT.sub(lambda match:guide_text(*guides[match[1]]),narrative)
    continuation=next((v for v in data.active_videos if v.id==data.continuity.video_id),None)
    if continuation:
        instruction = f"The video continues from {continuation.token}. "
        narrative = narrative.replace("{{shot:s1}}", "{{shot:s1}} " + instruction, 1) if cues else instruction + narrative
    shot_events = list(SHOT_EVENT.finditer(narrative))
    shot_contents = [
        narrative[event.end():shot_events[index+1].start() if index+1 < len(shot_events) else len(narrative)]
        for index, event in enumerate(shot_events)
    ] if cues else [narrative]

    def appearances(token):
        labels = [f"[Shot {index+1}]" for index, text in enumerate(shot_contents) if token in text]
        return ", ".join(labels) if labels else "no explicit appearance"

    detailed = SHOT_EVENT.sub(
        lambda match: shot_instruction(cues[int(match[1][1:])-1], int(match[1][1:])-1), narrative
    ) if cues else "[Shot 1] " + narrative
    definitions, retention = [], []
    motion_bindings = subject_motion_bindings(data)
    for u in data.active_units:
        description = data.description_for(u).rstrip('.')
        picture_sources = [s for s in u.sources if s.origin == 'picture']
        context_attrs = list(dict.fromkeys(s.attribute for s in u.sources if s.origin == 'context'))
        context_source = f"the continuity context of {continuation.token}" if continuation else "the declared continuity context"
        if not picture_sources:
            definitions.append(f"{u.token} is {description}, with {' and '.join(context_attrs)} from {context_source}.")
        elif data.pictures is None:
            phrases = [f"{s.attribute} from <Picture {data.slot_for(s)}>" for s in picture_sources]
            if context_attrs: phrases.append(f"{' and '.join(context_attrs)} from {context_source}")
            definitions.append(f"{u.token} is {description}, with {', '.join(phrases)}.")
        else:
            primary_picture = definition_picture(u.model_dump(), [p.model_dump() for p in data.pictures])
            primary = next((s for s in picture_sources if primary_picture and s.picture_id == primary_picture['id']), None)
            definition = f"{u.token} is {description}" + (f" from <Picture {data.slot_for(primary)}>" if primary else "")
            clothing, other = [], []
            for source in picture_sources:
                if source is primary:
                    continue
                picture = data.picture_for(source)
                if source.attribute in {"outfit", "shoes"}:
                    clothing.append(f"{picture.description_en.rstrip('.')} from <Picture {picture.slot}>")
                else:
                    other.append(f"{source.attribute} from <Picture {picture.slot}>")
            if clothing:
                definition += ", wearing " + " and ".join(clothing)
            if other:
                definition += ", with " + ", ".join(other)
            if context_attrs:
                definition += f", with {' and '.join(context_attrs)} from {context_source}"
            definitions.append(definition + ".")
        attrs = list(dict.fromkeys(s.attribute for s in u.sources))
        location = appearances(u.token) if cues else "[Shot 1]"
        if u.physical_details:
            phrases = [detail_phrase(data, detail, translated_details[detail_key(u, detail)]) for detail in u.physical_details]
            definitions[-1] = definitions[-1].rstrip('.') + '; the following physical details take precedence over the source appearance: ' + '; '.join(phrases) + '.'
            changed = any(detail.origin != 'context' for detail in u.physical_details)
            marker = 'partially_preserved' if changed else 'fully_preserved'
            scope = 'the supplied identity and other attributes are retained except for the declared physical changes' if changed else 'the supplied identity, attributes and physical details from the declared continuity context are retained'
            retention.append(f"{u.token} (appears in {location}): {marker} - {scope}; " + '; '.join(phrases) + '.')
        else:
            retention.append(f"{u.token} (appears in {location}): fully_preserved - supplied {' and '.join(attrs)}.")
        if u.scale:
            phrase = scale_phrase(data, u, translated_scales[f's{u.subject}'])
            definitions[-1] += ' Declared ' + phrase + '.'
            retention[-1] += ' Preserve ' + phrase + '. ' + SCALE_RETENTION
        for reference, mapping in motion_bindings.get(u.subject, []):
            proxy = mapping.figure.strip()
            definitions[-1] += (f' The position, orientation and motion of {u.token} follow the "{proxy}" proxy in {reference.token}; '
                'its appearance comes from the Subject references defined above.')
            retention[-1] += f' Placement, orientation and motion follow the "{proxy}" proxy in {reference.token}.'
    for video in data.active_videos:
        role={'continuation':'video-continuation source','camera':'camera-movement guide','subject_motion':'Subject-motion guide','camera_and_subject_motion':'combined camera and Subject-motion guide'}[video.role]
        definitions.append(f"{video.token} is {video.description_en}, used as the {role} ({video.duration_s:g}s).")
        scope='declared continuation relationship; its audio is not reused' if video.role=='continuation' else 'only the declared guide role and mapped motion; no appearance, background or audio transfer'
        retention.append(f"{video.token} ({'continuation source' if video.role=='continuation' else role}): fully_preserved - {scope}.")
    for picture in data.active_picture_guides:
        role=picture.role.replace('_',' ')
        definitions.append(f'<Picture {picture.slot}> is the {role} guide: {picture.description_en.rstrip(".")}.')
        marker='weak_reference' if picture.role in {'style','composition_previz'} else 'fully_preserved'
        location = appearances(f"<Picture {picture.slot}>") if cues else "[Shot 1]"
        retention.append(f'<Picture {picture.slot}> ({location} {role}): {marker} - the declared guide role and mapping.')
    measured_end = max((a.offset_s + a.useful_duration_s for a in data.audio_references if a.role != "voice"), default=0)
    duration = data.declared_duration_s if data.declared_duration_s is not None else max(plan.estimated_duration_s, measured_end)
    duration_origin = "declared" if data.declared_duration_s is not None else "measured" if measured_end >= plan.estimated_duration_s else "estimated"
    for audio in data.audio_references:
        speaker = f" for <Subject {audio.speaker_subject}> (S{speakers[audio.speaker_subject]})" if audio.speaker_subject in speakers else ""
        purpose = "voice-timbre reference; source words are not reused" if audio.role == "voice" else f"{audio.role} {'recording to copy' if audio.mode == 'copy' else 'reference for a new performance'}"
        detail = f"; requested sound: {audio.description_en.rstrip('.')}" if audio.role == "sound" else ""
        definitions.append(f"{audio.token} is the {purpose}{speaker}, source segment {audio.segment_start_s:g}–{audio.end_s:g}s, target start {audio.offset_s:g}s{detail}.")
        entire = (audio.exclusive_full_track and not data.ambient_sound and not data.custom_soundscape and len(data.audio_references) == 1 and not data.dialogues and audio.role != "voice"
                  and audio.segment_start_s == 0 and abs(audio.end_s - audio.measured_duration_s) <= 1 / audio.sample_rate
                  and audio.offset_s == 0 and abs(duration - audio.measured_duration_s) <= 1 / audio.sample_rate)
        marker = ("fully_copy" if entire else "partially_copy") if audio.mode == "copy" else "reference"
        if cues and audio.role == "voice":
            labels = [f"[Shot {i+1}]" for i, text in enumerate(shot_contents) if f"<Subject {audio.speaker_subject}> (S" in text]
        else:
            labels = [f"[Shot {i+1}]" for i, cue in enumerate(cues)
                      if cue["at_s"] < audio.offset_s + audio.useful_duration_s
                      and (cues[i+1]["at_s"] if i+1 < len(cues) else duration) > audio.offset_s]
        location = ", ".join(labels) or ("no explicit appearance" if cues else "[Shot 1]")
        explanation = speech_copy_instruction(audio) if audio.role == "speech" and audio.mode == "copy" else f"supplied {audio.role} segment."
        retention.append(f"{audio.token} (appears in {location}): {marker} - {explanation}")
    modes = ["reference generation"] if any(s.origin == 'picture' for u in data.active_units for s in u.sources) or any(d.picture_id for u in data.active_units for d in u.physical_details) or any(u.scale and u.scale.picture_id for u in data.active_units) or data.active_video_guides or any(p.role!='frame_anchor' for p in data.active_picture_guides) else []
    if any(p.role=='frame_anchor' for p in data.active_picture_guides):modes.append('keyframe completion')
    if data.continuity.mode != "none":
        modes.append("video continuation")
    if data.audio_references:
        if any(a.mode == "copy" for a in data.audio_references): modes.append("audio reuse")
        if any(a.mode == "reference" for a in data.audio_references): modes.append("audio reference")
    summary = (f"[{' + '.join(modes)}] " if modes else "")
    if plan.summary_en is not None:
        summary += plan.summary_en
    else:
        # Compatibilità dei vecchi piani nei test e negli strumenti; le nuove
        # risposte Ollama richiedono summary_en e non arrivano a questo ramo.
        summary += ("Active references: " + "; ".join(f"{u.token} ({u.role})" for u in data.active_units) + "."
                    if data.active_units else ("Continue from the declared context." if data.continuity.mode != "none" else "Audio inputs as specified below." if data.audio_references else "N/A"))
        if data.audio_references:
            summary += " Audio: " + "; ".join(f"{a.token} ({a.role}, {a.mode})" for a in data.audio_references) + "."
    soundscape = "N/A"
    if data.audio_references:
        soundscape = " ".join(
            f"{'Copy' if a.mode == 'copy' else 'Reference'} {a.token} for supplied {a.role}."
            for a in data.audio_references if not (a.mode == "copy" and a.role == "speech")) or "N/A"
    if data.ambient_sound:
        soundscape = "Ambient sounds." + (" " + soundscape if soundscape != "N/A" else "")
    elif custom_soundscape:
        soundscape = custom_soundscape + (" " + soundscape if soundscape != "N/A" else "")
    contents = ("\n".join(definitions) or "N/A", summary, "\n".join(retention) or "N/A",
                detailed, soundscape, "N/A")
    prompt = "\n\n".join(f"{key}:\n{value}" for key, value in zip(SECTIONS, contents))
    issues = []
    if cues and cues[-1]["at_s"] >= duration:
        issues.append("L’ultimo cambio d’inquadratura deve precedere la fine della durata utile del cut.")
    if any(p.role=='frame_anchor' and p.guidance.anchor=='keyframe' and p.guidance.at_s>=duration for p in data.active_picture_guides):
        issues.append('Il keyframe deve cadere prima della fine della durata utile del cut.')
    if not 4 <= duration <= 15 or plan.estimated_duration_s > 15:
        issues.append("Durata da rivedere: il cut utile deve essere fra 4 e 15 secondi; suddividere se necessario.")
    return CompileResult(status="proposal", input_hash=input_hash, interpretation=plan,
                         prompt=prompt, duration_s=duration,
                         duration_origin=duration_origin,
                         structural_checks_passed=not issues, confirmation_allowed=not issues, issues=issues)
