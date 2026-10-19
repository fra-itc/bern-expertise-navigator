# Interactive pitch and guided presentation

## Commercial experience

The pitch focuses on company ambitions, complementary expertise and a concrete
invitation to Bern. It does not discuss competitors. Existing verified partner
claims, citations and source links are preserved. When Apertus is reachable it
curates up to three existing selected partner IDs against the ambition and
evidence; new entities or unsupported claims cannot be added by that step.
Deterministic fallback is retained and `curation_by` records the actual method.

After generation the representative sees the commercial preview and a compact
side overview/map. Detailed rationale stays expandable. The recipient's shared
brief starts with a 4.5-second sourced ecosystem animation that can be skipped;
reduced motion bypasses animation. The map remains expandable afterward. It
uses the curated partners, not fabricated connections. The 4.5 seconds describe
presentation time, not AI/source-processing latency.

Optional company accent color and explicitly uploaded PNG/JPEG logo are set in
the pitch panel. Raster uploads are bounded, decoded and normalized on the
server; no automatic remote logo retrieval occurs. The PDF uses the same brand,
curated partners and linked sources. The shareable brief token also grants PDF
access, as intended for the recipient. Do not put confidential notes in a shared
brief. Private Knowledge Base passages are not automatically published there.

## Optional email delivery

The normal email-client path remains available. Server delivery is disabled
unless the operator configures:

```text
SMTP_HOST=smtp.example.org
SMTP_PORT=587
SMTP_FROM=approved-sender@example.org
SMTP_USER=approved-account
SMTP_PASSWORD=<secret stored outside git>
PITCH_PUBLIC_BASE_URL=https://your-public-pitch-host.example
```

Use the approved mail account. The explicit Send email with PDF button submits
the reviewed subject/body and attaches the server-generated PDF. SMTP uses
STARTTLS with certificate verification. No message is sent automatically upon
generation or deployment. The email body must contain the configured public
HTTPS pitch link; localhost is not sent to an external recipient.

The private delivery ledger in `NAV_DATA_DIR/delivery.db` stores idempotency keys,
content fingerprints and pending/sent/uncertain outcomes. Repeating the same key
does not resend. Uncertain acknowledgements are not retried automatically; an
operator must verify the delivery outcome. The mail preparation view displays
the recent delivery history. Tests use a fake SMTP transport, never real mail.

## Jury presentation and local voice

The header play icon opens seven visual scenes in EN/DE/FR covering purpose,
two operator roles, Knowledge Base, company ambitions, source-backed matching
and Analytics, pitch, and Apertus. Narration is optional and reads exactly the
visible slide heading/body. It can be paused/resumed and stops on slide changes.

Voice is synthesized locally using [Piper](https://github.com/OHF-Voice/piper1-gpl).
CLI contract: [official source](https://github.com/OHF-Voice/piper1-gpl/blob/main/src/piper/__main__.py).
The speech service is optional and membership-protected. Configure:

```text
SPEECH_PIPER_PYTHON=/path/to/isolated/piper-runtime/python
SPEECH_MODEL_EN=/path/to/en_US-lessac-medium.onnx
SPEECH_MODEL_DE=/path/to/de_DE-thorsten-medium.onnx
SPEECH_MODEL_FR=/path/to/fr_FR-siwis-medium.onnx
```

Install `piper-tts` in an isolated Python environment and download the matching
voices with `python -m piper.download_voices --download-dir <path> <voice names>`.
Voice models require their `.onnx.json` companion files. Review the engine and
individual voice model licenses when packaging/distributing. No browser cloud
speech API is used. Engine, models and generated temporary audio stay outside
version control. The local demo is configured with all three voices; all three
returned valid audio responses in a real smoke test. This is text-to-speech
narration; microphone dictation is a separate future task.

## Validation and limits

25 Python checks cover the involved API/workflow, PDF, SMTP simulation, source
selection, access and speech adapter. 17 DOM behavior checks cover the UI,
presentation and map, alongside existing workspace regressions. Actual Piper
EN/DE/FR synthesis passed. Live SMTP and live Apertus were not exercised.
Device/browser visual review remains outstanding because the available browser
automation connection could not be established. No new changes were pushed.


## Reviewed company evidence and stable delivery

The representative can explicitly approve current public company passages from
contextual KB retrieval alongside research partners, including a company-only
pitch. Private documents and notes are excluded. The email summarizes the same
approved pitch items; the page and PDF expose the same numbered evidence.
Regenerating creates a new share token and preserves prior shared versions.
Discovery metrics count candidate use only after its approved saved source is
included in a generated pitch. All contributions remain potential collaboration
opportunities, not commitments, funding offers or guarantees.

Local technical checks cover these boundaries. Full demo rehearsal and real device
visual/accessibility QA are deferred and must be completed before release.
