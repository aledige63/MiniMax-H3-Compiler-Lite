# Source development

Requires Python 3.12. Run from the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m scripts.export_contract --check
.venv/bin/python -m pip check
node --test tests/*.mjs
git diff --check
```

On Windows use `py -3.12 -m venv .venv` and replace `.venv/bin/python` with
`.venv\Scripts\python.exe -X utf8`. Node is only needed for JavaScript tests.
Automated tests use synthetic fixtures without real AI models or services.
Manual startup: `python -m scripts.serve --port 8767 --data-dir trial-data`.
Use the interpreter from the active virtual environment for Python commands.

## Standalone recipe

`python -m scripts.build_packages --output dist/1.1.0` creates the stable
Windows x64 ZIP. Git, old tags and old ZIPs are not required. The explicit
allowlist is `packaging/files.json`; `packaging/runtime-reference.json` checks
application and launcher hashes. The public release tag and runtime hashes identify the payload; the exact public commit is recorded in the delivery VERIFICA.json. Version is
1.1.0, stable tag v1.1.0. Update the reference deliberately for runtime changes.


Smoke/benchmark scripts perform real inference only when run explicitly.
Choose installed models using `--model`; m3 needs a vision model and m5 needs
`--vision-model` when `--vision` is enabled. These are not offline checks.
No real inference is needed to validate this source copy.

The public schema is `docs/contracts.schema.json`; after changing DTOs, regenerate
using `python -m scripts.export_contract`. Preserve historical text and snapshots,
persistent identities and explicit Picture/Subject associations.
