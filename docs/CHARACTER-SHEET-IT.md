# Character sheet: una descrizione unica del personaggio

Versione stabile **1.0.0**, 22 novembre 2026. L’utente ha confermato dal PC
che la nuova analisi non cita più i pannelli. Controllare comunque fedeltà
e dettagli di ogni proposta; la conferma non è una garanzia su tutte le immagini.

L'analisi deve descrivere direttamente un solo personaggio: viso, capelli,
corporatura visibile, abiti, scarpe, accessori e segni distintivi. Tutte le parti
dell'immagine contribuiscono, comprese quelle piccole e inferiori, ma il risultato
è un unico paragrafo inglese coerente, secondo il livello Compact/Medium/Full
scelto. Ogni caratteristica va menzionata una volta sola, senza inventare dettagli
nascosti o risolvere arbitrariamente informazioni contraddittorie.

Le istruzioni non elencano più i layout possibili: privilegiano la descrizione
della persona e dei suoi indumenti. Non devono comparire numeri dei riquadri,
viste frontali/laterali, pose, bordi, didascalie del template o commenti sul foglio.
Restano validi «il logo sul retro della giacca» e «la cicatrice sull'avambraccio
sinistro»: sono posizioni sul personaggio, non riferimenti alla disposizione
dell'immagine. Le scritte realmente stampate sugli abiti restano da conservare.

Se il controllo riconosce commenti su riquadri o viste, l'analisi restituisce un
errore e nessun testo applicabile. La descrizione corrente rimane intatta. Non
vengono tagliate frasi, riscritta la risposta o avviati tentativi automatici.
Il controllo è lessicale: non certifica la qualità o la completezza semantica
di una risposta del modello. La proposta valida va sempre controllata dall'utente.

## Come provarla

1. Nella versione Windows 1.0.0, apri Immagini e la Picture con il character sheet.
2. Usa ruolo Identità o Aspetto, categoria Personaggio (anche risolta da Auto)
   e il livello desiderato. Occorre il file originale caricato e un modello
   vision già verificato. Il proxy non sostituisce l'originale per questa analisi.
3. Nella nuova area Descrizione scegli **Tipo di analisi → Character sheet** e
   premi **Analizza**. Ogni clic richiede una nuova chiamata vision, senza cache.
   La proposta deve indicare **Character sheet**. I vecchi comandi sotto le
   ricevute sono sostituiti dal selettore esplicito e da un solo Analizza.
4. Controlla che la proposta descriva una sola persona in un unico paragrafo,
   integrando anche dettagli provenienti da altre parti dell'immagine e senza
   menzionare i riquadri. Verifica manualmente fedeltà, colori e scritte.
5. Premi **Usa questa descrizione** solo se il testo è corretto; correggi se
   necessario, riconferma e salva. L'analisi da sola non cambia i campi.
6. Se ricevi ancora l'errore sui riquadri/viste, la descrizione precedente è
   conservata: puoi riprovare esplicitamente o scrivere la descrizione manuale.

Cache schede: `vision-character-sheet-v6-unified-1280`. Quella dell'analisi
ordinaria resta invariata. Descrizioni già applicate, correzioni manuali,
ricevute con avvisi, prompt e snapshot storici non vengono riscritti.

Verifiche locali con sei layout sintetici e risposte simulate: immagine intera,
una chiamata, rifiuto dei commenti, conservazione di scritte e posizioni sul corpo,
cache distinta e applicazione esplicita. Confronto reale Medium e successiva conferma dell’utente dal browser Windows
registrati il 22 novembre. Non è stata ripetuta una nuova installazione Windows dello ZIP.

[English](CHARACTER-SHEET-EN.md).

Flusso completo, Scarta e storico: [DESCRIPTION-WORKFLOW-IT.md](DESCRIPTION-WORKFLOW-IT.md).
