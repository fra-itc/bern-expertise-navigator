# Private platform Knowledge Base

The staff header places **Knowledge Base** immediately after Search, with a
distinct red accent. It appears only when `/staff/session` reports an approved
canton account. Self-declared team names and email domains do not grant access.
Every `/kb/*` endpoint also enforces membership on the server.

## Account configuration

Local preview only: set `KB_INTERNAL_PREVIEW=1` and bind to `127.0.0.1` with
`--no-proxy-headers` to assume an internal canton user without login. This mode
accepts only direct loopback clients and is disabled by default. Do not enable
it behind a production proxy. The current local demo uses this mode at the
project owner's request.

No accounts or passwords are shipped. The provisional local-account adapter is
disabled until the administrator explicitly provisions users. Existing identity
provider integration (SSO/BE-Login) remains to be agreed with the project owner;
the prototype's old name-only staff identity is not such an identity provider.

From `src/app`, provision an approved user interactively:

```powershell
../.venv/Scripts/python.exe -m navigator.knowledge_access --file ../data/kb-accounts.json --email officer@example.org --name "Approved officer"
$env:KB_ACCOUNTS_FILE = (Resolve-Path ../data/kb-accounts.json).Path
$env:PYTHONUTF8 = '1'
../.venv/Scripts/python.exe -m uvicorn navigator.api:app --host 127.0.0.1 --port 8080
```

`src/data` is git-ignored. Restrict file access to the server operator. Accounts
must be approved based on actual canton membership. Disable a user by setting
`active` to false; every authenticated request rechecks the file. Passwords use
salted scrypt hashes. Sessions use signed HttpOnly, SameSite=Strict cookies,
Secure on HTTPS, expire after eight hours and are invalidated on restart.
Production needs HTTPS and the project's chosen identity provisioning/SSO
workflow. There is no self-registration or automatic email-domain admission.

The login is at `#/staff/access`, also linked from the identity screen.

## Workflow

Add company → name → progressively revealed website/social URL fields →
documents → notes → Save and process. Record the company's canton explicitly.
Entries can be edited, retried or deleted. The tree groups overview, sources,
documents, notes and suggested partners. The profile uses the existing company
analysis/Apertus pipeline, with its existing rules fallback. Knowledge Base
ingestion does not search for partners; that action belongs to lead creation.

Both lead creation modes offer `Bern only` (default) or `Bern and nearby northern
Switzerland`. The selection is persisted on the lead and filters private company
retrieval server-side. The extended canton allowlist is Bern, Solothurn, Aargau,
Basel-Stadt, Basel-Landschaft, Zurich and Lucerne. Southern cantons and companies
without a recorded canton are excluded. Existing entries need their canton
completed before they can participate. The current public research index still
covers Bern institutions; selecting an extended area does not invent new data.

Document extraction reuses the existing parser: extracted content and metadata
are persisted; original file binaries are not retained. Website ingestion uses
the existing bounded reader with robots.txt and public-address checks. Blocked
social sites can be supplemented with pasted notes or uploaded documents. A
source failure is shown without discarding other usable sources.

Knowledge is stored in `NAV_DATA_DIR/knowledge.db` (SQLite, including when the
public index uses Postgres). Back up this private volume separately. Editing
invalidates old retrieval passages immediately; late processing tasks cannot
overwrite a newer revision or restore deleted content. Jobs run in-process;
after a server restart an interrupted entry needs an explicit Edit / retry.

## Private retrieval

Authenticated staff lead pages show source-backed private context from the new
Knowledge Base, using passage keyword overlap. This context does not enter the
public `/search`, public case responses or shared executive briefs. It is not
yet a new semantic/vector index or an automatic source for public pitches.
Extending AI-generated pitch claims to private sources needs an agreed sharing
policy and source-verification changes; those are not silently enabled here.

## Validation

## Analytics and guide

`#/staff/analytics` uses the same canton membership gate as the Knowledge Base.
Companies can be classified by recorded sector and topics in the company form.
Bar charts show actual counts, including unclassified records. Generated profile
keywords are displayed separately as suggestions requiring review. Lead company
names are deduplicated after case/whitespace normalization; this is not a legal
company-identity registry. Companies with no name are excluded from lead counts.

