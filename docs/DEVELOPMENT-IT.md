# Sviluppo dei sorgenti

Richiede Python 3.12. Eseguire dalla radice:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m scripts.export_contract --check
.venv/bin/python -m pip check
node --test tests/*.mjs
git diff --check
```

Su Windows usare `py -3.12 -m venv .venv` e sostituire `.venv/bin/python` con
`.venv\Scripts\python.exe -X utf8`. Node serve soltanto ai test JavaScript.
I test automatici usano fixture sintetiche, senza modelli o servizi AI reali.
Per l'avvio manuale: `python -m scripts.serve --port 8767 --data-dir data-prova`.
I comandi Python vanno eseguiti con l'interprete della virtualenv attiva.

## Ricetta autonoma

`python -m scripts.build_packages --output dist/1.1.0` crea lo ZIP stabile
Windows x64. Non servono Git, vecchi tag o vecchi ZIP. L’allowlist è
`packaging/files.json`; `packaging/runtime-reference.json` controlla gli hash
applicativi e degli avvii. Tag pubblico e hash runtime identificano i file; il commit pubblico esatto è nel VERIFICA.json di consegna. Versione
1.1.0, tag stabile v1.1.0. Aggiornare il riferimento solo per modifiche intenzionali.


Gli script smoke/benchmark effettuano inferenze solo se avviati esplicitamente.
Scegliere i modelli installati con `--model`; m3 richiede il modello vision e
m5 richiede `--vision-model` quando si abilita `--vision`. Non sono verifiche offline.
Nessuna inferenza reale è necessaria per verificare questa copia dei sorgenti.

Lo schema pubblico è in `docs/contracts.schema.json`; dopo modifiche ai DTO,
rigenerarlo con `python -m scripts.export_contract`. Conservare testi e snapshot
storici, identità persistenti e associazioni Picture/Subject esplicite.
