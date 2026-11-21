"""Scala dichiarata dall'utente: identità stabili e frasi assemblate dal programma."""
import re


def scale_entries(data):
    return {f's{unit.subject}': unit for unit in data.included_units if unit.scale}


def canonical_scale(unit):
    value = unit.get('scale')
    if not isinstance(value, dict):
        return value
    # Il numero locale non entra nella libreria condivisa fra scene.
    return {key: item for key, item in value.items()
            if key != 'reference_subject' and item not in (None, '')}


def resolve_scale_subject(unit, numbers):
    scale = unit.get('scale')
    if isinstance(scale, dict) and scale.get('reference_subject_id'):
        scale['reference_subject'] = numbers.get(scale['reference_subject_id'])


def numeric_values(text):
    return re.findall(r'\d+(?:\.\d+)?', text.replace(',', '.'))


def scale_phrase(data, unit, translation):
    scale = unit.scale
    phrases = []
    if scale.measurements.strip():
        phrases.append('physical dimensions: ' + translation.measurements_en.strip().rstrip('.'))
    if scale.comparison.strip():
        target = f' relative to <Subject {scale.reference_subject}>' if scale.reference_subject is not None else ''
        picture = next((p for p in data.pictures or [] if p.id == scale.picture_id), None)
        source = f' as shown in <Picture {picture.slot}>' if picture else ''
        phrases.append(f'scale{target}{source}: ' + translation.comparison_en.strip().rstrip('.'))
    if scale.picture_id:
        phrases.append('the scale reference supplies only the stated dimensional relationship; other people and scene content are not transferred by this scale reference')
    return '; '.join(phrases)


SCALE_RETENTION = ('Maintain the declared physical dimensions and relative proportions throughout the cut; '
                   'apparent size changes naturally with distance and perspective.')
