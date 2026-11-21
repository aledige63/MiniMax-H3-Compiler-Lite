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

`python -m scripts.build_packages --output dist/source-build` crea due ZIP di sviluppo
Mac/Windows con versione distinta `2026.11.19-preview3-source1`. Non richiede Git,
tag storici o fonti esterne e non ricrea gli ZIP collaudati byte per byte.
`packaging/files.json` è l'elenco esplicito; `packaging/runtime-reference.json`
verifica SHA256 dei file applicativi e degli avvii. Il campo source_commit è solo
provenienza: il relativo oggetto Git originale non è incluso. Il tag stabile è null.
Aggiornare consapevolmente il riferimento solo per revisioni runtime intenzionali.
I manifesti verificano ogni file e i due archivi hanno checksum separati.

Gli script smoke/benchmark effettuano inferenze solo se avviati esplicitamente.
Scegliere i modelli installati con `--model`; m3 richiede il modello vision e
m5 richiede `--vision-model` quando si abilita `--vision`. Non sono verifiche offline.
Nessuna inferenza reale è necessaria per verificare questa copia dei sorgenti.

Lo schema pubblico è in `docs/contracts.schema.json`; dopo modifiche ai DTO,
rigenerarlo con `python -m scripts.export_contract`. Conservare testi e snapshot
storici, identità persistenti e associazioni Picture/Subject esplicite.
