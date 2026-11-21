"""Proposta locale limitata a verbo di parlato + citazione, sempre da confermare."""
import re

QUOTED_SPEECH = re.compile(
    r'\b(?:dice|aggiunge|risponde|chiede|esclama|sussurra)\s*:?\s*'
    r'(?:"(?P<straight>[^"\r\n]+)"|«(?P<italian>[^«»\r\n]+)»|“(?P<curly>[^“”\r\n]+)”)',
    re.IGNORECASE)


def quoted_speech(request):
    return [dict(index=index, start=match.start(), end=match.end(),
                 text=next(value for value in match.groupdict().values() if value is not None),
                 context=request[max(0,match.start()-90):match.end()])
            for index,match in enumerate(QUOTED_SPEECH.finditer(request))]
