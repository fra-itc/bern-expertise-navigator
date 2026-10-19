# Report di revisione — 19 ottobre 2026

## Risultato

La piattaforma dispone di un percorso completo dalla conoscenza del territorio al pitch documentato. Il tutorial introduttivo resta di sette scene. Alla fine apre un secondo percorso di sette scene su architettura e strumenti, in EN/DE/FR, con ritorno al primo percorso. La narrazione locale legge gli stessi testi; il copione personalizzato resta rinviato.

La proposta commerciale valorizza obiettivi, supporto e complementarità. Le fonti pubblicabili richiedono approvazione esplicita; non si dichiarano accordi, finanziamenti o numeri inventati.

## Lavorazioni incluse

- Branding Canton Bern, font locali, tema chiaro/scuro, logo adattato, texture e footer compatto.
- Knowledge Base privata con aziende, link progressivi, documenti, note, settori e topic.
- Discovery da lead o URL: proposte da rivedere, campi incerti rossi, conferma/correzione/omissione; nessun censimento automatico.
- Matching contestuale con modello locale E5 e capacità complementari, perimetro Berna o zone vicine del nord svizzero.
- Analytics su portafoglio, esiti registrati e attività discovery; suggerimenti separati dagli esiti effettivi.
- Due ruoli controllati sul server: agente e rappresentante. Anteprima locale distinta dagli account reali.
- Pitch con passaggi pubblici selezionati, sommario per l’operatore, mappa animata e branding del destinatario.
- PDF con evidenze e link, pagine pubblicate stabili per versione, email coerente con il pitch e invio SMTP con deduplica.
- Conservazione originali, verifica SHA-256, download autenticato e blocco della cancellazione dei file referenziati.
- Presentazione introduttiva e percorso tecnico, narrazione locale Piper, istruzioni di configurazione e deployment.

## Controlli eseguiti

104 test Python superati; 8 test PostgreSQL saltati perché il database di test non è configurato. Una deprecazione Starlette/AnyIO non bloccante resta nel test runner.

21 test DOM dell’interfaccia superati. Comprendono le tre lingue, caricamento/errori e ripristino, accesso KB, campi candidati e passaggio introduzione/percorso tecnico/ritorno/chiusura.

La nuova prova integrata usa database temporanei e dati esplicitamente fittizi: documento originale → lead → discovery da URL → conferma candidata → draft → salvataggio KB → matching contestuale → approvazione fonte → pitch → pagina pubblica → PDF → bozza email → invio simulato → deduplica. Verifica anche l’esclusione del documento privato dal pitch e la protezione dell’originale referenziato. La fonte web e il recapito SMTP sono sostituiti da confini di test controllati. Nessuna email reale inviata.

La prova del modello semantico locale ha classificato una fonte di validazione clinica prima di una fonte estranea. Non costituisce una valutazione statistica della qualità del matching.

## Verifiche non concluse

Il browser automatico non può collegarsi: il bridge della sessione risulta indisponibile. Non è quindi verificato l’aspetto su desktop, Android, iPhone e iPad, nei due temi, né l’effettiva esperienza da tastiera o la resa visiva del PDF. I test DOM non sostituiscono queste verifiche.

Apertus non è disponibile nell’istanza locale; il fallback è operativo. SearXNG e SMTP non sono configurati per la prova reale. L’indice di ricerca pubblico locale contiene zero entità: va popolato prima della demo pubblica; il percorso KB privato è stato provato su dati temporanei. Dettatura al microfono ancora da implementare.

## Prima del push e del rilascio

Completare verifica visiva e tastiera quando il browser sarà collegabile; provare servizi reali con configurazione approvata e dati rappresentativi; predisporre identità, HTTPS, storage cifrato, ACL, backup e scansione malware per il deployment. La gestione applicativa degli originali non equivale a cifratura a riposo.

Le modifiche restano locali. Nessun nuovo push, merge o messaggio esterno effettuato. Prachi mantiene revisione e decisione di integrazione. Il push è subordinato alla conferma dell’utente dopo la revisione di questi esiti.


## Aggiornamento: revisione mirata prima del push

La successiva revisione ha riprodotto tre bug non coperti dalla regressione precedente: pannello pitch KB nascosto dopo ricarica, perdita delle fonti KB alla rigenerazione e riepilogo/explainer incoerenti dopo l’arricchimento KB. Vedere `docs/bugs-review-2026-10-19.md`. Push sospeso; i difetti sono aperti e non sono stati corretti durante questa revisione.


## Aggiornamento dopo la verifica dei materiali locali

BUG-01, BUG-02 e BUG-03 sono stati corretti. Il pannello mostra i pitch salvati dopo ricarica. Le approvazioni KB sono conservate nel lead privato e ripristinate nell’interfaccia; la rigenerazione risolve nuovamente ID e revisione. Omettere la selezione conserva le approvazioni precedenti, mentre una lista esplicitamente vuota le rimuove. Fonti modificate richiedono nuova revisione. I riferimenti privati non sono aggiunti alla pagina pubblica. Riepilogo ed explainer sono aggiornati dopo l’arricchimento KB in tutte e tre le lingue.

Verifica finale locale: 110 test Python e 22 test DOM superati; 8 test PostgreSQL saltati senza database di test. Test della pipeline completa, fonti, PDF, email simulata e originali inclusi. Tutti gli script JavaScript superano il controllo di sintassi. I servizi esterni non configurati sono dipendenze di deployment, non errori della verifica locale.
