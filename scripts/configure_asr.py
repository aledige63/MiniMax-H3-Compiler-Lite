"""Configurazione esplicita di un modello Whisper già presente sul Mac, senza download."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Configura l’ASR opzionale con un modello MLX locale esistente')
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parent.parent / 'data')
    args = parser.parse_args()
    model = args.model_dir.expanduser().resolve()
    if not (model / 'config.json').is_file() or not any((model / file).is_file() for file in ('weights.npz','weights.safetensors')):
        parser.error('Il percorso deve contenere config.json e i pesi Whisper MLX già disponibili. Nessun modello verrà scaricato.')
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = args.data_dir / 'asr.json'; temporary = target.with_suffix('.tmp')
    with temporary.open('w') as file:
        os.chmod(temporary,0o600); json.dump({'model_dir':str(model)},file); file.flush(); os.fsync(file.fileno())
    os.replace(temporary,target)
    print('Percorso ASR salvato. Installa le dipendenze opzionali se mancanti e aggiorna la pagina; testo e vision restano indipendenti.')


if __name__ == '__main__': main()
