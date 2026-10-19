# Demo priorities — issue #1

Tracking: https://github.com/Bizzo88/bern-expertise-navigator/issues/1

Implementation: Bizzo88. Review, validation and merge decisions: Prachi Kedar.
Priorities and component ownership still need Prachi's confirmation. Work in
small PRs; the entire backlog is not required for the first demo.

## P0 — interface and core demo workflow

- [x] First typography and spacing pass with local system fonts and responsive controls.
- [x] Search company requests by company, needs, location or specialty.
- [x] Show a recoverable loading failure instead of an apparently empty lead list.
- [x] Announce pitch generation, preserve the previous output on failure and allow retry.
- [x] Restore partner-search controls after failure without losing the query.
- [x] Localize new UI messages in English, German and French.
- [x] Identify the user-supplied branding reference: https://www.be.ch/de/start.html.
- [x] Apply its logo, favicon, Roboto fonts, red/black/white/beige palette and institutional footer links locally.
- [ ] Confirm organization-specific footer contact details and any additional brand guidelines with the client.
- [ ] Visually validate desktop/mobile layouts, dark mode, contrast and keyboard navigation.
- [ ] Agree on representative fictional leads/documents and rehearse the complete demo.

## P1 — administration and Knowledge Base

- [ ] Agree on company/lead resource schema and API ownership before parallel implementation.
- [x] Add an expandable private company tree with websites/social links, extracted documents and notes.
- [x] Add/edit/delete company entries, their links, notes and extracted document contents.
- [x] Process company knowledge with the existing AI/rules profile pipeline; partner search belongs to lead creation.
- [x] Show processing status, source failures and source-backed private context on authenticated lead pages.
- [x] Reflect edits/deletion in private retrieval and enforce canton membership on server endpoints.
- [x] Retain original documents in protected private storage and add local semantic passage retrieval.
- [x] Require explicit approval of current public web passages; private notes/documents stay out of external pitches.

## P1/P2 — roles

- [x] Define the two functional roles: Sales Agent enriches leads/knowledge; Representative reviews matches and prepares pitches.
- [x] Enforce Agent and Representative workflows; role switching exists only in explicit loopback preview.
- [x] Protect staff cases on the server; restrict pitch creation, sending and outcomes to Representatives.
- [x] Enforce access to the new Knowledge Base via explicitly provisioned canton accounts (disabled until configured).
- [ ] Confirm identity provider/provisioning with the project owner and enable approved accounts; see `docs/knowledge-base.md`.

## Commercial presentation

- [x] Analytics with sectors, recorded/suggested topics and staff-evidenced lead outcomes.
- [x] CEO pitch focused on ambitions and complementary expertise, with compact operator overview.
- [x] Source-backed animated ecosystem map, skip/reduced motion and optional uploaded company branding.
- [x] PDF download with branding and sources; optional SMTP delivery with idempotency and delivery history.
- [x] Seven-scene jury presentation with play icon and EN/DE/FR local Piper narration.
- [ ] Configure an approved public URL/email account and validate live SMTP only when authorized.
- [ ] Validate live Apertus curation and evaluate its benefit against the fallback.
- [ ] Add open-model microphone dictation as a separate feature.
- [ ] Review the new visual flows on desktop/mobile and prepare a final end-to-end demo.

## Validation for the first UI contribution

JavaScript syntax: `node --check src/app/navigator/static/app.js`.

Optional DOM behavior checks require Node and `jsdom@26`. Install jsdom in an
external tooling directory (not an application dependency), set `NODE_PATH` to
that directory's `node_modules`, and run:

```powershell
$env:NODE_PATH = 'C:/path/to/ui-tools/node_modules'
node --test src/tests/ui-workspace.test.cjs
```

The checks cover request filtering/clearing and safe rendering, three languages,
load failure/retry, pitch failure recovery and partner-search recovery. They use
mocked API responses and do not validate layout, live AI or production access controls.

## Discovery and contextual matching

- [x] Lead-driven discovery with Bern / nearby northern scope, public source evidence and candidate drafts.
- [x] Autofill supported values; mark uncertain fields with a red square and require operator confirmation or omission.
- [x] Export approved candidates to an unsaved Knowledge Base form; never register automatically.
- [x] Analytics records actual searches, candidates, approvals, rejections and candidate use in generated pitches.
- [x] Use local multilingual embeddings with complementary capability expansion and an explicit fallback.
- [x] Preserve published pitch versions: regenerating creates a new link; previous page/PDF content stays stable.
- [ ] Configure an operator-controlled SearXNG JSON endpoint for autonomous discovery. Explicit public URLs work without it.
- [ ] Deployment: encrypted private storage, service ACLs, backup/restore, malware scanning and identity provisioning.

Full demo rehearsal and real desktop/Android/iPhone/iPad visual QA remain deferred at the user's request.
Changes remain local pending review; no new push or merge has been performed.


## Review pass — 19 October 2026

- [x] Preserve introductory tutorial and append a seven-scene technical EN/DE/FR walkthrough, using the same narration pipeline.
- [x] Run isolated company-to-email demo pipeline with controlled public-source and SMTP boundaries.
- [x] Run regression: 104 Python tests passed, 8 PostgreSQL tests skipped, 21 DOM tests passed.
- [x] Prepare report, review text, WhatsApp draft and Excel change register.
- [ ] Real device/browser/keyboard and PDF visual QA: blocked by unavailable browser bridge.
- [ ] Validate configured external services and load the currently empty public research index.
- [ ] Obtain user confirmation before pushing the prepared changes.


- [x] Fix and regress KB-only pitch reload, preservation of approved KB sources and post-enrichment summary/explainer in EN/DE/FR. Final local suite: 110 Python + 22 DOM tests passed.
