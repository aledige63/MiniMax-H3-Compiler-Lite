# Descrizione della Picture: flusso semplificato

Versione stabile **1.0.0**, 22 novembre 2026. Scarta e character sheet confermati
dall’utente sul browser Windows dopo l’allineamento del backend Mac.

## Cosa cambia

La Picture contiene una sola area **Descrizione**. Il testo modificabile è quello
in uso: modificarlo manualmente rimane sempre possibile. La nuova proposta è
separata dal testo in uso e non lo sostituisce automaticamente.

Accanto a **Analizza** scegli esplicitamente **Immagine singola** oppure
**Character sheet**. Il secondo tipo richiede ruolo Identità/Aspetto, categoria
Personaggio e file originale caricato; il proxy non lo sostituisce. La modalità
è una scelta dell'interfaccia e non cambia il ruolo o le associazioni H3.
Le opzioni categoria, livello, attributo e vista sono in **Opzioni di analisi**,
chiuso inizialmente; il profilo attuale è riassunto accanto ai comandi.

Ogni clic su Analizza richiede esplicitamente una nuova analisi, senza riusare
una risposta dalla cache. Non ci sono pulsanti diversi per ripetere una vecchia
analisi: il tipo visibile governa sempre la nuova richiesta. Mentre un'analisi
della Picture è in coda o in corso, il comando e il selettore del tipo sono
bloccati; descrizione e testo manuale restano modificabili.

## Una proposta attuale

Compare al massimo una proposta attuale per Picture. **Usa questa descrizione**
la applica, toglie la conferma della Picture e la sposta nello storico. Il testo
applicato resta da controllare e confermare. Non modifica il testo manuale del cut.

**Scarta** toglie subito la proposta dalla vista e mostra un messaggio accanto
alla descrizione, mentre salva la scelta. Se il salvataggio fallisce, ripristina
la proposta e mostra lì l'errore. Lo scarto sposta la proposta nello storico senza cambiare descrizione, media,
versioni o snapshot. La scelta è salvata nell'archivio e resiste al riavvio.
Non è una cancellazione del risultato. Campi locali non salvati restano intatti.
Una proposta scartata non è più applicabile tramite il vecchio comando API.

Usare o scartare una proposta non fa riapparire una proposta più vecchia.
Se cambia il riferimento, il tipo di analisi o il profilo, la vecchia proposta
resta nello storico. I lavori attivi rimangono visibili e annullabili. Un errore
mostra il proprio messaggio senza sostituire la descrizione né promuovere un
risultato precedente. Per riprovare usa il solo pulsante Analizza.

## Storico e traduzione

**Storico delle proposte** è chiuso inizialmente. Contiene risultati precedenti,
profili diversi, proposte applicate/scartate e ricevute storiche. È consultabile:
non avvia analisi, non cambia campi e non offre comandi per applicare risultati
vecchi. Si conservano **al massimo tre analisi complessive per cut/Picture**,
compresa l'eventuale proposta attuale. Analisi immagine, character sheet,
traduzioni e tentativi falliti condividono il limite. Le analisi più vecchie
vengono eliminate dal registro, non soltanto nascoste, e non sono più consultabili.
La pulizia avviene anche all'avvio sugli archivi esistenti. Per le tre ricevute
conservate testi, avvisi e metriche restano intatti. I lavori ancora attivi non
vengono eliminati: rientrano nel limite al termine. Prove vision, ASR, file,
descrizioni già salvate, prompt e snapshot non vengono eliminati.

**Traduci in inglese** compare solo quando la lingua della descrizione è diversa
dall'inglese. Anche la traduzione produce una proposta da usare o scartare.
Richiede un modello testo disponibile, selezionato nelle Impostazioni.

## Prova sul PC

1. Segui `WINDOWS-CHECK-IT.txt`: backup verificato e copia ripristinata di prova.
2. Apri una Picture con vecchie analisi. Controlla una sola proposta attuale e
   lo storico chiuso. Le proposte obsolete devono restare nello storico.
3. Scrivi una descrizione e un testo manuale senza salvarli. Premi Scarta sulla
   proposta attuale: entrambi i testi devono restare. Salva e riavvia: la proposta
   deve rimanere nello storico, senza farne comparire una precedente. La proposta
   deve sparire subito, anche se il server impiega tempo a rispondere.
4. Scegli Character sheet, controlla categoria Personaggio e premi Analizza.
   Verifica il tipo indicato nella proposta e la descrizione unica della persona.
   Il clic chiama il modello vision; cambiare selettore o aprire lo storico no.
5. Premi Usa questa descrizione: cambia solo il campo Descrizione della Picture,
   da riconfermare. Controlla che il testo manuale del cut resti intatto.
6. Prova Immagine singola e verifica che il nuovo risultato indichi quel tipo.
7. Cambia lingua da Inglese a Italiano: deve comparire Traduci in inglese.
   Tornando a Inglese deve scomparire, senza traduzioni automatiche.
8. Cambia livello nelle opzioni: la vecchia proposta va nello storico. Controlla
   che aprire storico/opzioni non salvi dati o chiami il modello.
9. Su una Picture con molte analisi precedenti controlla che dopo l'avvio ne
   restino soltanto tre, inclusa l'attuale. Le precedenti non saranno recuperabili
   dall'app; effettua prima il backup dalla vecchia installazione come indicato
   nella guida Windows.

Le protezioni contro risultati tardivi, bozze locali, scene chiuse e revisioni
concorrenti restano attive. Nessuna migrazione SQLite o modifica ai prompt salvati.
Il collaudo funzionale dal browser Windows è confermato. Non viene dichiarata
una nuova installazione nativa dello ZIP; controllare ogni descrizione sul proprio riferimento.
