# Mapping delle guide Video e apertura coerente

Disponibile dalla release **1.1.0**. [English](GUIDE-MAPPING-EN.md).

Una prova con una guida Stage ha mostrato un blocco bianco conservato
accanto all’auto. Nel primo prompt il mapping era presente, ma collegava il
proxy soprattutto al movimento; una frase generata aggiungeva inoltre una
seconda apertura con il personaggio già in scena. La prova dell’utente con un
prompt corretto ha eliminato il blocco. Non è un confronto a seed e impostazioni
controllati e non dimostra precisione geometrica o fedeltà universale di H3.

## Nuove compilazioni

- Le definizioni dei Subject mappati separano le sorgenti: aspetto e identità
  dalle Picture o dal contesto confermato; posizione, orientamento e movimento
  dalla figura dichiarata nel Video. Nessun Subject viene creato per una sagoma.
- Le istruzioni della guida specificano la sostituzione del proxy sul posto,
  dalla sua prima comparsa, con l’aspetto del Subject assegnato. Le sagome non
  sono oggetti aggiuntivi. Non viene analizzato semanticamente il video.
- Il testo inglese incollato nel Prompt guida resta identico ed è inserito una
  sola volta; il modello non lo riscrive. Slot e numeri Subject sono risolti dai
  mapping del cut, senza numeri fissati da Stage.
- Una riga esplicita `Opening:`, `Opening frame:` o `Opening composition:`
  nel testo di una guida movimento Subject/combinata viene fornita al modello
  come apertura autorevole. Non si deducono presenze o secondi con un parser
  della narrazione e non si trasferisce l’aspetto del proxy.
- Il modello non deve aggiungere una seconda apertura per gli stessi Subject
  né nel racconto né nel summary. Se la richiesta è interamente coperta dalla
  guida, il piano può contenere il solo evento guida. Azioni aggiuntive, dialoghi
  e shot richiesti rimangono eventi espliciti. Conflitti essenziali richiedono
  una domanda, senza una proposta parziale.
- Un controllo lessicale rifiuta le seconde aperture riconosciute nelle parti
  generate, anche quando seguono il testo guida. Non rimuove frasi, non corregge
  parole e non effettua retry. Le scritte citate e le battute restano dati
  autorevoli. Il controllo non certifica la coerenza semantica di ogni risposta.

Guide sola camera, Picture guida, cut senza guida attiva e Video privi di una
riga d’apertura mantengono il proprio percorso. I mapping movimento ricevono
le istruzioni esplicite sulle sorgenti; il controllo della seconda apertura
si attiva solo quando una guida movimento dichiara la propria apertura.

## Conservazione e prova

Non serve una migrazione SQLite. Il renderer viene usato per le nuove versioni:
lettura, copia ed export dei vecchi prompt restituiscono il testo memorizzato.
Snapshot, versioni manuali, associazioni e file non sono ricalcolati dallo stato
corrente. Nessuna nuova compilazione viene avviata all’apertura del cut.

Per ottenere una nuova proposta, aprire il cut e premere **Compila/Ricompila**.
Controllare il risultato prima della prova H3; la versione precedente rimane
disponibile nello storico.
