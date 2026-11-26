# MiniMax H3 Compiler Lite 1.1.0

November 26, 2026 · stable release · MIT, copyright (c) 2026 aledige.

## Changes since 1.0.0

- **Object sheet · multiple views** consolidates repeated depictions of one object
  into one description. Whole original image, Compact/Medium/Full, separate cache,
  explicit proposal application and no automatically created Subjects.
- Motion guides explicitly bind Subject appearance to Pictures/continuity and
  position, orientation and trajectory to the Video proxy. Each Subject replaces
  its proxy from first appearance; proxy shapes are not additional scene objects.
- The guide’s declared opening is authoritative. Recognized second openings in
  actions or the summary are rejected without rewriting or hidden retries.
- README and launcher guides explicitly require local/remote Ollama with installed
  models, or an OpenAI API key. Text and verified vision models are required.

## Using output from Stage 0.9.0 onward

With **Stage 0.9.0**, use the exported MP4 together with **Prompt for MiniMax
Compiler**, saved as `_compiler.txt`. Add the MP4 as a Video guide, select and
enable its role, map every figure to its Subject, and paste only the narrative
body into **Guide prompt · English** (maximum 2,500 characters).
A mannequin and a box can guide a person and a vehicle whose appearance comes
from their own Pictures. The environment remains a separate reference.
Connect the file to the matching Video slot in the external H3 workflow too.

This is a usable manual workflow. This release does not implement a joint
MP4/TXT/JSON importer and does not execute Stage or MiniMax H3.
Guide: [STAGE-EN](STAGE-EN.md). Stage: https://github.com/aledige63/Stage/releases/tag/v0.9.0.

## Preservation and validation

Saved prompts, manual versions, snapshots, associations and files are preserved.
New instructions apply only to new analyses/compilations. No SQLite migration
or automatic model download. Version 1.0.0 and older tags/ZIPs stay unchanged.

Local runtime checks: 438 Python tests ran (one skipped), 114 JavaScript tests,
DTO schema, dependencies and data/media integrity after a Mac restart. The public
copy also includes an independent packaging check. Automated tests use synthetic
archives and simulated responses without real inference.
The user’s external Stage/H3 trial with a corrected prompt improved the output,
with some trajectory approximation remaining. This is not a guarantee of H3
geometric fidelity or acceptance of the new automatic LLM path.
A fresh native Windows installation of this ZIP has not been repeated.

## Downloads and upgrading

Windows 11 x64: extract into a new writable local folder and run `Avvia.cmd`
with Python 3.12 x64 installed. Save edits, stop the old server and create a
verified backup first. Preserve the data archive or exact `--data-dir` path.
Do not overwrite the old code folder. Mac Apple Silicon runs from source with
Python 3.12; no new Mac ZIP. Python, Ollama, models and API keys are not bundled.
Linux is excluded. Verify downloads against `SHA256SUMS.txt`.
