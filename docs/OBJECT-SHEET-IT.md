# Scheda oggetto: una descrizione da più viste

Disponibile dalla release **1.1.0**. [English](OBJECT-SHEET-EN.md).

Una Picture può contenere più raffigurazioni dello stesso oggetto: ad esempio
un veicolo visto davanti, dietro, di lato, dall’alto e in dettaglio. La nuova
modalità **Scheda oggetto · più viste** integra l’intera immagine in un’unica
descrizione inglese dell’oggetto, senza elencare viste, riquadri o impaginazione.
Non crea più auto o nuovi Subject dal numero di raffigurazioni.

## Uso

1. Carica la scheda completa come file originale della Picture.
2. Scegli il ruolo **Oggetto** e lascia la categoria **Dal ruolo dell’immagine**,
   oppure scegli esplicitamente **Oggetto / oggetto impugnato**. Il ruolo
   **Aspetto** è compatibile solo con questa categoria scelta esplicitamente.
3. Scegli Compact, Medium o Full nelle opzioni di analisi.
4. Seleziona **Tipo di analisi → Scheda oggetto · più viste**, poi **Analizza**.
   Il modello vision deve essere selezionato e già verificato. Il cambio dei
   menu non avvia inferenze; ogni Analizza richiede una nuova chiamata.
5. Controlla la proposta e premi **Usa questa descrizione** solo se corretta,
   quindi riconferma. L’associazione al Subject Oggetto resta esplicita.

L’analisi usa l’originale intero, ridotto soltanto per l’invio al vision a un
massimo di 1280 px per lato; ignora eventuali proxy. Il file originale e quello
destinato a H3 rimangono intatti. Non ritaglia la prima vista e non richiede un
numero o una disposizione particolare delle viste.

Le istruzioni privilegiano sagoma, proporzioni, colore, materiali visibili,
componenti e dettagli distintivi. Per un veicolo includono carrozzeria, porte,
vetri, tetto, ruote, fari, griglia e finiture quando visibili. Loghi e scritte
realmente sull’oggetto restano descrivibili; caption e numeri del foglio sono
esclusi. Non si inventano marca, modello, anno, misure o parti nascoste.

Commenti riconosciuti sulle viste o sull’impaginazione producono un errore,
senza testo applicabile, riscrittura o tentativi automatici. Riferimenti alle
parti fisiche, come fari posteriori, tetto e specchietti retrovisori, sono validi.
Il controllo lessicale non garantisce fedeltà o completezza: la revisione umana
rimane necessaria, soprattutto per dettagli piccoli e scritte.

Il task `image_object_sheet` e la cache `vision-object-sheet-v1-unified-1280`
sono distinti dall’analisi ordinaria e dal character sheet v6. Scarta, applicazione
esplicita e protezione dai risultati tardivi seguono il flusso esistente. Le tre
analisi più recenti per cut/Picture comprendono anche le schede oggetto.
Descrizioni salvate, prompt, snapshot, associazioni e file restano conservati;
non serve una migrazione SQLite.

Verifiche con immagini sintetiche e risposte simulate: nessuna inferenza reale
sull’immagine allegata, nessuna prova H3. Per un foglio contenente oggetti
diversi non usare questa modalità come riconoscimento o associazione automatica.

[Flusso Descrizione](DESCRIPTION-WORKFLOW-IT.md) · [Character sheet](CHARACTER-SHEET-IT.md)
