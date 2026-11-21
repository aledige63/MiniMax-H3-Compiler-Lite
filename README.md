# MiniMax H3 Compiler Lite

English: [README-EN.md](README-EN.md).

Compilatore locale di prompt per il workflow MiniMax H3. Organizza progetti,
scene, cut, riferimenti Picture/Subject, dialoghi, regia, guide video e versioni.
Supporta analisi immagini esplicita, ASR facoltativo, export TXT e stampa dal browser.
Prepara prompt in inglese e conserva il parlato nella lingua originale.
Le proposte richiedono revisione umana. Non genera video e non esegue MiniMax H3.

**MIT — Copyright (c) 2026 aledige.** Vedere [LICENSE](LICENSE) e
[note sulle dipendenze](THIRD-PARTY-NOTICES.md).

## Copia sorgenti

Edizione `2026.11.19-preview3-source1`, preparata per una futura pubblicazione.
Il codice applicativo e gli avvii corrispondono alla preview3, il cui runtime
è identico alla preview2 collaudata. Questa copia contiene una nuova cronologia
indipendente; i vecchi tag e la storia locale non sono inclusi. Gli ZIP collaudati
restano distribuzioni separate: non vengono rigenerati o sostituiti da questa copia.
Materiali esterni, inventari, report reali e schermate di sviluppo sono esclusi.
La ricetta di sviluppo funziona anche senza Git e produce ZIP con nomi distinti.
Vedere [sviluppo](docs/DEVELOPMENT-IT.md) e [ambito](docs/SOURCE-COPY-IT.md).
Nessuna pubblicazione è stata eseguita durante questa preparazione.

## Avvio

Piattaforme previste: Mac Apple Silicon con macOS 14 o successivo e Windows 11 x64.
Linux escluso. Installare separatamente Python 3.12 nativo a 64 bit.
Estrarre i sorgenti in una cartella locale scrivibile fuori da Drive/OneDrive/iCloud.

- Mac: doppio clic su `Avvia.command` (se serve: `chmod +x Avvia.command`).
- Windows: doppio clic su `Avvia.cmd`.

Al primo avvio occorre Internet per installare `requirements.lock` in `.venv`.
Nessun modello viene scaricato. Si apre `http://127.0.0.1:8767/`.
Salvare, attendere la fine dei lavori e premere Ctrl+C per fermare il server.
L'interfaccia del browser offre italiano e inglese; gli avvisi degli avvii sono italiani.

I dati persistenti sono in `~/Library/Application Support/MiniMax H3 Compiler Lite/data`
su Mac e `%LOCALAPPDATA%\MiniMax H3 Compiler Lite\data` su Windows.
Se esistono già dati in questi percorsi, saranno riaperti. Per una prova isolata:

```sh
./Avvia.command --data-dir "$HOME/MiniMax-prova/data" --port 18767
```

```bat
Avvia.cmd --data-dir "%USERPROFILE%\MiniMax-prova\data" --port 18767
```

## Configurazione e uso

Aprire Impostazioni utente e scegliere Ollama locale/remoto oppure OpenAI.
Nessun endpoint personale o modello testo/vision è preselezionato. Per Ollama sullo
stesso computer usare `http://127.0.0.1:11434`; i modelli vanno installati separatamente.
Scegliere e verificare testo e vision; un vision verificato completa la configurazione.
La password dell'unico account è facoltativa. Le chiavi API restano nell'archivio privato.
Salvataggi, caricamenti, export e copia non avviano inferenze.

Creare un progetto e un cut. Caricare una Picture, analizzarla su richiesta e
controllare/applicare/confermare la descrizione. Aggiungere e collegare il Subject
esplicitamente: un'immagine non crea automaticamente un Subject. I numeri dei
Subject sono locali alla scena; le associazioni usano identità persistenti.
Scrivere la richiesta, registrare il parlato esatto e il parlante, salvare e compilare.
Rivedere la proposta prima di confermare ed esportare. Testo manuale e versioni
storiche conservano parole, spazi e snapshot.

Le guide dettagliate di avvio, backup e ripristino sono in
[packaging/LEGGIMI.txt](packaging/LEGGIMI.txt). Prima di un backup salvare e fermare
il server. Ripristinare solo in una destinazione nuova e verificare gli hash.
Codice e archivio operativo hanno backup distinti; non mettere dati, credenziali,
media o pesi nel repository e non lavorare sul database operativo dentro Drive.

L'integrazione futura Stage è nel [piano IT/EN](docs/ROADMAP.md): modalità da decidere
dopo una prova con video e prompt reali. Non è implementata in questa edizione.
