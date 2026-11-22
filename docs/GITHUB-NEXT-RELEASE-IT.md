# Registro GitHub — versione 1.0.0

Rilascio stabile numerato del 22 novembre 2026. English: [GITHUB-NEXT-RELEASE-EN.md](GITHUB-NEXT-RELEASE-EN.md).

L'utente ha confermato dal PC Windows, dopo il riavvio del backend Mac, che
Scarta funziona e che la nuova analisi character sheet non cita più i pannelli.
Ha quindi autorizzato il consolidamento della release, eliminando il suffisso
preview dalla versione corrente. Le versioni precedenti restano immutate.

## Contenuto da integrare

- Descrizioni condivise per UUID fra bozze compatibili nella stessa scena aperta.
- Libreria accessibile con edit non salvati, ricaricamento selettivo e barra fissa.
- Character sheet v6 con descrizione unica, controllo delle viste e cache distinta.
- Un solo Analizza, selettore esplicito, proposta unica e storico chiuso.
- Scarta persistente tramite dismiss, rimozione immediata e ripristino su errore.
- Limite di tre analisi per cut/Picture, incluse traduzioni e tentativi falliti;
  eliminazione delle più vecchie già autorizzata, con protezione di file e testi.
- Guide IT/EN e note [RELEASE-1.0.0-IT.md](RELEASE-1.0.0-IT.md).

## Validazione e consegna

421 test Python eseguiti (uno saltato su Mac), 111 JavaScript superati.
Scarta verificato sul backend reale, sulla LAN e dopo un secondo riavvio:
cut invariati salvo revisione, versioni/snapshot conservati e hash media intatti.
La conferma utente riguarda il browser Windows collegato al backend Mac;
non viene dichiarata una nuova installazione Windows del nuovo ZIP numerato.

La ricetta pubblicabile è autonoma: allowlist e riferimento runtime aggiornati,
nessuna dipendenza da vecchi ZIP o dalla cronologia privata. Il pacchetto stabile
Windows mantiene il runtime accettato e gli avvii/dipendenze già collaudati.
Il manifesto del pacchetto identifica hash e provenienza; i report di verifica
accompagnano la consegna. MIT, copyright aledige, documentazione in entrambe le lingue.

## Pubblicazione separata

**Nessun push o pubblicazione GitHub eseguito.** Il consolidamento locale e la
consegna Drive non autorizzano la pubblicazione. La base pubblica controllata
in sola lettura è `aledige63/MiniMax-H3-Compiler-Lite`, main,
`5e7d59cd02fe71666063a401144821f7ca780036`. Patch, sorgenti e manifesti revisionati
sono preparati per una successiva istruzione di pubblicazione.

Non importare cronologia privata, handoff locale, dati, media, chiavi, modelli,
report di inferenze o materiali esterni. Conservare tutti i vecchi ZIP/tag.
Stage resta nel piano futuro. Linux escluso; nessun nuovo installer Mac richiesto.
