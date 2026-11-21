"""Messaggi dei controlli preliminari, riferiti ai campi visibili del cut."""

from app.direction import IMAGE_GUIDE_ROLES, VIDEO_GUIDE_ROLES


def reference_label(kind, item, index):
    number = item.get("subject" if kind == "Subject" else "slot", index + 1)
    label = f"Battuta {item.get('id', index + 1)}" if kind == "Battuta" else f"{kind} {number}"
    name = item.get("name")
    return f"{label} · {name.strip()}" if isinstance(name, str) and name.strip() else label


def rows(data, key):
    value = data.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def enabled_guide(item):
    guidance = item.get("guidance")
    return isinstance(guidance, dict) and guidance.get("enabled")


def completion_issues(data):
    """Elenca insieme le conferme e i campi obbligatori ancora incompleti."""
    if not isinstance(data, dict):
        return []
    issues = []
    request = data.get("request")
    if isinstance(request, str) and not request.strip():
        issues.append("Richiesta — descrivi cosa deve succedere nel cut.")
    units = [u for u in rows(data, 'active_units') if u.get('excluded') is not True]
    excluded_pictures = {p['id']:p for p in rows(data,'pictures') if p.get('excluded') is True and isinstance(p.get('id'),str)}
    used_pictures = set()
    for index, unit in enumerate(units):
        label = reference_label("Subject", unit, index)
        if not unit.get("name"):
            issues.append(f"{label} — compila il nome del Subject.")
        if not unit.get("confirmed"):
            issues.append(f"{label} — spunta «Confermo definizione e associazioni di questo Subject».")
        sources = rows(unit, "sources")
        if not sources:
            issues.append(f"{label} — aggiungi l’associazione a un’immagine oppure al contesto di continuità.")
        if unit.get("definition_mode") == "manual" and blank(unit.get("description_en", "")):
            issues.append(f"{label} — compila la definizione manuale del Subject.")
        scale = unit.get('scale')
        if isinstance(scale, dict):
            if blank(scale.get('measurements')) and blank(scale.get('comparison')):
                issues.append(f'{label} — Dimensioni e scala: indica le misure oppure un confronto dimensionale.')
            if (scale.get('picture_id') or scale.get('reference_subject_id')) and blank(scale.get('comparison')):
                issues.append(f'{label} — descrivi il confronto dimensionale con il Subject o nella Picture selezionata.')
            if scale.get('reference_subject_id') and not any(u.get('subject') == scale.get('reference_subject') for u in units):
                issues.append(f'{label} — il Subject di confronto dimensionale è assente o escluso: aggiungilo al cut oppure scegli un altro riferimento.')
            if isinstance(scale.get('picture_id'), str):
                used_pictures.add(scale['picture_id'])
                if scale['picture_id'] in excluded_pictures:
                    issues.append(f'{label} — il riferimento dimensionale usa una Picture esclusa: riattivala oppure modifica Dimensioni e scala.')
        for number, detail in enumerate(rows(unit, "physical_details"), 1):
            for key, field in [("description", "Descrizione del dettaglio"), ("body_location", "Posizione sul corpo")]:
                if blank(detail.get(key, "")):
                    issues.append(f"{label} · dettaglio fisico {number} — compila «{field}».")
            if isinstance(detail.get("picture_id"), str):
                used_pictures.add(detail["picture_id"])
                if detail['picture_id'] in excluded_pictures:
                    issues.append(f"{label} — un dettaglio fisico usa un’immagine esclusa: riattiva la Picture oppure escludi anche il Subject.")
        for source in sources:
            if source.get("origin", "picture") == "picture":
                if isinstance(source.get("picture_id"), str):
                    used_pictures.add(source["picture_id"])
                    if source['picture_id'] in excluded_pictures:
                        picture = excluded_pictures[source['picture_id']]
                        issues.append(f"{label} — usa Picture {picture.get('slot', '?')}, esclusa da questo cut: riattiva l’immagine oppure escludi anche il Subject.")
                if data.get("pictures") is None and not source.get("linked_to_h3"):
                    issues.append(f"{label} — conferma il collegamento di Picture {source.get('picture_slot')} a H3.")
    for index, picture in enumerate(rows(data, "pictures")):
        if picture.get('excluded') is True: continue
        guide_role = isinstance(picture.get("role"), str) and picture["role"] in IMAGE_GUIDE_ROLES
        guide = guide_role and enabled_guide(picture)
        if (not isinstance(picture.get("id"), str) or picture["id"] not in used_pictures) and not guide:
            continue
        label = reference_label("Picture", picture, index)
        if blank(picture.get("description_en", "")):
            issues.append(f"{label} — compila la descrizione dell’immagine.")
        if not picture.get("confirmed"):
            checkbox = "Ho controllato descrizione, ruolo e mapping della guida" if guide_role else "Ho controllato la descrizione dell’immagine"
            issues.append(f"{label} — spunta «{checkbox}».")
        if not picture.get("linked_to_h3"):
            issues.append(f"{label} — spunta «La collegherò a H3 nello slot Picture indicato».")
        if picture.get("description_language", "English") != "English" and not picture.get("use_original_language"):
            issues.append(f"{label} — traduci la descrizione oppure spunta «Uso questa descrizione nella lingua scelta».")
    characters = {unit["subject"] for unit in units if unit.get("role") == "character" and type(unit.get("subject")) is int}
    for index, dialogue in enumerate(rows(data, "dialogues")):
        label = reference_label("Battuta", dialogue, index)
        if blank(dialogue.get("text", "")):
            issues.append(f"{label} — compila «Parole esatte della battuta».")
        if dialogue.get("delivery", "on_screen") != "narrator" and (type(dialogue.get("speaker_subject")) is not int or dialogue["speaker_subject"] not in characters):
            issues.append(f"{label} — scegli un personaggio attivo nel campo «Chi parla».")
        if not dialogue.get("confirmed"):
            issues.append(f"{label} — spunta «Confermo testo, modalità e parlante».")
    for index, audio in enumerate(rows(data, "audio_references")):
        label = reference_label("Audio", audio, index)
        if not audio.get("media_id"):
            issues.append(f"{label} — carica e associa il file WAV o MP3 alla traccia.")
        if audio.get("role", "speech") != "sound" and (type(audio.get("speaker_subject")) is not int or audio["speaker_subject"] not in characters):
            issues.append(f"{label} — scegli un personaggio attivo nel campo «Parlante dell’audio».")
        if audio.get("role", "speech") == "speech" and blank(audio.get("transcript", "")):
            issues.append(f"{label} — compila «Trascrizione verificata · testo esatto», oppure usa «Trascrivi audio» e applica la proposta.")
        if audio.get("role") == "sound" and blank(audio.get("description_en", "")):
            issues.append(f"{label} — compila «Uso sonoro richiesto · in inglese».")
        if not audio.get("confirmed"):
            issues.append(f"{label} — spunta «Confermo contenuto, segmento e parlante audio».")
        if not audio.get("linked_to_h3"):
            issues.append(f"{label} — spunta la conferma di collegamento del file a H3 nello slot Audio indicato.")
    continuity = data.get("continuity") or {}
    if not isinstance(continuity, dict):
        continuity = {}
    for index, video in enumerate(rows(data, "videos")):
        guide = isinstance(video.get("role"), str) and video["role"] in VIDEO_GUIDE_ROLES and enabled_guide(video)
        if video.get("id") != continuity.get("video_id") and not guide:
            continue
        label = reference_label("Video", video, index)
        if blank(video.get("description_en", "the source clip for continuation")):
            issues.append(f"{label} — compila la descrizione del Video.")
        if not video.get("file_exists"):
            issues.append(f"{label} — spunta «Il file Video esiste nel mio workflow».")
        if not video.get("confirmed"):
            issues.append(f"{label} — spunta «Confermo ruolo, descrizione, durata e mapping del Video».")
        if not video.get("linked_to_h3"):
            issues.append(f"{label} — spunta «Collegherò il file a H3 nello slot Video indicato».")
        if video.get("duration_s") is None:
            issues.append(f"{label} — indica la durata del Video oppure carica il file per misurarla.")
    if issues:
        # Non nascondere un conflitto di slot dietro alle conferme mancanti.
        # Per input completi resta autorevole il controllo strutturale del DTO.
        slots = set()
        for picture in rows(data, "pictures"):
            slot = picture.get("slot")
            if type(slot) is not int:
                continue
            if slot in slots:
                issues.append(f"Picture {slot} — due immagini occupano lo stesso slot. Scegli slot diversi nel catalogo immagini.")
            slots.add(slot)
    return issues