Contact metrics use the recorded lead statuses/events. Opportunity,
collaboration and establishment outcomes are entered by staff via private
`/kb/leads/{id}/progress`, with an evidence note required for confirmed
collaborations/establishments. They are human-recorded outcomes, not automated
certifications or predicted success rates. There is no automatic verification
of an entered confirmation. Outcome records are stored in the private SQLite
database separately from public case responses.

Analytics links to the existing sourced-pitch workflow. Saving a PDF uses the
browser's print/save dialog; an officer attaches that file in their email client.
No email is sent and no attachment is silently generated or transmitted.

The header's `?` button opens a seven-step native dialog in the selected EN/DE/FR
language. It explains the purpose, Knowledge Base, leads/geography, source
verification, pitch/PDF/email, analytics and future capabilities. Native dialog
behavior provides modal focus and Escape-to-close; closing restores focus to
the help button. Device-level visual QA remains outstanding.

`tests/test_knowledge.py` covers server authorization, document upload, source
failure, background processing, matching, editing/deletion and stale jobs.
`tests/ui-workspace.test.cjs` covers menu gating/order, progressive links and the
company save payload, along with the previous workspace regression checks.


## Contextual retrieval and candidate discovery

`PRIVATE_SEMANTIC_EMBEDDINGS=1` enables local multilingual passage embeddings.
Set `PRIVATE_EMBED_MODEL` to a pre-downloaded SentenceTransformer model directory
(for example `intfloat/multilingual-e5-small`). Loading is local-only; private
passages are never sent to an embedding API. Keep this separate from the public
index model. CPU setup uses sentence-transformers 3.3.1, transformers 4.46.3 and
PyTorch 2.5.1 CPU. If unavailable, results explicitly report concept expansion.
Similarity supports retrieval, not a probability of partnership or success.

Discovery is available from each lead and Analytics. Configure
`DISCOVERY_SEARXNG_URL` with your operator-controlled SearXNG `/search` endpoint
with JSON responses enabled for autonomous public discovery. Search queries are
capability-oriented; review the data policy of the configured search service.
Without a provider, operators can supply public company URLs for source reading.
Company reads retain the existing robots/public-IP restrictions.

Extracted fields require exact source quotes; unsupported values remain red.
An operator must confirm name, URL, canton and proposed complementarity before
approval. Optional uncertain fields can be omitted. Approval opens an unsaved KB
draft; only an explicit save registers it. Counts in Analytics are recorded events,
not certified unique legal entities or claims of commercial success. Pitch use is
recorded when an approved candidate's saved public evidence is actually published.

## Two server-enforced roles

Provision accounts with `python -m navigator.knowledge_access --file <private-file>
--email <email> --name <name> --role agent` (or `representative`). Existing accounts
without a role default to Agent. Both roles enrich leads and knowledge. Only the
Representative creates pitches, prepares invitation email, records outcomes or
sends mail. Unauthenticated users cannot access `/cases`. The signed preview-role
switch works only with explicit `KB_INTERNAL_PREVIEW=1` and loopback access;
production users cannot promote themselves. Keep preview disabled in deployment.

## Original documents and deployment storage

New uploads through `/kb/documents` retain the original bytes and extracted text.
Old parse-only uploads cannot be reconstructed; re-upload them if needed.
`NAV_DATA_DIR/private-originals` is outside static assets, uses random identifiers,
SHA-256 integrity checks and protected attachment-only download routes. Referenced
files cannot be deleted through the API; references include both leads and KB.
Originals are never attached to recipient pitches automatically.

This is private application storage, not encryption at rest. Before deployment,
use an encrypted volume/object store, service-only filesystem ACLs (especially on
Windows), HTTPS, private account/config files, encrypted backups with restore tests,
retention rules and malware scanning. Run parsers in a constrained service/container
and set upload/request limits at the proxy. Staged unreferenced uploads can be
removed by an operator using `vault.cleanup(referenced_ids())`; it retains files
newer than one day. No background deletion is enabled. Never commit `src/data`.

## Sharing evidence

Only explicitly selected current public web passages enter a recipient pitch.
The server resolves IDs and revisions from storage and rejects stale passages,
private notes/documents and companies outside the lead's selected geography.
Published links preserve an immutable version shared by page and PDF. Regeneration
creates a new token; deleting the lead withdraws its stored published versions.
A bearer link can be forwarded: send it only to intended recipients.
