# MiniMax H3 Compiler Lite 1.0.0

Rilascio stabile del 22 novembre 2026. English: [RELEASE-1.0.0-EN.md](RELEASE-1.0.0-EN.md).
MIT — Copyright (c) 2026 aledige.

## Comportamento consolidato

- Una sola Descrizione per Picture, con selettore esplicito Immagine singola /
  Character sheet e un solo Analizza. Ogni clic richiede un'analisi nuova;
  cambiare selettore o aprire opzioni e storico non chiama il modello.
- Scarta rimuove subito la proposta e persiste senza cambiare descrizione,
  altri campi del cut o testo manuale. Se il server rifiuta il comando, la
  proposta torna visibile con l'errore. Nessuna promozione di proposte vecchie.
- Al massimo tre analisi per cut/Picture, inclusa l'attuale: analisi immagine,
  character sheet, traduzioni e tentativi falliti condividono il limite.
  Le precedenti vengono eliminate anche al primo avvio; lavoro attivo protetto.
- Character sheet v6: descrizione unica della persona dall'immagine intera,
  senza commenti sui pannelli; applicazione esplicita e correzioni manuali
  autorevoli. Proposte non valide rifiutate senza riscrittura o retry automatico.
- Descrizioni condivise di Picture/Subject sincronizzate per UUID fra bozze
  compatibili nella stessa scena aperta. Campi locali, file/proxy, esclusioni,
  prompt conservati, versioni e snapshot restano protetti.
- Libreria accessibile anche con edit non salvati; ricaricamento selettivo e
  barra distinta dalla creazione, fissa in Immagini e Subject.

## Collaudo e ambito

Il 22 novembre l'utente ha confermato sul PC Windows che Scarta funziona e che
la nuova analisi del character sheet non cita più i pannelli, dopo l'allineamento
del backend Mac. Verificati inoltre scarto dopo due riavvii controllati,
idempotenza, conservazione di testi/versioni/snapshot e hash dei file media.

La conferma funzionale riguarda il browser Windows collegato al backend Mac.
Il nuovo ZIP Windows mantiene avvio e dipendenze della base già collaudata;
non viene dichiarata una nuova installazione nativa Windows di questo ZIP.
La qualità delle descrizioni resta da controllare sul proprio riferimento.
La consegna numerata riguarda Windows x64. Il servizio Mac esistente resta
attivo; non viene consegnato un nuovo installer Mac. Linux escluso.

## Aggiornamento

Prima del primo avvio crea un backup verificato dalla vecchia installazione:
il limite di tre elimina le analisi più vecchie. Descrizioni salvate, originali,
prompt, versioni e snapshot non vengono eliminati. Estrai in una cartella nuova,
mantieni il medesimo archivio dati scelto e riavvia il backend, oltre al browser.
Vedere `UPDATE-IT.txt` e `WINDOWS-CHECK-IT.txt` nel pacchetto.

I precedenti ZIP, checksum e tag restano invariati. La versione segue la
numerazione 1.0.0; le correzioni successive useranno 1.0.x, le nuove funzionalità
compatibili 1.x.0. Non viene aggiunto il suffisso preview alla release corrente.
Il registro [GITHUB-NEXT-RELEASE-IT.md](GITHUB-NEXT-RELEASE-IT.md) accompagna
la preparazione per GitHub; la pubblicazione richiede un'istruzione separata.
