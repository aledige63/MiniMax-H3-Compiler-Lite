# MiniMax H3 Compiler Lite 1.1.0

26 novembre 2026 · rilascio stabile · MIT, copyright (c) 2026 aledige.

## Novità rispetto a 1.0.0

- **Scheda oggetto · più viste**: integra le raffigurazioni dello stesso oggetto
  in una descrizione unica. File originale completo, livelli Compact/Medium/Full,
  cache distinta, proposta da applicare esplicitamente e nessun Subject automatico.
- Guide movimento con mapping espliciti nelle definizioni: aspetto dalle Picture
  o dal contesto, posizione/orientamento/traiettoria dal proxy Video. Il Subject
  sostituisce la sagoma dalla prima comparsa; la sagoma non è un oggetto aggiuntivo.
- Apertura dichiarata nella guida autorevole. Le seconde aperture riconosciute
  nelle azioni o nel summary sono rifiutate senza riscritture o retry nascosti.
- Prerequisiti AI espliciti nei README e nelle guide: Ollama locale/remoto con
  modelli installati, oppure chiave API OpenAI. Servono testo e vision verificato.

## Utilizzo dell’output Stage dalla versione 0.9.0

Da **Stage 0.9.0** si possono usare insieme l’MP4 esportato e il testo
**Prompt per MiniMax Compiler**, salvato come `_compiler.txt`.
Caricare l’MP4 come Video guida nel cut, scegliere il ruolo corretto, attivarlo,
associare ogni figura al Subject e incollare il solo corpo narrativo nel campo
**Prompt guida · inglese** (massimo 2.500 caratteri).
Il manichino e un parallelepipedo possono guidare rispettivamente una persona
e un’auto, definite dalle proprie Picture. L’ambiente resta un riferimento distinto.
Il file va collegato anche allo stesso slot Video nel workflow H3 esterno.

È un flusso manuale già utilizzabile: questa release non include un importatore
automatico congiunto MP4/TXT/JSON e non esegue Stage o MiniMax H3.
Guida: [STAGE-IT](STAGE-IT.md). Stage: https://github.com/aledige63/Stage/releases/tag/v0.9.0.

## Conservazione e verifiche

Prompt salvati, versioni manuali, snapshot, associazioni e file sono conservati.
Le nuove istruzioni si applicano soltanto a nuove analisi/compilazioni. Nessuna
migrazione SQLite o modello scaricato automaticamente. La serie 1.0.0 e i vecchi
tag/ZIP restano invariati.

Controlli locali del runtime: 438 test Python eseguiti (uno saltato), 114 JavaScript,
schema DTO, dipendenze e integrità dati/media dopo riavvio Mac. La copia pubblica
include inoltre il controllo autonomo del confezionamento. Le prove automatiche
usano archivi sintetici e risposte simulate, senza inferenze reali.
Il test esterno dell’utente con una guida Stage e un prompt corretto ha dato un
risultato migliore, con traiettorie ancora approssimative. Non è una garanzia di
fedeltà geometrica H3 né un collaudo del nuovo percorso LLM automatico.
Una nuova installazione nativa Windows di questo ZIP non è stata ripetuta.

## Download e aggiornamento

Windows 11 x64: estrarre il nuovo ZIP in una cartella locale nuova e avviare
`Avvia.cmd` con Python 3.12 x64 installato. Salvare gli edit, fermare il vecchio
server e creare prima un backup verificato. Conservare lo stesso archivio dati
o lo stesso `--data-dir`. Non sovrascrivere la vecchia cartella del codice.
Mac Apple Silicon: avvio dai sorgenti con Python 3.12; nessun nuovo ZIP Mac.
Modelli, Ollama, Python e chiavi API non sono inclusi. Linux escluso.
Confrontare i download con `SHA256SUMS.txt`.
