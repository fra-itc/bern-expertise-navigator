# Bug report prima del push — 19 ottobre 2026

Stato attuale: BUG-01, BUG-02 e BUG-03 corretti e verificati. I paragrafi di riproduzione sotto documentano il comportamento precedente.

Al momento della scoperta, il push era sospeso. La regressione esistente passava (104 test Python; 8 PostgreSQL saltati), ma la revisione mirata ha riprodotto i seguenti difetti. I test diagnostici sono su dati temporanei e non hanno modificato i dati dell’utente. Nessuna correzione applicata in questa revisione.

## BUG-01 — P1 — Pitch KB esistente nascosto dopo ricarica

Dove: `src/app/navigator/static/app.js`, `stepOf` (riga 1001) e `officerPitch` (riga 1142).

Riproduzione: generare un pitch con sole aziende KB e nessun partner di ricerca selezionato, lasciando il lead nello stato new; ricaricare la pagina del lead.

Risultato: le selezioni `S.kbSelections` erano solo in memoria. Lo step ritorna a 2, il pannello pitch si blocca e non mostra anteprima, PDF, email o rigenerazione, anche se `outreach.brief` esiste. La pagina pubblica già generata resta disponibile: il contenuto non è cancellato.

Atteso: un pitch salvato resta consultabile dopo ricarica. La selezione delle fonti va gestita separatamente dalla visibilità dell’output già pubblicato.

Prova: test DOM diagnostico riprodotto su un lead con `matches=[]` e `outreach.brief` presente; `#pitchBox` e `#prepBrief` risultano assenti.

## BUG-02 — P1 — Rigenerazione perde le fonti KB approvate

Dove: `src/app/navigator/static/app.js`, invio `knowledge_sources` (riga 1216); `src/app/navigator/api.py`, `prepare_brief` (righe 331–352).

Riproduzione: generare un pitch misto con un partner di ricerca selezionato e un’azienda KB approvata; riaprire la pagina e rigenerare.

Risultato: le selezioni KB non sono conservate nel lead. Il frontend invia una lista vuota e il server genera con successo una versione che contiene solo il partner di ricerca. L’azienda sparisce senza avviso. Nel caso KB-only, una richiesta senza le selezioni temporanee restituisce HTTP 400.

Atteso: conservare i riferimenti approvati in modo privato e risolvere nuovamente ID/revisione prima di rigenerare, oppure richiedere esplicitamente una nuova selezione. Una fonte cambiata deve richiedere revisione, senza essere pubblicata automaticamente né rimossa senza avviso. La rimozione intenzionale di tutte le fonti deve essere distinta dall’assenza di una selezione nella richiesta.

Prova: API isolata, primo pitch con partner di ricerca + Materials Lab; rigenerazione HTTP 200 con Materials Lab assente. Confermato HTTP 400 per rigenerazione KB-only senza selezioni.

## BUG-03 — P2 — Riepilogo e spiegazione incoerenti con aziende KB

Dove: `src/app/navigator/knowledge_workflow.py`, `enrich` (righe 38–47).

Riproduzione: generare un pitch con una sola azienda KB approvata.

Risultato: `brief.items` contiene l’azienda e le statistiche vengono incrementate, ma `summary.text` resta quello costruito prima dell’arricchimento: “0 selected connections”. Anche l’explainer mantiene testo e conteggi precedenti, perché viene generato prima dell’aggiunta delle aziende.

Atteso: ricalcolare riepilogo ed explainer a partire dagli stessi elementi effettivamente pubblicati, in tutte e tre le lingue.

Prova: test API isolato, un elemento pubblicato e riepilogo con zero connessioni.

## Limiti del controllo

I controlli DOM e API non verificano la resa visiva reale. Browser automatico ancora indisponibile; desktop, Android, iPhone, iPad, tastiera e PDF visivo restano da verificare. Apertus, SearXNG e SMTP reali non sono stati validati; l’indice pubblico locale è vuoto. Queste condizioni sono già documentate nel report generale e non vengono confuse con i tre bug riprodotti sopra.


## Autorizzazione al push

Dopo la segnalazione dei tre bug, l’utente ha richiesto esplicitamente il push dello stato corrente. I difetti restano aperti: questo invio al branch di lavoro è per revisione e non costituisce approvazione al merge o al rilascio.


## Aggiornamento dopo la verifica dei materiali locali

BUG-01, BUG-02 e BUG-03 sono stati corretti. Il pannello mostra i pitch salvati dopo ricarica. Le approvazioni KB sono conservate nel lead privato e ripristinate nell’interfaccia; la rigenerazione risolve nuovamente ID e revisione. Omettere la selezione conserva le approvazioni precedenti, mentre una lista esplicitamente vuota le rimuove. Fonti modificate richiedono nuova revisione. I riferimenti privati non sono aggiunti alla pagina pubblica. Riepilogo ed explainer sono aggiornati dopo l’arricchimento KB in tutte e tre le lingue.

Verifica finale locale: 110 test Python e 22 test DOM superati; 8 test PostgreSQL saltati senza database di test. Test della pipeline completa, fonti, PDF, email simulata e originali inclusi. Tutti gli script JavaScript superano il controllo di sintassi. I servizi esterni non configurati sono dipendenze di deployment, non errori della verifica locale.
