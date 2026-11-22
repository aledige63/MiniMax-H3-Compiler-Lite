# MiniMax H3 Compiler Lite

[English](README.md) · **Italiano**

Applicazione web locale per preparare prompt MiniMax H3. Organizza progetti,
scene, cut, riferimenti Picture/Subject, parlato esatto, regia e guide video.
Permette di rivedere le proposte dei modelli, conservare versioni manuali,
esportare TXT e stampare dal browser. La generazione video avviene nel workflow
MiniMax H3 esterno.

**Licenza MIT — Copyright (c) 2026 aledige.** Vedere [LICENSE](LICENSE) e
[note sulle dipendenze](THIRD-PARTY-NOTICES.md).


## Versione stabile 1.0.0

Comportamento confermato dall’utente su Windows il 22 novembre 2026, dopo
l’allineamento del backend Mac. Questi sorgenti costruiscono il pacchetto Windows
senza vecchi ZIP o oggetti Git privati. Pubblicazione GitHub separata.

[RELEASE-1.0.0](docs/RELEASE-1.0.0-IT.md) · [DESCRIPTION-WORKFLOW](docs/DESCRIPTION-WORKFLOW-IT.md) · [CHARACTER-SHEET](docs/CHARACTER-SHEET-IT.md) · [SCENE-REFERENCE-SYNC](docs/SCENE-REFERENCE-SYNC-IT.md)

## Scaricamento e installazione

Il repository contiene i sorgenti e gli strumenti di avvio. Scaricalo con Git,
poi esegui l'avvio guidato incluso per installare le dipendenze Python e aprire
l'applicazione. I pacchetti ZIP Mac/Windows già collaudati restano distribuzioni
separate. [Note tecniche sui sorgenti](docs/SOURCE-COPY-IT.md).

### 1. Installa i prerequisiti

