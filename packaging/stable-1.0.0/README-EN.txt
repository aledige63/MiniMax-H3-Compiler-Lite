MiniMax H3 Compiler Lite — Windows 11 x64 — stable release
1.0.0 — MIT — Copyright (c) 2026 aledige
Italiano: LEGGIMI.txt

Stable Windows x64 release 1.0.0. The user confirmed Discard and character-sheet
analysis from a Windows browser connected to the aligned Mac backend on November 22.
A fresh native installation of this new ZIP has not been repeated. The runtime
is unchanged from the accepted application; launchers and dependencies retain
the previously tested base. See RELEASE-1.0.0-EN.md and UPDATE-EN.txt.

One Description, one Analyze action and an explicit Single image / Character
sheet selector. Discard persists; history keeps at most THREE analyses per
cut/Picture, including the current one. Older analyses are deleted at startup.
Back up from the old installation before the first start. Saved descriptions,
files, prompts, versions and snapshots are preserved.

GitHub publication is separate and has not been performed. Linux is excluded.

Requirements: Windows 11 x64 and Python 3.12 x64 with the py launcher installed.
Python: https://www.python.org/downloads/windows/
Extract the ZIP completely into a NEW writable local folder outside Drive,
OneDrive or other synchronized folders. Do not overwrite your old installation.
Double-click Avvia.cmd to start with the default archive, or use the commands
in WINDOWS-CHECK-EN.txt to choose a restored test archive first.
Keep the command window open; stop with Ctrl+C and wait for shutdown.
After starting, refresh the browser with Ctrl+F5.

First launch creates a local .venv and installs requirements.lock from PyPI;
Internet is required. Python, Ollama, models and API keys are not included.
No model is downloaded or called automatically. Existing model selections remain
in your chosen archive. No text model is preset. Vision defaults are unchanged.

Default working archive:
  %LOCALAPPDATA%\MiniMax H3 Compiler Lite\data
If you previously used --data-dir, keep that exact archive path when upgrading.
The startup window displays the selected data path. Code and data are separate.

Saving a shared Subject or Picture description refreshes compatible drafts in
the same open scene. Historical prompts and snapshots remain unchanged; compile
again to obtain a prompt using the new description. The library now opens even
when unsaved fields or a reference conflict are present. Reloading a selected
reference preserves other unsaved fields and manual text.
The library button is at the top of both Images and Subjects in a dedicated
toolbar, separate from creation controls and visible while either list scrolls.
See SCENE-REFERENCE-SYNC-EN.md for the exact scope and conflict behavior.

This revision also includes v6 character-sheet instructions: one unified
description of the character without panel or view commentary. The sheet cache
is new: select Character sheet and press Analyze to obtain a new proposal. Previously
saved descriptions remain intact. The selected vision model and ordinary image
analysis retain their existing settings. See CHARACTER-SHEET-EN.md for testing,
limitations and explicit application.

release-manifest.json lists every payload file, size, SHA-256 and provenance.
SHA256SUMS.txt beside the ZIP verifies the complete download. The launcher and dependency lock are unchanged from the tested base.
LICENSE and THIRD-PARTY-NOTICES.md are included. Dependencies and external models
have their own terms; see DEPENDENCIES-EN.txt. No external project material or
personal archive is included.
