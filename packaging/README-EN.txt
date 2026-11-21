MiniMax H3 Compiler Lite — first launch
Version 2026.11.19-preview3-source1 — MIT — IT/EN documentation
Italiano: apri LEGGIMI.txt.

1. PREPARATION

Download the ZIP for your computer and extract it completely into a writable
local folder, for example a MiniMax folder in your user directory. Do not run
the application inside the ZIP. Keep code and working data outside folders
synchronized by Drive, OneDrive or iCloud.

Install 64-bit Python 3.12 separately:
https://www.python.org/downloads/
Choose a Python 3.12 release with an installer for your platform.
Mac: macOS 14 or later and native Apple Silicon Python (arm64/universal2),
without Rosetta. Windows 11 x64: use the x64 installer including the py launcher.
If another Python version is installed, keep Python 3.12 available too.

First launch requires Internet to install the Python dependencies pinned in
requirements.lock. Python, Ollama, models and API keys are not included.
These are not offline installation packages. No model is downloaded.

2. STARTING AND STOPPING

Mac Apple Silicon: double-click Avvia.command. If macOS requires explicit
opening, use its Open context-menu action and check that this is the script
from the folder you extracted. If the execute permission is missing, open
Terminal in that folder and run:
  chmod +x Avvia.command
  ./Avvia.command

Windows 11 x64: double-click Avvia.cmd. PowerShell, administrator privileges
and changes to PowerShell execution policy are not needed.

The terminal displays the Python check, .venv creation, dependency installation
and startup. Launcher messages are currently in Italian. The ready message
starts with "Pronto" and the browser opens at:
  http://127.0.0.1:8767/
If it does not open automatically, open that URL after the ready message.
Keep the launcher window open while working. To stop, save the draft and any
manual text, wait for processing to finish, press Ctrl+C in that window and
wait for shutdown. Closing the browser does not stop the application.
The ZIPs do not install automatic startup or background services.

If Python is missing, install the required version and launch again.
If dependency installation fails, read the messages, check Internet and retry.
If you moved .venv with the code folder, remove .venv and launch again to
recreate it. For an occupied port, stop the other copy or select another port:
  Mac:     ./Avvia.command --port 18767
  Windows: Avvia.cmd --port 18767
Then open http://127.0.0.1:18767/. Two servers cannot use the same data folder
even on different ports. Do not remove the lock file manually.

3. DATA LOCATION

Mac:
  ~/Library/Application Support/MiniMax H3 Compiler Lite/data
Windows:
  %LOCALAPPDATA%\MiniMax H3 Compiler Lite\data

The launcher displays the actual path. It contains the database, images, audio,
video, settings and any private API key. Preserve the entire folder and keep it
out of Git and public shares. The .venv environment inside the code folder can
be recreated. A new ZIP reuses the same per-user data path regardless of where
you extract its code. Existing data at that path will be reopened.
The packages do not automatically import data from older installations that
used a data folder beside the code.

For an isolated test:
  Mac:     ./Avvia.command --data-dir "$HOME/MiniMax-test/data" --port 18767
  Windows: Avvia.cmd --data-dir "%USERPROFILE%\MiniMax-test\data" --port 18767
Use the same --data-dir for backup and subsequent tests of that archive.
Windows examples use Command Prompt (CMD). In PowerShell use .\Avvia.cmd
and "$env:USERPROFILE\MiniMax-test\data" instead.

4. OLLAMA OR OPENAI

Open Settings and, if needed, select English under appearance and language.
Use an existing local/remote Ollama service or OpenAI with your API key.
The initial Ollama address is empty. For a service on this same computer,
enter http://127.0.0.1:11434 and retrieve its installed models.
The application does not install Ollama or download models.

No text model is preselected in a new installation. Select the service and
model independently for text and vision; one multimodal model can handle
both. Run the synthetic checks in Settings. Complete setup requires a text
model and a selected, verified vision model. Check the displayed destination
before running a test: text and images go to the chosen service. OpenAI calls
use your API account. Saving settings does not start an inference.

