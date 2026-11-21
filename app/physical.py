"""Associazioni e frasi dei dettagli fisici, senza inferenze o slot memorizzati."""


def unit_picture_ids(unit):
    """Dipendenze fotografiche anche di una bozza incompleta."""
    ids = [item['picture_id'] for key in ('sources', 'physical_details')
        for item in (unit[key] if isinstance(unit.get(key), list) else [])
        if isinstance(item, dict) and isinstance(item.get('picture_id'), str)]
    scale = unit.get('scale')
    if isinstance(scale, dict) and isinstance(scale.get('picture_id'), str):
        ids.append(scale['picture_id'])
    return list(dict.fromkeys(ids))


def detail_content(unit):
    return [{k: v for k, v in detail.items() if k not in {'origin', 'picture_id'}}
            for detail in unit.get('physical_details', []) if isinstance(detail, dict)]


def detail_key(unit, detail):
    return f's{unit.subject}_{detail.id}'


def detail_entries(data):
    return {detail_key(unit, detail): (unit, detail) for unit in data.included_units for detail in unit.physical_details}


def detail_phrase(data, detail, translation):
    description = translation.description_en.strip().rstrip('.')
    location = translation.body_location_en.strip().rstrip('.')
    if detail.picture_id:
        picture = next(p for p in data.pictures if p.id == detail.picture_id)
        description += f' from <Picture {picture.slot}>'
    if detail.operation == 'replace':
        return f'the {location} is replaced by {description}'
    if detail.operation == 'modify':
        return f'the {location} is modified as follows: {description}'
    return f'{description} is added at the {location}'