FIELD_LABELS = {
    'excluded': 'Escludi da questo cut',
    'analysis': 'Impostazioni dell’analisi immagine', 'category': 'Categoria di analisi',
    'level': 'Livello di descrizione', 'attribute': 'Attributo o dettaglio da analizzare', 'view': 'Vista dell’immagine',
    "physical_details": "Dettagli fisici e modifiche", "description": "Descrizione del dettaglio",
    "scale": "Dimensioni e scala", "measurements": "Misure", "comparison": "Confronto dimensionale",
    "reference_subject": "Subject di confronto", "reference_subject_id": "Identità del Subject di confronto",
    "body_location": "Posizione sul corpo", "operation": "Operazione sul dettaglio fisico",
    "request": "Richiesta", "name": "Nome", "sources": "Associazioni delle immagini",
    "description_en": "Descrizione", "declared_duration_s": "Durata dichiarata",
    "speaker_subject": "Parlante", "language": "Lingua del parlato", "media_id": "File associato",
    "text": "Parole esatte della battuta", "transcript": "Trascrizione verificata · testo esatto",
    "measured_duration_s": "Durata del file", "sample_rate": "Dati del file audio",
    "sample_count": "Dati del file audio", "channels": "Dati del file audio",
    "segment_start_s": "Inizio sorgente · s", "segment_end_s": "Fine sorgente · s",
    "offset_s": "Inizio nel cut · s", "narrator_voice": "Voce narrante",
    "duration_s": "Durata del Video", "confirmed": "Conferma dei dati del riferimento",
    "linked_to_h3": "Collegamento a H3", "continuity": "Continuità",
    "active_units": "Personaggi e unità della scena", "pictures": "Immagini · Picture",
    "dialogues": "Dialoghi nativi", "audio_references": "Audio e trascrizione",
    "delivery": "Tipo di parlato", "role": "Ruolo", "placement": "Quando applicare la regia",
}


