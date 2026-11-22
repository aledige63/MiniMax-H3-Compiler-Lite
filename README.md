# MiniMax H3 Compiler Lite

**English** · [Italiano](README-IT.md)

A local web application for preparing MiniMax H3 prompts. Organize projects,
scenes, cuts, Picture/Subject references, exact dialogue, camera direction and
video guides. Review model proposals, keep manual versions, export TXT and
print from the browser. Video generation takes place in your separate MiniMax
H3 workflow.

**MIT License — Copyright (c) 2026 aledige.** See [LICENSE](LICENSE) and
[dependency notices](THIRD-PARTY-NOTICES.md).


## Stable version 1.0.0

Windows behavior was accepted by the user on November 22, 2026, after the Mac
backend was aligned. This source snapshot builds the standalone Windows package
without historical ZIPs or private Git objects. GitHub publication is separate.

[RELEASE-1.0.0](docs/RELEASE-1.0.0-EN.md) · [DESCRIPTION-WORKFLOW](docs/DESCRIPTION-WORKFLOW-EN.md) · [CHARACTER-SHEET](docs/CHARACTER-SHEET-EN.md) · [SCENE-REFERENCE-SYNC](docs/SCENE-REFERENCE-SYNC-EN.md)

## Download and install

This repository contains the source code and startup tools. Clone it with Git,
then run the included guided launcher to install the Python dependencies and
open the application. The previously tested Mac/Windows ZIP packages remain
separate distributions. [Technical source notes](docs/SOURCE-COPY-EN.md).

### 1. Install the prerequisites

