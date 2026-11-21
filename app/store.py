"""Errori pubblici e serializzazione deterministica dell'archivio."""
import hashlib
import json


class StoreError(Exception):
    def __init__(self, code, message, status=409, current_revision=None, issues=None):
        self.code, self.message, self.status = code, message, status
        self.current_revision = current_revision
        self.issues = issues


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dto(model, value):
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))