A password is optional for the single account. You can enable, change or
disable it. The guided launcher listens only on the local computer.
API keys remain in the private backend archive, so data backups must stay private.

5. FIRST NEUTRAL TEST

Create a test project. Upload a neutral picture, such as an empty cup on a
table, as a Picture with the Object role. Select your verified vision model
and choose Analyze image. Review the proposal, apply it and confirm the
description. Proposals do not replace fields automatically.
Add an Object Subject, explicitly link it to that Picture and confirm its
definition and associations. Declare the H3 slot link only if you intend to
use that same image in your external H3 workflow.

Set the cut duration to 5 seconds and write a simple request, for example:
  The cup remains still on the table for five seconds.
Use # to insert the Subject reference when appropriate. Save the draft and
compile. Review and keep the prompt, then try Export / print. Stop and restart
the application to check that the project and saved version reopen correctly.
Proposals require review; the app prepares prompts and does not generate H3
videos. The browser interface supports Italian/English and light/dark themes.

6. VERIFIED BACKUP AND RESTORE

Save edits, wait for work to finish and stop with Ctrl+C. From the extracted
folder choose a NEW local backup destination:
  Mac:     ./Avvia.command --backup "$HOME/MiniMax-backup-01"
  Windows: Avvia.cmd --backup "%USERPROFILE%\MiniMax-backup-01"
Then verify:
  Mac:     ./Avvia.command --verify-backup "$HOME/MiniMax-backup-01"
  Windows: Avvia.cmd --verify-backup "%USERPROFILE%\MiniMax-backup-01"
If you used --data-dir, also pass it to --backup. Backup includes the chosen
archive's data, media and settings. Keep the application ZIP separately;
Python and external Ollama models are not included. ASR is not configured in
these packages. Manually added external ASR weights need a separate copy.

Backup refuses an active server or an existing destination. After verification
succeeds, compress the completed backup folder and copy it to Drive. Restart
the app normally. Do not place the working database in Google Drive.

To test restore into a new location:
  Mac:
    .venv/bin/python -m scripts.backup_workspace restore "$HOME/MiniMax-backup-01" "$HOME/MiniMax-restored-01"
    ./Avvia.command --data-dir "$HOME/MiniMax-restored-01/data" --port 18767
  Windows CMD:
    .venv\Scripts\python.exe -X utf8 -m scripts.backup_workspace restore "%USERPROFILE%\MiniMax-backup-01" "%USERPROFILE%\MiniMax-restored-01"
    Avvia.cmd --data-dir "%USERPROFILE%\MiniMax-restored-01\data" --port 18767
Restore verifies the backup first and refuses an existing destination.

7. UPDATING

Save everything, stop the previous copy and create a verified backup. Extract
the new ZIP into a new folder rather than overwriting the old .venv. Launch
it to recreate dependencies and reopen the same personal data path, or pass
your existing custom --data-dir. Check a populated project, saved versions
and an export. Keep the old ZIP and backup until the check is complete.
Test a rollback on a separate restored backup, never on a database already
updated by a newer version. Replacing an existing Mac service requires an
explicit choice of the archive and service configuration to use.

8. SOURCE EDITION AND LICENSE

This source copy is version 2026.11.19-preview3-source1 with new independent
history. Application code is preserved from preview3; external references,
inventories, local reports and screenshots are excluded. It includes no
user database, media, models, Python interpreter or credentials.
Tested preview3 packages remain separate and are not replaced.

The standalone recipe creates development ZIPs with distinct names.
Manifests record the explicit file list, provenance and SHA256 hashes.
It requires no old Git tags and does not recreate the original ZIPs byte
for byte. Runtime comparison is not a new native Windows acceptance test.

MIT — Copyright (c) 2026 aledige. Retain LICENSE and the copyright notice.
Dependencies retain their own terms: THIRD-PARTY-NOTICES.md and
DEPENDENCIES-EN.txt. IT/EN guides are available in this folder.
Linux is outside the plan. Preparation does not publish anything to GitHub.