def validation_messages(error, raw=None):
    data = raw.get("input", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        data = {}
    messages = []
    groups = {"active_units": "Subject", "pictures": "Picture", "dialogues": "Battuta",
              "audio_references": "Audio", "videos": "Video"}
    for detail in error.errors(include_input=False, include_url=False):
        if detail["type"] == "input_incomplete":
            messages.extend(detail["ctx"]["issues"])
            continue
        location = detail.get("loc", ())
        prefix = ""
        for index, part in enumerate(location):
            if part in groups and index + 1 < len(location) and isinstance(location[index + 1], int):
                number = location[index + 1]
                items = data.get(part, [])
                if isinstance(items, list) and number < len(items) and isinstance(items[number], dict):
                    prefix = reference_label(groups[part], items[number], number) + " — "
                break
        field = FIELD_LABELS.get(location[-1]) if location else None
        if detail["type"] == "json_invalid":
            message = "I dati inviati non sono leggibili. Riprova il salvataggio."
        elif detail["type"] == "value_error":
            message = detail["msg"].removeprefix("Value error, ")
        elif detail["type"].startswith(("picture_", "video_", "continuity_", "guide_", "direction_", "shot_")):
            message = detail["msg"]
        elif field and detail["type"] in {"missing", "string_too_short"}:
            message = f"Compila il campo «{field}»."
        elif field and detail["type"] in {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}:
            operator, key = {
                "greater_than": ("maggiore di", "gt"), "greater_than_equal": ("maggiore o uguale a", "ge"),
                "less_than": ("minore di", "lt"), "less_than_equal": ("minore o uguale a", "le"),
            }[detail["type"]]
            message = f"«{field}» deve essere {operator} {detail['ctx'][key]}."
        elif field and detail["type"] in {"literal_error", "enum"}:
            message = f"Scegli un’opzione disponibile nel campo «{field}»."
        elif field:
            message = f"Controlla il campo «{field}»."
        else:
            message = "Controlla il valore del campo indicato e la sua selezione."
        messages.append(prefix + message)
    return list(dict.fromkeys(messages))