| Requisito | Mac | Windows |
|---|---|---|
| Sistema | macOS 14 o successivo, Apple Silicon | Windows 11 x64 |
| Python | Python **3.12** nativo a 64 bit | Python **3.12** a 64 bit, con launcher `py` |
| Git | [Git per macOS](https://git-scm.com/install/mac) | [Git per Windows](https://git-scm.com/install/windows) |

Installa Python da [python.org](https://www.python.org/downloads/). Scegli la
serie **3.12**: l'avvio guidato richiede questa versione anche se ne hai
installata una più recente. Su Mac usa un installer compatibile con Apple
Silicon (`arm64`/`universal2`) e una sessione Terminale nativa. Su Windows scegli
l'installer x64 e includi pip e il launcher Python. Sul sito dei download sono
elencate le release Python 3.12 che forniscono installer nativi.

Dopo l'installazione di Git o Python apri un nuovo terminale. Servono Internet
per il download e per installare le dipendenze al primo avvio. Linux è escluso
dalle piattaforme previste per la distribuzione.

### 2. Scarica con Git

Segui le istruzioni per il tuo computer. Gli esempi creano una cartella locale
`Projects` nella tua cartella utente. Conserva sorgenti e archivio fuori dalle
cartelle sincronizzate di Drive, OneDrive o iCloud.

**Mac — Terminale**

Controlla prima Git e Python:

```sh
git --version
python3.12 -c "import sys, platform; print(sys.version); print(platform.machine())"
```

L'output Python atteso è `3.12.x` e `arm64`. Se al primo uso di Git macOS propone
di installare gli strumenti da riga di comando, completa l'installazione prima
di continuare.

Scarica il repository ed entra nella sua cartella:

```sh
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/aledige63/MiniMax-H3-Compiler-Lite.git
cd MiniMax-H3-Compiler-Lite
```

**Windows — PowerShell**

Apri PowerShell e controlla Git e Python:

```powershell
git --version
py -3.12 -c "import sys, platform, struct; print(sys.version); print(platform.machine()); print(struct.calcsize('P') * 8)"
```

L'output Python atteso è `3.12.x`, `AMD64`/`x86_64` e `64`.

Scarica il repository ed entra nella sua cartella:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Projects" | Out-Null
Set-Location "$env:USERPROFILE\Projects"
git clone https://github.com/aledige63/MiniMax-H3-Compiler-Lite.git
Set-Location MiniMax-H3-Compiler-Lite
```

Il repository è pubblico: per scaricarlo non serve un account GitHub.
La clonazione scarica i file del progetto e la cronologia Git pubblica;
non installa Python, dipendenze o modelli. Se la cartella di destinazione esiste
già, scegli un'altra cartella locale oppure aggiorna il clone esistente come
descritto più avanti.

### 3. Installa le dipendenze e avvia

Esegui il comando seguente **dentro la cartella `MiniMax-H3-Compiler-Lite`
appena scaricata**. Avvia l'installazione guidata inclusa nel progetto.

**Mac — Terminale**

```sh
python3.12 -X utf8 start.py
```

**Windows — PowerShell**

```powershell
py -3.12 -X utf8 start.py
```

Al primo avvio il programma controlla Python e la piattaforma, crea `.venv`,
installa da PyPI le versioni di `requirements.lock`, verifica le dipendenze e
avvia il server locale. Lascia aperto il terminale e attendi il messaggio di
disponibilità. Il browser dovrebbe aprirsi su **<http://127.0.0.1:8767/>**.

Se il browser non si apre automaticamente, apri quell'indirizzo dopo che il
server è pronto. Per gli avvii successivi usa lo stesso comando: l'ambiente
preparato viene riutilizzato quando è ancora valido. Gli avvisi di avvio sono
attualmente italiani; l'interfaccia del browser offre inglese e italiano
nelle impostazioni.

Per fermare il server salva, attendi la fine dei lavori e premi **Ctrl+C** nel
terminale. Chiudere soltanto il browser lo lascia attivo.

### 4. Configura testo e vision

Apri **Impostazioni utente**. Scegli un servizio Ollama locale/remoto già
disponibile oppure OpenAI, quindi seleziona e verifica separatamente testo e
vision. Un modello vision verificato è richiesto per completare la configurazione.

Per Ollama sullo stesso computer inserisci `http://127.0.0.1:11434`. Installa
separatamente Ollama e modelli adatti. Non sono preselezionati endpoint personali
o modelli testo/vision e l'applicazione non scarica modelli. Le richieste vanno
al servizio scelto; le chiamate OpenAI usano il tuo account API. Le chiavi restano
nell'archivio privato del backend. La password dell'unico account è facoltativa.
Salvataggi, caricamenti, copia ed export non avviano inferenze.

Crea un progetto e un cut. Carica una Picture, richiedi l'analisi, poi rivedi,
applica e conferma la descrizione. Aggiungi e collega il Subject esplicitamente:
un'immagine non lo crea automaticamente. I numeri dei Subject sono locali alla
scena. Scrivi la richiesta, il parlato esatto e il parlante, salva e compila.
Rivedi la proposta prima di confermarla o esportarla. Testo manuale e versioni
storiche conservano parole, spazi e snapshot.

## Dati e prove separate

L'archivio di lavoro è separato dalla cartella dei sorgenti clonati:

| Piattaforma | Cartella dati predefinita |
|---|---|
| Mac | `~/Library/Application Support/MiniMax H3 Compiler Lite/data` |
| Windows | `%LOCALAPPDATA%\MiniMax H3 Compiler Lite\data` |

I dati già presenti in questi percorsi vengono riaperti. Prima di passare a
questa copia da un'installazione operativa, salva, ferma il suo server e crea
un backup verificato seguendo la [guida di backup e ripristino](packaging/LEGGIMI.txt).
Se usi un archivio personalizzato, passa esplicitamente lo stesso `--data-dir`.
I dati conservati accanto a un'altra cartella sorgenti non vengono importati
automaticamente.

Per una prova in un archivio separato e su una porta diversa:

**Mac**

```sh
python3.12 -X utf8 start.py --data-dir "$HOME/MiniMax-prova/data" --port 18767
```

**Windows — PowerShell**

```powershell
py -3.12 -X utf8 start.py --data-dir "$env:USERPROFILE\MiniMax-prova\data" --port 18767
```

Apri `http://127.0.0.1:18767/`. Per riaprire quell'archivio di prova usa lo stesso
`--data-dir`. Due server non possono usare contemporaneamente lo stesso archivio.

## Aggiorna un clone Git esistente

Salva, attendi la fine dei lavori, ferma l'applicazione e crea un backup
verificato dei dati. Apri un terminale nella cartella del repository esistente:

```sh
git status --short
git pull --ff-only
```

Se `git status` elenca modifiche locali, controllale e conservale prima di
aggiornare. Risolvi eventuali conflitti o cronologie divergenti segnalati da Git
prima di continuare. Dopo il pull riuscito esegui lo stesso comando di avvio
per la tua piattaforma. Se necessario, il programma prepara nuovamente le
dipendenze e riapre la cartella dati scelta. Controlla progetti salvati,
selezioni dei modelli, versioni e un export.

## Risoluzione dei problemi

| Problema | Cosa controllare |
|---|---|
| `git` non viene riconosciuto | Installa Git, poi apri un nuovo terminale. |
| Python 3.12 non viene trovato | Installa Python 3.12 a 64 bit; su Windows includi il launcher `py`. |
| Su Mac viene segnalata un'architettura errata | Usa Python nativo per Apple Silicon e una sessione Terminale fuori da Rosetta. |
| L'installazione di una dipendenza fallisce | Leggi l'errore, controlla Internet e ripeti il comando di avvio. |
| La porta 8767 è occupata | Ferma l'altro server oppure aggiungi `--port 18767` e apri il relativo indirizzo. |
| L'archivio è già in uso | Ferma il suo server oppure scegli un `--data-dir` separato. |

## Documentazione

| Argomento | Italiano | English |
|---|---|---|
| Uso, backup e ripristino | [Guida utente](packaging/LEGGIMI.txt) | [User guide](packaging/README-EN.txt) |
| Dipendenze | [Note dipendenze](packaging/NOTE-DIPENDENZE.txt) | [Dependency notes](packaging/DEPENDENCIES-EN.txt) |
| Sviluppo e test | [Sviluppo](docs/DEVELOPMENT-IT.md) | [Development](docs/DEVELOPMENT-EN.md) |
| Provenienza e ambito dei sorgenti | [Ambito sorgenti](docs/SOURCE-COPY-IT.md) | [Source notes](docs/SOURCE-COPY-EN.md) |

Il [piano futuro](docs/ROADMAP.md) prevede la valutazione dell'integrazione con
Stage tramite video guida esportato e relativo prompt camera. La modalità sarà
definita dopo una prova di export; questa versione non la implementa.
