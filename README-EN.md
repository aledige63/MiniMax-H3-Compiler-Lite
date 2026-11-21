# MiniMax H3 Compiler Lite

Italiano: [README.md](README.md).

A local prompt compiler for the MiniMax H3 workflow. Organizes projects, scenes,
cuts, Picture/Subject references, dialogue, camera direction, video guides and versions.
Supports explicit image analysis, optional ASR, TXT exports and browser printing.
Produces English prompts while keeping dialogue in its original language.
Proposals require human review. It does not generate video or execute MiniMax H3.

**MIT — Copyright (c) 2026 aledige.** See [LICENSE](LICENSE) and
[dependency notices](THIRD-PARTY-NOTICES.md).

## Source copy

Edition `2026.11.19-preview3-source1`, prepared for future publication.
Application code and launchers match preview3, whose runtime is identical to tested
preview2. This copy has a new independent history; old tags and local history are
excluded. Tested ZIPs remain separate distributions and are neither rebuilt nor
replaced by this copy. External reference materials, inventories, real development
reports and screenshots are excluded. The development recipe also works without
Git and creates ZIPs with distinct names. See [development](docs/DEVELOPMENT-EN.md)
and [scope](docs/SOURCE-COPY-EN.md). No publication occurred during preparation.

## Start

Supported targets: Mac Apple Silicon with macOS 14 or later, and Windows 11 x64.
Linux is outside the plan. Install native 64-bit Python 3.12 separately.
Extract sources into a writable local folder outside Drive/OneDrive/iCloud.

- Mac: double-click `Avvia.command` (if needed: `chmod +x Avvia.command`).
- Windows: double-click `Avvia.cmd`.

First launch needs Internet to install `requirements.lock` into `.venv`.
No models are downloaded. The browser opens `http://127.0.0.1:8767/`.
Save changes, wait for jobs to finish, then press Ctrl+C to stop the server.
The browser interface supports Italian and English; launcher messages are Italian.

Persistent data lives in `~/Library/Application Support/MiniMax H3 Compiler Lite/data`
on Mac and `%LOCALAPPDATA%\MiniMax H3 Compiler Lite\data` on Windows.
Existing data at those paths will reopen. For an isolated trial:

```sh
./Avvia.command --data-dir "$HOME/MiniMax-trial/data" --port 18767
```

```bat
Avvia.cmd --data-dir "%USERPROFILE%\MiniMax-trial\data" --port 18767
```

## Configuration and use

Open User settings and choose local/remote Ollama or OpenAI.
No personal endpoint or text/vision model is preselected. For Ollama on the same
computer use `http://127.0.0.1:11434`; install models separately.
Choose and verify text and vision independently; verified vision completes setup.
The single account password is optional. API keys stay in the private backend archive.
Saving, loading, exporting and copying do not trigger inference.

Create a project and a cut. Upload a Picture, request analysis, then review,
apply and confirm its description. Add and associate a Subject explicitly:
uploading an image does not create a Subject. Subject numbers belong to each scene;
associations use persistent identities. Enter the request, exact dialogue and speaker,
save and compile. Review the proposal before confirming and exporting.
Manual text and historical versions preserve words, whitespace and snapshots.

Detailed startup, backup and recovery instructions are in
[packaging/README-EN.txt](packaging/README-EN.txt). Save changes and stop the server
before backing up. Restore only into a new destination and verify hashes.
Source and operational data have separate backups. Never add data, credentials,
media or weights to the repository or run the operational database inside Drive.

Future Stage integration is recorded in the [IT/EN roadmap](docs/ROADMAP.md).
Its method will be decided after a real video/prompt export trial.
It is not implemented in this edition.
