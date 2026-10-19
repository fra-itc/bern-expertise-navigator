# Add the Canton Bern knowledge-to-pitch workspace

Staff need to turn documented ecosystem capabilities into a concise invitation for a prospective company. This contribution adds a private Knowledge Base, reviewed discovery candidates, contextual complementary matching, portfolio Analytics and a source-backed pitch with an interactive recipient page, versioned PDF and optional SMTP delivery.

The Canton Bern visual identity, light/dark themes and responsive controls provide a consistent interface. Agents enrich leads and knowledge; Representatives prepare and send pitches. Public KB excerpts require explicit approval of the current source revision. Original uploads remain private, and recipient pages retain their published version when a new pitch is generated.

A seven-scene introductory presentation is followed by a seven-scene technical walkthrough in English, German and French. It explains the actual modules, open components and configuration requirements; local Piper can narrate slide text.

## Validation

- 104 Python tests passed; 8 PostgreSQL tests skipped without a configured test database.
- 21 DOM tests passed, including all three technical walkthrough languages.
- Isolated company/source/lead/discovery/KB/matching/pitch/PDF/email pipeline passed with controlled web and SMTP boundaries. No real email sent.
- Local semantic model smoke test passed.

## Open validation and deployment requirements

Real browser/device/keyboard QA and PDF visual review are pending because the browser bridge is unavailable. Live Apertus, autonomous SearXNG and real SMTP are not validated in this environment. Populate the public research index before the public demo. Microphone dictation is not implemented. Provision production identities, HTTPS, encrypted private storage, service ACLs, backups and malware scanning before deployment.

Review and merge remain Prachi’s responsibility. This is prepared text only; no new push or merge has been performed.


## Known bugs found in pre-push review

The user explicitly authorized pushing this review state with three open bugs: a KB-only pitch panel becomes hidden after reload; regeneration can drop approved KB sources; and the operator summary/explainer can retain pre-enrichment counts. Reproduction and impact are documented in `docs/bugs-review-2026-10-19.md`. These issues must be addressed before merge/release.


## Aggiornamento dopo la verifica dei materiali locali

BUG-01, BUG-02 e BUG-03 sono stati corretti. Il pannello mostra i pitch salvati dopo ricarica. Le approvazioni KB sono conservate nel lead privato e ripristinate nell’interfaccia; la rigenerazione risolve nuovamente ID e revisione. Omettere la selezione conserva le approvazioni precedenti, mentre una lista esplicitamente vuota le rimuove. Fonti modificate richiedono nuova revisione. I riferimenti privati non sono aggiunti alla pagina pubblica. Riepilogo ed explainer sono aggiornati dopo l’arricchimento KB in tutte e tre le lingue.

Verifica finale locale: 110 test Python e 22 test DOM superati; 8 test PostgreSQL saltati senza database di test. Test della pipeline completa, fonti, PDF, email simulata e originali inclusi. Tutti gli script JavaScript superano il controllo di sintassi. I servizi esterni non configurati sono dipendenze di deployment, non errori della verifica locale.
