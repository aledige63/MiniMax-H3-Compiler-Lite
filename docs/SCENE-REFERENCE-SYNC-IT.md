# Riferimenti condivisi nella scena

Correzione del 21 novembre 2026, richiesta dopo il conflitto sul Subject 4
fra cut 1 e cut 2 della stessa scena. Riproduzione su dati sintetici;
l'archivio Windows dell'utente non è stato acquisito né modificato.

Salvando una descrizione di Subject o Picture, le bozze degli altri cut della
stessa scena aperta che usano lo stesso UUID ricevono la descrizione aggiornata.
Questo supera la precedente regola del ricaricamento sempre esplicito. Anche
le bozze rimaste indietro vengono riallineate alla lettura, purché un cut della
stessa scena contenga il riferimento corrente della libreria. Una modifica
proveniente solo da un'altra scena non basta.

Restano locali richiesta, battute, esclusioni, slot Picture, guida e dichiarazione
del collegamento H3. La sincronizzazione non aggiunge immagini mancanti, non cambia
ruoli o sorgenti e non ricollega file/proxy. Subject derivati da contesto storico
e scene chiuse conservano i propri dati. Non viene concessa automaticamente una
conferma mancante. Il salvataggio non chiama il modello.

Testi, versioni, snapshot, basi manuali, risultati e ingressi dei job già avviati
restano invariati. La bozza aggiornata va ricompilata per ottenere un nuovo prompt.
Gli altri cut possono tornare allo stato di bozza conservando la versione
precedentemente confermata.

Prima del salvataggio il browser recupera la revisione corrente e unisce solo
gli aggiornamenti descrittivi compatibili con le modifiche locali. Due modifiche
diverse allo stesso campo restano un conflitto recuperabile. I conflitti reali
di revisione dello stesso cut restano protetti.

«Dalla libreria del progetto» si apre senza richiedere il salvataggio preventivo.
Il pulsante compare in Immagini e Subject, in una barra separata dalla creazione
di nuovi elementi e fissa in alto durante lo scorrimento delle due sezioni.
Il ricaricamento esplicito sostituisce il riferimento scelto, conservando gli
altri campi locali e il testo manuale non salvato. Prima di ricaricare il campo
in conflitto, copiare il testo locale che si desidera conservare.

La consegna Windows è la versione stabile 1.0.0. Pubblicazione GitHub separata;
gli ZIP precedenti restano invariati. Vedere
`WINDOWS-CHECK-IT.txt` nel nuovo ZIP per backup, prova e ripristino.

[English](SCENE-REFERENCE-SYNC-EN.md).
