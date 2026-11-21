import argparse
from pathlib import Path

from app.domain import CompileInput
from app.interpreter import OllamaClient


def main():
    parser = argparse.ArgumentParser(description="Compila un cut Ref2VA con una sola chiamata a Ollama locale.")
    parser.add_argument("input", type=Path, help="DTO CompileInput JSON")
    parser.add_argument("--model", required=True, help="Nome esatto del modello Ollama installato da usare")
    args = parser.parse_args()
    data = CompileInput.model_validate_json(args.input.read_text(encoding='utf-8'))
    result = OllamaClient().compile(data, args.model)
    # Output esplicito verso l'utente; nessun log persistente del testo.
    print(result.model_dump_json(indent=2))
    return 1 if result.status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