| Requirement | Mac | Windows |
|---|---|---|
| System | macOS 14 or later, Apple Silicon | Windows 11 x64 |
| Python | Native 64-bit Python **3.12** | 64-bit Python **3.12**, with the `py` launcher |
| Git | [Git for macOS](https://git-scm.com/install/mac) | [Git for Windows](https://git-scm.com/install/windows) |
| AI service | Ollama with installed models, or an OpenAI API key (see below) | Ollama with installed models, or an OpenAI API key (see below) |

For AI features, prepare one of these alternatives before configuring the app:

- **Ollama:** install and run Ollama locally with suitable models already
  downloaded, or use an existing remote Ollama service with installed models.
- **OpenAI:** have an OpenAI API key and an API account enabled for the selected
  models. Requests use that account and may incur API charges.

Choose a text model for prompt compilation and a vision model for image and
character-sheet analysis. The same multimodal model can serve both roles, or
you can configure text and vision separately. A verified vision model is
required to complete setup. Ollama, model weights and API keys are not included;
the app does not download models. Configure and verify your choices in
**User settings** after startup, as described in step 4.

Install Python from [python.org](https://www.python.org/downloads/). Select the
**3.12** series: the launcher requires it even if a newer Python is installed.
On Mac, use an Apple Silicon compatible installer (`arm64`/`universal2`) and a
native terminal session. On Windows, choose the x64 installer and include pip
and the Python launcher. The download site lists Python 3.12 releases that
provide native installers.

Open a new terminal after installing Git or Python. Internet access is needed
for the download and first dependency installation. Linux is outside the
supported delivery targets.

### 2. Download with Git

Use the instructions for your computer. The examples create a local `Projects`
folder under your user account. Keep source and working data outside folders
synchronized by Drive, OneDrive or iCloud.

**Mac — Terminal**

First check Git and Python:

```sh
git --version
python3.12 -c "import sys, platform; print(sys.version); print(platform.machine())"
```

Expected Python output: `3.12.x` and `arm64`. If macOS offers to install command
line tools on your first use of Git, complete the installation before continuing.

Clone the repository and enter its folder:

```sh
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/aledige63/MiniMax-H3-Compiler-Lite.git
cd MiniMax-H3-Compiler-Lite
```

**Windows — PowerShell**

Open PowerShell and check Git and Python:

```powershell
git --version
py -3.12 -c "import sys, platform, struct; print(sys.version); print(platform.machine()); print(struct.calcsize('P') * 8)"
```

Expected Python output: `3.12.x`, `AMD64`/`x86_64`, and `64`.

Clone the repository and enter its folder:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Projects" | Out-Null
Set-Location "$env:USERPROFILE\Projects"
git clone https://github.com/aledige63/MiniMax-H3-Compiler-Lite.git
Set-Location MiniMax-H3-Compiler-Lite
```

The repository is public; downloading it does not require a GitHub account.
Cloning downloads the project files and public Git history. It does not install
Python, dependencies or models. If the destination folder already exists,
choose another local parent folder or update the existing clone as described below.

### 3. Install dependencies and start

Run the following command **inside the cloned `MiniMax-H3-Compiler-Lite`
folder**. It starts the guided installer included in the project.

**Mac — Terminal**

```sh
python3.12 -X utf8 start.py
```

**Windows — PowerShell**

```powershell
py -3.12 -X utf8 start.py
```

On first launch, the program checks Python and the platform, creates `.venv`,
installs the versions in `requirements.lock` from PyPI, checks dependencies and
starts the local server. Keep the terminal open and wait for the ready message.
The browser should open at **<http://127.0.0.1:8767/>**.

If the browser does not open automatically, open that address after the server
is ready. Use the same command on subsequent launches; the prepared environment
is reused when still valid. Launcher messages are currently Italian. The browser
interface offers English and Italian in its settings.

To stop, save changes, wait for jobs to finish and press **Ctrl+C** in the
terminal. Closing the browser alone leaves the server running.

### 4. Configure text and vision

Open **User settings**. Choose an existing local/remote Ollama service or OpenAI,
then select and verify text and vision independently. A verified vision model
is required for complete setup.

For Ollama on the same computer, enter `http://127.0.0.1:11434`. Install Ollama
and suitable models separately. No personal endpoint or text/vision model is
preselected, and the application does not download models. Requests go to your
chosen provider; OpenAI calls use your API account. Keys stay in the private
backend archive. The single account password is optional. Saving settings,
loading, copying and exporting do not trigger inference.

Create a project and a cut. Upload a Picture, request analysis, then review,
apply and confirm the description. Add and associate a Subject explicitly;
uploading an image does not create one. Subject numbers belong to each scene.
Enter the request, exact dialogue and speaker, save and compile. Review the
proposal before confirming or exporting. Manual text and historical versions
preserve words, whitespace and snapshots.

## Data and isolated trials

Working data is separate from the cloned source folder:

| Platform | Default data folder |
|---|---|
| Mac | `~/Library/Application Support/MiniMax H3 Compiler Lite/data` |
| Windows | `%LOCALAPPDATA%\MiniMax H3 Compiler Lite\data` |

Existing data at these paths will reopen. Before switching an existing working
installation, save changes, stop its server and create a verified backup using
the [backup and recovery guide](packaging/README-EN.txt). Pass the same
`--data-dir` explicitly if you use a custom archive. Data stored next to another
source folder is not imported automatically.

For a trial in a separate archive and on another port:

**Mac**

```sh
python3.12 -X utf8 start.py --data-dir "$HOME/MiniMax-trial/data" --port 18767
```

**Windows — PowerShell**

```powershell
py -3.12 -X utf8 start.py --data-dir "$env:USERPROFILE\MiniMax-trial\data" --port 18767
```

Open `http://127.0.0.1:18767/`. Reuse the same `--data-dir` to reopen that trial
archive. Two servers cannot use the same archive simultaneously.

## Update an existing Git clone

Save changes, wait for jobs to finish, stop the application and create a
verified data backup. Open a terminal in your existing repository folder:

```sh
git status --short
git pull --ff-only
```

If `git status` lists local changes, review and preserve them before updating.
Resolve any conflict or divergent history reported by Git before continuing.
After a successful pull, run the same startup command for your platform. The
launcher prepares dependencies again if needed and reopens the selected data
folder. Check saved projects, model choices, versions and an export.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `git` is not recognized | Install Git, then open a new terminal. |
| Python 3.12 is not found | Install 64-bit Python 3.12; on Windows include the `py` launcher. |
| Mac reports the wrong architecture | Use native Apple Silicon Python and a terminal session outside Rosetta. |
| A dependency installation fails | Read the terminal error, check Internet access, then rerun the startup command. |
| Port 8767 is occupied | Stop the other server or add `--port 18767` and open the matching URL. |
| The archive is already in use | Stop its server or choose a separate `--data-dir`. |

## Documentation

| Topic | English | Italiano |
|---|---|---|
| Operation, backup and recovery | [User guide](packaging/README-EN.txt) | [Guida utente](packaging/LEGGIMI.txt) |
| Dependencies | [Dependency notes](packaging/DEPENDENCIES-EN.txt) | [Note dipendenze](packaging/NOTE-DIPENDENZE.txt) |
| Source development and tests | [Development](docs/DEVELOPMENT-EN.md) | [Sviluppo](docs/DEVELOPMENT-IT.md) |
| Source provenance and scope | [Source notes](docs/SOURCE-COPY-EN.md) | [Ambito sorgenti](docs/SOURCE-COPY-IT.md) |

See the [roadmap](docs/ROADMAP.md) for future Stage integration using its exported
guide video and matching camera prompt. The method remains to be decided after
an export trial; it is not implemented in this version.
