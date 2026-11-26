# Usare l’export di Stage con il Compiler

Disponibile da Compiler **1.1.0** con l’output di **Stage 0.9.0** e successive
versioni che mantengono questo formato. [English](STAGE-EN.md).
Stage: https://github.com/aledige63/Stage/releases/tag/v0.9.0.

1. In Stage esportare l’MP4 e **Prompt per MiniMax Compiler** (`_compiler.txt`).
2. Nel Compiler definire i Subject finali e le relative Picture. Per una scheda
   multivista dell’auto scegliere il tipo **Scheda oggetto · più viste**.
3. In Video caricare l’MP4, scegliere **Guida camera + Subject** se contiene
   entrambi i movimenti e attivare **Usa questa guida nel cut**. Usare **Guida sola
   camera** quando non si devono trasferire posizioni o movimenti dei Subject.
4. Associare separatamente le figure: per esempio `the red mannequin` al
   personaggio e `the white box` all’auto. I numeri Subject e Video sono quelli
   del cut; non devono necessariamente essere 1 e 2.
5. Incollare soltanto il corpo narrativo di `_compiler.txt` in **Prompt guida ·
   inglese**, entro 2.500 caratteri. Non incollare le sezioni dell’esempio Ref2VA.
6. Confermare descrizione, ruolo, durata, mapping e collegamento H3. Impostare
   la durata del cut coerente con la guida. Un Video guida attivo deve durare
   2–15 s; tutti i Video attivi insieme non possono superare 15 s.
7. Lasciare il movimento del menu Regia non specificato quando è guidato dal
   Video. Scrivere la richiesta narrativa e compilare. Controllare la proposta.
8. Collegare Picture e MP4 agli stessi slot nel workflow MiniMax H3 esterno e
   usare il prompt finale a sei sezioni prodotto dal Compiler.

Aspetto e identità provengono dalle Picture del Subject. Posizione, orientamento,
traiettoria e tempi provengono dal proxy dichiarato nella guida; la sagoma viene
sostituita dal Subject e non aggiunta come un oggetto separato. Le figure devono
essere distinguibili per descrizione, colore o forma.
L’ambiente può essere un Subject **Ambiente** associato a una terza Picture:
non richiede un mapping nel Video se la guida non contiene una figura dedicata.

Il testo guida rimane identico e compare una volta. Un’apertura esplicita della
guida governa i Subject mappati; le seconde aperture riconosciute vengono
rifiutate senza riparazioni o tentativi automatici. Il modello può chiedere una
scelta se la richiesta contraddice la guida. La fedeltà visiva e le traiettorie
H3 restano da controllare: il prompt non è un vincolo geometrico certificato.

Il Compiler archivia l’MP4 per la consultazione ma non lo invia al modello chat,
non avvia H3 e non importa automaticamente MP4/TXT/JSON come pacchetto unico.
Caricare o cambiare menu non avvia inferenze. Le versioni già salvate restano
intatte; una nuova proposta richiede Compila/Ricompila.
