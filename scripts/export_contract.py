import argparse
import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

import inspect
import app.contracts as web_contracts

from app.domain import (AudioReference, CompileCommand, CompileInput, CompileResult, ConfirmCommand,
                        CurrentInterpretation, Interpretation, ManualPromptCommand, PictureReference, VideoReference)
from app.contracts import (AddItemCommand, AddSourceCommand, CutView, DraftCommand, HealthView,
                           JobView, ModelView, PromptVersion, WebCompileCommand,
                           WebManualPromptCommand)
from app.narrative import NarrativePlan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    models = [AudioReference, VideoReference, CompileInput, Interpretation, CurrentInterpretation, NarrativePlan, CompileResult, CompileCommand, ConfirmCommand,
              ManualPromptCommand, PictureReference, DraftCommand, AddItemCommand, AddSourceCommand, WebCompileCommand,
              WebManualPromptCommand, PromptVersion, JobView, CutView, HealthView, ModelView]
    models += [model for _, model in inspect.getmembers(web_contracts, inspect.isclass) if model.__module__ == web_contracts.__name__ and model not in models]
    _, schema = models_json_schema([(m, "validation") for m in models], title="MiniMax H3 Lite M6")
    output = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    target = Path("docs/contracts.schema.json")
    if args.check:
        if target.read_text(encoding='utf-8') != output:
            raise SystemExit("Schema non aggiornato: eseguire python -m scripts.export_contract")
    else:
        target.write_text(output, encoding='utf-8', newline='\n')


if __name__ == "__main__":
    main()
