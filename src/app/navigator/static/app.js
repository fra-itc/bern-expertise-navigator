/* Bern Expertise Navigator — vanilla JS, no dependencies (runs air-gapped).
 *
 * Three clearly separated areas:
 *   PUBLIC  #/ , #/search, #/directory          — the navigator from the brief, for anyone
 *   STAFF   #/staff/...                          — canton business development: request → partners → pitch & invite
 *   BRIEF   #/b/<token>                          — the executive brief a CEO receives (read-only, printable)
 */
(() => {
  "use strict";

  /* ======================= utilities ======================= */
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => (s ?? "").toString().replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };
  const isNarrow = () => matchMedia("(max-width: 1100px)").matches;
  const hostPath = (u) => { try { const x = new URL(u); return x.hostname.replace(/^www\./, "") + x.pathname.replace(/\/index_\w+\.html$|\/$/, ""); } catch { return u; } };
  function toast(msg, ms = 2400) { const el = $("#toast"); el.textContent = msg; el.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), ms); }
  const go = (h) => { if (location.hash !== h) location.hash = h; else route(); };
  const briefUrl = (token) => `${location.origin}${location.pathname}#/b/${token}`;

  const DOC_ACCEPT = ".pdf,.docx,.docm,.pptx,.pptm,.xlsx,.xlsm,.odt,.odp,.ods,.rtf,.txt,.md,.csv,.html,.htm,.eml,.doc,.ppt,.xls";
  const DOC_MAX_MB = 25;
  const ICON = {
    plus: '<svg class="i" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    back: '<svg class="i" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    unit: '<svg viewBox="0 0 24 24"><path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6"/></svg>',
    project: '<svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3"/><path d="M7 15h10"/></svg>',
    infrastructure: '<svg viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/></svg>',
    link: '<svg class="i" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>',
    ext: '<svg class="i" viewBox="0 0 24 24"><path d="M14 3h7v7M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>',
    file: '<svg class="i" viewBox="0 0 24 24"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/></svg>',
    x: '<svg class="i" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    check: '<svg class="i" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
    mail: '<svg class="i" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    cal: '<svg class="i" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    copy: '<svg class="i" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
    info: '<svg class="i" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>',
    shield: '<svg class="i" viewBox="0 0 24 24"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    send: '<svg class="i" viewBox="0 0 24 24"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/></svg>',
    inbox: '<svg class="i" viewBox="0 0 24 24"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/></svg>',
    sparkle: '<svg class="i" viewBox="0 0 24 24"><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/></svg>',
    trash: '<svg class="i" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"/></svg>',
    briefcase: '<svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/></svg>',
    microscope: '<svg viewBox="0 0 24 24"><path d="M6 18h8M3 22h18M14 22a7 7 0 1 0 0-14h-1M9 14h2M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2zM12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/></svg>',
    lock: '<svg class="i" viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
    moon: '<svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
    doc: '<svg class="i" viewBox="0 0 24 24"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></svg>',
    printer: '<svg class="i" viewBox="0 0 24 24"><path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7"/></svg>',
    eye: '<svg class="i" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  };

  /* ======================= i18n ======================= */
  const I18N = {
    en: {
      "m.sourcesLead": "structured and traceable: who, where, what, why — with the original pages",
      "src.function": "Function",
      "src.aff": "Affiliation",
      "src.contact": "Contact",
      "src.expertise": "Expertise",
      "src.projects": "Projects & activities",
      "src.infra": "Infrastructure & services",
      "src.about": "About",
      "src.why": "Why it matches",
      "src.link": "Source page",
      "m.sources": "Sources",
      "skip": "Skip to content", "lang.label": "Language", "theme": "Dark mode",
      "ai.on": "Apertus AI active", "ai.off": "Rules mode · no AI",
      "ai.onT": "Apertus, the Swiss open language model, helps interpret requests and write plain-language summaries. Every fact shown is quoted from a public source.",
      "ai.offT": "The AI model is not reachable. Summaries and matches come from a reviewed glossary and fixed rules; nothing is generated.",
      "prov.apertus": "Summary written by Apertus (AI). Check it against the sources analysed below.",
      "prov.rules": "Summary from the reviewed glossary and fixed rules (no AI).",
      "prov.ai": "AI-written", "prov.rule": "Rules",
      "prov.offer": "Built only from the indexed fields of the cited sources (no AI). Every [n] links to its public page.",
      "prov.searchAi": "Apertus helped interpret the query. Quotes and sources are verbatim from public pages.",
      "prov.searchRules": "Keyword and meaning search, no AI. Quotes and sources are verbatim from public pages.",
      "foot.proto": "Prototype (Hack Apertus 2026). Not an official service of the Canton of Bern.",
      "col.todoD": "Choose partners", "col.readyD": "Send the invitation", "col.doneD": "Follow up",
      "col.none": "No match", "col.noneD": "No Bern assets found yet",
      "bs.short": "Enter at least 3 characters.",
      "u.sources": "Sources analysed",
      "u.kw": "Key business keywords",
      "u.offer": "Solutions & offerings",
      "brand.sub": "Research & expertise in Bern", "brand.staffSub": "Staff workspace", "brand.briefSub": "Executive brief",
      "nav.search": "Search", "nav.dir": "Labs & facilities", "nav.staff": "Staff workspace",
      "nav.requests": "Requests", "nav.new": "New request", "nav.public": "Public site",
      "staff.tag": "Staff", "who.switch": "Change person", 
      "foot.public": "Information from the public websites of the University of Bern, the ARTORG Center and Diabetes Center Berne. Every result links to its source.",
      "foot.staff": "Staff workspace (prototype): identities are self-declared, no passwords. Requests are stored locally and never sent anywhere by the server.",
      "foot.brief": "Prepared with the Bern Expertise Navigator. Every statement links to its public source.",
      "home.title": "Find the people, labs and facilities behind Bern's research",
      "home.lead": "One search across the University of Bern, the ARTORG Center and Diabetes Center Berne. Use your own words — every result is structured and linked to the public page that supports it.",
      "ph": "e.g. glucose sensors, robots for neurosurgery, 3D printing service…", "go": "Search",
      "try": "Try", "proof": "Bern in numbers", "proofNote": "quoted verbatim from the institutions' pages",
      "themes": "Research strengths", "themesNote": "based on the institutions' public pages",
      "people": "people", "labsN": "labs", "projects": "projects", "lead": "Lead",
      "home.more": "Browse all labs & facilities", "res.n": "results", "res.also": "also searched for", "res.why": "Why it matches", "res.found": "Found through",
      "f.role": "Role", "f.aff": "Affiliation", "f.exp": "Expertise", "f.proj": "Projects", "f.infra": "Infrastructure & services",
      "f.contact": "Contact", "res.verified": "Source-verified", "res.sources": "sources",
      "res.none": "No answer without a source", "res.noneHint": "The navigator only answers from pages it has indexed, and never guesses names or expertise.",
      "res.select": "Select a result to see every cited source.", "res.open": "Open source page", "res.about": "About",
      "res.linked": "People & linked entities", "res.evidence": "Evidence (verbatim from the source pages)",
      "res.add": "Add to request", "res.added": "Added to the request",
      "flt.sources": "Sources", "flt.types": "Show",
      "type.person": "Person", "type.unit": "Lab / unit", "type.project": "Project", "type.infrastructure": "Facility",
      "t.people": "People", "t.labs": "Labs", "t.projects": "Projects", "t.facilities": "Facilities",
      "dir.title": "Labs & facilities", "dir.lead": "Every research group and every facility found on the indexed websites, with its lead and a link to its page.",
      "dir.labs": "Labs & groups", "dir.fac": "Facilities & services", "dir.all": "All institutions",
      "id.title": "Staff workspace", "id.lead": "Enter your name: it appears in the activity log and as the sender of invitations. Stored only in this browser.",
      "id.name": "Your name", "id.email": "Your email", "id.team": "Team / email signature", "id.enter": "Enter workspace", "id.recent": "Recently used",
      "st.new": "New", 
      "st.contacted": "Invited", "st.call_scheduled": "Call scheduled", "st.closed": "Closed",
      "st.interested": "Company replied", "col.replied": "Replied", "col.repliedD": "The company answered: get back to them",
      "bv.title": "Times the company opened the pitch", "bv.none": "Not opened yet", "bv.seen": "Opened {n}× · last {d}", "bv.until": "Link works until {d}",
      "bv.revoke": "Disable link", "bv.revokeQ": "Disable this link now? The company will no longer be able to open the pitch.",
      "bv.revoked": "Link disabled. Prepare the pitch again to get a new link.", "bv.expired": "Link expired on {d}. Prepare the pitch again to renew it.",
      "rp.title": "The company replied", "rp.visit": "Would like to visit Bern", "rp.call": "Would like a call first",
      "rp.question": "Has a question", "rp.answer": "Answer by email",
      "rq.title": "Company requests", "rq.lead": "Each request follows three steps: company profile → matching Bern assets → pitch and invitation.",
      "kpi.open": "to do", "kpi.ready": "pitch ready", "kpi.invited": "invited",
      "col.todo": "To do", "col.ready": "Pitch ready", "col.done": "Invited",
      "col.empty": "Nothing here", "rq.empty": "No requests yet", "rq.emptyD": "Start from a company's website, its documents or its request, or open one of the fictional examples.",
      "partners": "partners",
      "nw.title": "New company request", "nw.lead": "Paste the company's email or message.",
      "nw.company": "Company", "nw.country": "Country", "nw.contact": "Contact person", "nw.email": "Contact email",
      "nw.text": "What is the company asking for?", "nw.textHint": "any language", "nw.submit": "Understand & find partners",
      "nw.examples": "Fictional examples", "nw.working": "Analysing the request and matching it with Bern's assets…",
      "nw.q": "Which company is it about?", "nw.urlPh": "Company website, e.g. www.example-medtech.com", "nw.info": "…or paste information about the company (email, description)", "nw.infoPh": "Optional when you give the website",
      "nw.need": "Business need (optional)", "nw.needPh": "e.g. clinical validation partner, testing facility, market entry in Switzerland", "nw.missing": "Enter the company's website or paste some information about it.", "nw.reading": "Analysing the company website and matching it with Bern's assets…",
      "nw.docs": "Documents the company shared (pitch deck, brochure…)", "nw.docsHint": "Drop files here or click to choose — PDF, Word, PowerPoint, Excel, OpenDocument, text",
      "nw.pages": "{n} pages/slides", "nw.remove": "Remove", "nw.uploading": "Reading {n} file(s)…", "nw.tooBig": "is larger than {n} MB.",
      "nw.readingDocs": "Analysing the documents and matching them with Bern's assets…", "u.docs": "Documents", "u.docText": "Show the text that was read",
      "u.web": "Company website", "u.info": "Information provided",
      "nw.company2": "Company (optional)", "nw.countryAny": "Company's country", "nw.canton": "Canton", "nw.cantonAny": "All cantons",
      "nw.area": "Medtech area", "nw.niche": "Niche", "nw.any": "Any", "nw.find": "Match with Bern", "nw.try": "Try",
      "rq.untitled": "New request",
      "d.save": "Save details", "d.edit": "Edit",
      "cs.back": "All requests", "cs.backQ": "Review queue", "cs.received": "Received", "cs.contact": "Company contact", "cs.activity": "Activity",
      "cs.delete": "Delete request", "cs.confirmDelete": "Delete this request permanently?",
      "step.1": "Company profile", "step.2": "Bern assets", "step.3": "Pitch & invitation", 
      "u.title": "Company profile",
      "u.does": "Business activity", "u.needs": "Business needs", "u.orig": "Original request",
      "m.title": "What Bern offers", "m.none": "No matching assets were found in the indexed sources.",
      "m.src": "source", 
      "i.title": "Pitch & invite", "i.locked": "No Bern assets were found for this company, so no pitch can be prepared yet.",
      "i.gen": "Generate pitch",
      "i.forYou": "For you", "i.forYouT": "Simplified preface", "i.forCeo": "For the CEO", "i.forCeoT": "Strategic pitch",
      "i.open": "Open the brief", "i.pdf": "Save as PDF", "i.copyLink": "Copy link", "i.copied": "Link copied",
      "i.teams": "potential partners", "i.stmt": "sourced statements", "i.pubs": "publications", "i.srcs": "sources",
      "i.mail": "Send", "i.slots": "Propose call times", "i.dur": "Call length (min)", "i.prepMail": "Prepare the email",
      "i.subj": "Subject", "i.body": "Email (editable)", "i.openMail": "Open in email app", "i.copy": "Copy text", "i.sent": "Mark as sent",
      "i.ics": "Calendar invite (.ics)", "i.doneEmail": "Invitation sent on {d}.", "i.doneCall": "Call scheduled: {d}.",
      "ctx": "Adding partners to the request from {c}", "ctxBack": "Back to the request",
      "bf.prepared": "prepared {d}", "bf.missing": "This brief does not exist or has been withdrawn.", "bf.teams": "research teams",
      "err": "Something went wrong",
      "st.pitch": "Pitch ready",
      "bs.tab": "Broad search",
      "bs.tab2": "Company details",
      "sg.working": "Looking for companies that match…", "sg.title": "Which company do you mean?",
      "sg.lead": "Companies suggested by Apertus for “{q}”, each checked on its own website. The description is the company's own.",
      "sg.choose": "Choose and analyse", "sg.none": "None of these: continue with the search only", "sg.back": "Change the search",
      "sg.place": "names {p} on its website", "sg.topic": "talks about", "sg.ai": "Suggested by Apertus: the model may not know every company, check before contacting one.",
      "nav.dash": "Dashboard", "db.title": "Dashboard", "db.lead": "What Apertus costs per request, and how well the search finds the right experts.",
      "db.priceSet": "Price: CHF {i} per million input tokens and CHF {o} per million output tokens ({m}).",
      "db.priceTodo": "Placeholder price (CHF {i} / CHF {o} per million input / output tokens). Set LLM_PRICE_IN_CHF_PER_M and LLM_PRICE_OUT_CHF_PER_M in .env for real figures.",
      "db.cost": "Cost of Apertus (live)", "db.since": "since {d}",
      "db.noUsage": "No request has called Apertus yet. Figures appear after the first search, company suggestion or new request.",
      "db.perReq": "Cost per request", "db.perReqD": "average over {n} requests", "db.total": "Total cost", "db.totalD": "{n} calls · {t} tokens",
      "db.lat": "Response time", "db.latD": "median · 95th percentile {p}", "db.calls": "Actions using Apertus", "db.callsD": "searches, suggestions, requests",
      "db.byRoute": "By action", "db.byCase": "By request", "db.deleted": "deleted request",
      "db.col.action": "Action", "db.col.req": "Times", "db.col.calls": "Calls", "db.col.tokens": "Tokens", "db.col.cost": "Cost (CHF)",
      "db.col.median": "Median", "db.col.p95": "95th pct.", "db.col.company": "Request", "db.col.last": "Last",
      "db.rx": "Full re-extraction", "db.rxD": "{n} pages · {t} tokens", "db.rxMeasured": "Measured on the last Apertus extraction ({c} calls).",
      "db.rxEstimated": "Estimate: no Apertus extraction has been measured yet, so tokens come from the page length (about 4 characters per token, 600 output tokens per page).",
      "db.quality": "Search quality (golden set)", "db.qualityD": "{q} test queries; each run is saved with make eval TAG=…. Target: recall@10 of at least {t}%.",
      "db.noRuns": "No saved evaluation run yet. Run make eval TAG=rules, and make bench for Apertus.", "db.target": "target {t}%", "db.below": "below target",
      "db.col.run": "Run", "db.col.recall": "Recall@10", "db.col.twins": "Lay-term twins", "db.col.trace": "Traceability", "db.col.abst": "Abstention",
      "db.col.lat": "Latency", "db.col.callsQ": "Calls / query", "db.col.cpq": "Cost / query", "db.noLlm": "no Apertus",
      "db.r.search": "Search", "db.r.suggest": "Company suggestions", "db.r.create": "New request", "db.r.rematch": "Search partners again",
      "db.r.draft": "Draft e-mail", "db.r.brief": "Executive brief", "db.r.matches": "Add partners", "db.r.details": "Request details", "db.r.reply": "Company reply",
      "bs.title": "What are you looking for?",
      "bs.ph": "e.g. glucose company in Milan — in any language",
      "bs.place": "Place",
      "bs.topic": "Topic",
      "bs.searching": "Searching Bern for",
      "bs.hint": "Type a topic, a company type and/or a place.",
      "bs.langs": "Works in English, Deutsch, Français, Italiano and Rumantsch.",
    },
    de: {
      "m.sourcesLead": "strukturiert und nachvollziehbar: wer, wo, was, warum — mit den Originalseiten",
      "src.function": "Funktion",
      "src.aff": "Zugehörigkeit",
      "src.contact": "Kontakt",
      "src.expertise": "Fachgebiete",
      "src.projects": "Projekte & Aktivitäten",
      "src.infra": "Infrastruktur & Dienstleistungen",
      "src.about": "Beschreibung",
      "src.why": "Warum es passt",
      "src.link": "Quellseite",
      "m.sources": "Quellen",
      "skip": "Zum Inhalt springen", "lang.label": "Sprache", "theme": "Dunkelmodus",
      "ai.on": "Apertus-KI aktiv", "ai.off": "Regelmodus · ohne KI",
      "ai.onT": "Apertus, das offene Schweizer Sprachmodell, hilft beim Verstehen von Anfragen und schreibt verständliche Zusammenfassungen. Jede angezeigte Tatsache ist aus einer öffentlichen Quelle zitiert.",
      "ai.offT": "Das KI-Modell ist nicht erreichbar. Zusammenfassungen und Treffer stammen aus einem geprüften Glossar und festen Regeln; nichts wird generiert.",
      "prov.apertus": "Zusammenfassung von Apertus (KI) verfasst. Bitte mit den unten analysierten Quellen abgleichen.",
      "prov.rules": "Zusammenfassung aus dem geprüften Glossar und festen Regeln (ohne KI).",
      "prov.ai": "KI-verfasst", "prov.rule": "Regeln",
      "prov.offer": "Nur aus den indexierten Angaben der zitierten Quellen erstellt (ohne KI). Jede [n] verweist auf ihre öffentliche Seite.",
      "prov.searchAi": "Apertus hat geholfen, die Suche zu verstehen. Zitate und Quellen stammen wörtlich von öffentlichen Seiten.",
      "prov.searchRules": "Stichwort- und Bedeutungssuche, ohne KI. Zitate und Quellen stammen wörtlich von öffentlichen Seiten.",
      "foot.proto": "Prototyp (Hack Apertus 2026). Kein offizielles Angebot des Kantons Bern.",
      "col.todoD": "Partner auswählen", "col.readyD": "Einladung senden", "col.doneD": "Nachfassen",
      "col.none": "Kein Treffer", "col.noneD": "Noch keine Berner Angebote gefunden",
      "bs.short": "Mindestens 3 Zeichen eingeben.",
      "u.sources": "Analysierte Quellen",
      "u.kw": "Zentrale Geschäftsbegriffe",
      "u.offer": "Lösungen & Angebote",
      "brand.sub": "Forschung & Expertise in Bern", "brand.staffSub": "Arbeitsbereich", "brand.briefSub": "Executive Brief",
      "nav.search": "Suche", "nav.dir": "Labore & Infrastruktur", "nav.staff": "Arbeitsbereich",
      "nav.requests": "Anfragen", "nav.new": "Neue Anfrage", "nav.public": "Öffentliche Seite",
      "staff.tag": "Intern", "who.switch": "Person wechseln", 
      "foot.public": "Informationen von den öffentlichen Websites der Universität Bern, des ARTORG Center und des Diabetes Center Berne. Jedes Ergebnis ist mit seiner Quelle verlinkt.",
      "foot.staff": "Arbeitsbereich (Prototyp): Identität selbst angegeben, keine Passwörter. Anfragen werden lokal gespeichert und vom Server nirgends hin gesendet.",
      "foot.brief": "Erstellt mit dem Bern Expertise Navigator. Jede Aussage ist mit ihrer öffentlichen Quelle verlinkt.",
      "home.title": "Die Menschen, Labore und Infrastruktur hinter Berns Forschung finden",
      "home.lead": "Eine Suche über die Universität Bern, das ARTORG Center und das Diabetes Center Berne. In eigenen Worten — jedes Ergebnis ist strukturiert und mit der öffentlichen Quellseite verlinkt.",
      "ph": "z. B. Glukosesensoren, Roboter für die Neurochirurgie, 3D-Druck…", "go": "Suchen",
      "try": "Beispiele", "proof": "Bern in Zahlen", "proofNote": "wörtlich zitiert von den Seiten der Institutionen",
      "themes": "Forschungsstärken", "themesNote": "gemäss den öffentlichen Seiten der Institutionen",
      "people": "Personen", "labsN": "Labore", "projects": "Projekte", "lead": "Leitung",
      "home.more": "Alle Labore & Infrastruktur", "res.n": "Ergebnisse", "res.also": "auch gesucht nach", "res.why": "Warum es passt", "res.found": "Gefunden über",
      "f.role": "Funktion", "f.aff": "Zugehörigkeit", "f.exp": "Fachgebiete", "f.proj": "Projekte", "f.infra": "Infrastruktur & Dienste",
      "f.contact": "Kontakt", "res.verified": "Quelle geprüft", "res.sources": "Quellen",
      "res.none": "Keine Antwort ohne Quelle", "res.noneHint": "Der Navigator antwortet nur aus indexierten Seiten und rät nie Namen oder Fachgebiete.",
      "res.select": "Ergebnis wählen, um alle Belege zu sehen.", "res.open": "Quellseite öffnen", "res.about": "Über",
      "res.linked": "Personen & verknüpfte Einträge", "res.evidence": "Belege (wörtlich von den Quellseiten)",
      "res.add": "Zur Anfrage hinzufügen", "res.added": "Zur Anfrage hinzugefügt",
      "flt.sources": "Quellen", "flt.types": "Zeigen",
      "type.person": "Person", "type.unit": "Labor / Gruppe", "type.project": "Projekt", "type.infrastructure": "Infrastruktur",
      "t.people": "Personen", "t.labs": "Labore", "t.projects": "Projekte", "t.facilities": "Infrastruktur",
      "dir.title": "Labore & Infrastruktur", "dir.lead": "Alle Forschungsgruppen und Infrastrukturen der indexierten Websites, mit Leitung und Link zur Seite.",
      "dir.labs": "Labore & Gruppen", "dir.fac": "Infrastruktur & Dienste", "dir.all": "Alle Institutionen",
      "id.title": "Arbeitsbereich", "id.lead": "Geben Sie Ihren Namen ein: Er erscheint im Verlauf und als Absender der Einladungen. Nur in diesem Browser gespeichert.",
      "id.name": "Ihr Name", "id.email": "Ihre E-Mail", "id.team": "Team / E-Mail-Signatur", "id.enter": "Arbeitsbereich öffnen", "id.recent": "Zuletzt verwendet",
      "st.new": "Neu", 
      "st.contacted": "Eingeladen", "st.call_scheduled": "Gespräch geplant", "st.closed": "Abgeschlossen",
      "st.interested": "Firma hat geantwortet", "col.replied": "Antwort erhalten", "col.repliedD": "Die Firma hat geantwortet: melden Sie sich",
      "bv.title": "So oft hat die Firma den Pitch geöffnet", "bv.none": "Noch nicht geöffnet", "bv.seen": "{n}× geöffnet · zuletzt {d}", "bv.until": "Link gültig bis {d}",
      "bv.revoke": "Link deaktivieren", "bv.revokeQ": "Link jetzt deaktivieren? Die Firma kann den Pitch dann nicht mehr öffnen.",
      "bv.revoked": "Link deaktiviert. Erstellen Sie den Pitch neu, um einen neuen Link zu erhalten.", "bv.expired": "Link am {d} abgelaufen. Erstellen Sie den Pitch neu, um ihn zu verlängern.",
      "rp.title": "Die Firma hat geantwortet", "rp.visit": "Möchte Bern besuchen", "rp.call": "Möchte zuerst ein Gespräch",
      "rp.question": "Hat eine Frage", "rp.answer": "Per E-Mail antworten",
      "rq.title": "Firmenanfragen", "rq.lead": "Jede Anfrage durchläuft drei Schritte: Firmenprofil → passende Berner Angebote → Pitch und Einladung.",
      "kpi.open": "zu erledigen", "kpi.ready": "Pitch bereit", "kpi.invited": "eingeladen",
      "col.todo": "Zu erledigen", "col.ready": "Pitch bereit", "col.done": "Eingeladen",
      "col.empty": "Nichts", "rq.empty": "Noch keine Anfragen", "rq.emptyD": "Starten Sie mit der Website, Dokumenten oder der Anfrage einer Firma – oder öffnen Sie ein fiktives Beispiel.",
      "partners": "Partner",
      "nw.title": "Neue Firmenanfrage", "nw.lead": "Fügen Sie die E-Mail oder Nachricht der Firma ein.",
      "nw.company": "Firma", "nw.country": "Land", "nw.contact": "Kontaktperson", "nw.email": "E-Mail der Kontaktperson",
      "nw.text": "Was sucht die Firma?", "nw.textHint": "jede Sprache", "nw.submit": "Verstehen & Partner finden",
      "nw.examples": "Fiktive Beispiele", "nw.working": "Die Anfrage wird analysiert und mit den Berner Angeboten abgeglichen…",
      "nw.q": "Um welche Firma geht es?", "nw.urlPh": "Website der Firma, z. B. www.beispiel-medtech.ch", "nw.info": "…oder Informationen zur Firma einfügen (E-Mail, Beschreibung)", "nw.infoPh": "Optional, wenn Sie die Website angeben",
      "nw.need": "Geschäftlicher Bedarf (optional)", "nw.needPh": "z. B. Partner für klinische Validierung, Testinfrastruktur, Markteintritt in der Schweiz", "nw.missing": "Geben Sie die Website der Firma an oder fügen Sie Informationen zur Firma ein.", "nw.reading": "Die Website der Firma wird analysiert und mit den Berner Angeboten abgeglichen…",
      "nw.docs": "Dokumente der Firma (Pitch-Deck, Broschüre…)", "nw.docsHint": "Dateien hierher ziehen oder klicken — PDF, Word, PowerPoint, Excel, OpenDocument, Text",
      "nw.pages": "{n} Seiten/Folien", "nw.remove": "Entfernen", "nw.uploading": "{n} Datei(en) werden gelesen…", "nw.tooBig": "ist grösser als {n} MB.",
      "nw.readingDocs": "Die Dokumente werden analysiert und mit den Berner Angeboten abgeglichen…", "u.docs": "Dokumente", "u.docText": "Gelesenen Text anzeigen",
      "u.web": "Website der Firma", "u.info": "Bereitgestellte Informationen",
      "nw.company2": "Firma (optional)", "nw.countryAny": "Land der Firma", "nw.canton": "Kanton", "nw.cantonAny": "Alle Kantone",
      "nw.area": "Medtech-Bereich", "nw.niche": "Nische", "nw.any": "Alle", "nw.find": "Mit Bern abgleichen", "nw.try": "Beispiele",
      "rq.untitled": "Neue Anfrage",
      "d.save": "Angaben speichern", "d.edit": "Bearbeiten",
      "cs.back": "Alle Anfragen", "cs.backQ": "Prüfungen", "cs.received": "Eingegangen", "cs.contact": "Kontakt der Firma", "cs.activity": "Verlauf",
      "cs.delete": "Anfrage löschen", "cs.confirmDelete": "Diese Anfrage endgültig löschen?",
      "step.1": "Firmenprofil", "step.2": "Berner Angebote", "step.3": "Pitch & Einladung", 
      "u.title": "Firmenprofil",
      "u.does": "Geschäftstätigkeit", "u.needs": "Geschäftlicher Bedarf", "u.orig": "Ursprüngliche Anfrage",
      "m.title": "Was Bern bietet", "m.none": "In den indexierten Quellen wurden keine passenden Angebote gefunden.",
      "m.src": "Quelle", 
      "i.title": "Pitch & Einladung", "i.locked": "Für diese Firma wurden keine Berner Angebote gefunden; ein Pitch kann noch nicht vorbereitet werden.",
      "i.gen": "Pitch erstellen",
      "i.forYou": "Für Sie", "i.forYouT": "Vereinfachtes Vorwort", "i.forCeo": "Für die Geschäftsleitung", "i.forCeoT": "Strategischer Pitch",
      "i.open": "Brief öffnen", "i.pdf": "Als PDF speichern", "i.copyLink": "Link kopieren", "i.copied": "Link kopiert",
      "i.teams": "mögliche Partner", "i.stmt": "belegte Aussagen", "i.pubs": "Publikationen", "i.srcs": "Quellen",
      "i.mail": "Versand", "i.slots": "Gesprächstermine vorschlagen", "i.dur": "Dauer (Min.)", "i.prepMail": "E-Mail vorbereiten",
      "i.subj": "Betreff", "i.body": "E-Mail (bearbeitbar)", "i.openMail": "Im E-Mail-Programm öffnen", "i.copy": "Text kopieren", "i.sent": "Als gesendet markieren",
      "i.ics": "Kalendereinladung (.ics)", "i.doneEmail": "Einladung gesendet am {d}.", "i.doneCall": "Gespräch geplant: {d}.",
      "ctx": "Partner für die Anfrage von {c} hinzufügen", "ctxBack": "Zurück zur Anfrage",
      "bf.prepared": "erstellt {d}", "bf.missing": "Dieses Dokument existiert nicht oder wurde zurückgezogen.", "bf.teams": "Forschungsteams",
      "err": "Etwas ist schiefgelaufen",
      "st.pitch": "Pitch bereit",
      "bs.tab": "Freie Suche",
      "bs.tab2": "Angaben zur Firma",
      "sg.working": "Passende Firmen werden gesucht…", "sg.title": "Welche Firma meinen Sie?",
      "sg.lead": "Von Apertus vorgeschlagene Firmen für «{q}», jede auf ihrer eigenen Website geprüft. Die Beschreibung stammt von der Firma selbst.",
      "sg.choose": "Auswählen und analysieren", "sg.none": "Keine davon: nur mit der Suche weiter", "sg.back": "Suche ändern",
      "sg.place": "nennt {p} auf der Website", "sg.topic": "spricht über", "sg.ai": "Von Apertus vorgeschlagen: Das Modell kennt nicht jede Firma, bitte vor einer Kontaktaufnahme prüfen.",
      "nav.dash": "Dashboard", "db.title": "Dashboard", "db.lead": "Was Apertus pro Anfrage kostet und wie gut die Suche die richtigen Fachleute findet.",
      "db.priceSet": "Preis: CHF {i} pro Million Eingabe-Tokens und CHF {o} pro Million Ausgabe-Tokens ({m}).",
      "db.priceTodo": "Platzhalterpreis (CHF {i} / CHF {o} pro Million Eingabe- / Ausgabe-Tokens). Für echte Zahlen LLM_PRICE_IN_CHF_PER_M und LLM_PRICE_OUT_CHF_PER_M in .env setzen.",
      "db.cost": "Kosten von Apertus (live)", "db.since": "seit {d}",
      "db.noUsage": "Noch keine Anfrage hat Apertus aufgerufen. Die Zahlen erscheinen nach der ersten Suche, dem ersten Firmenvorschlag oder der ersten neuen Anfrage.",
      "db.perReq": "Kosten pro Anfrage", "db.perReqD": "Durchschnitt über {n} Anfragen", "db.total": "Gesamtkosten", "db.totalD": "{n} Aufrufe · {t} Tokens",
      "db.lat": "Antwortzeit", "db.latD": "Median · 95. Perzentil {p}", "db.calls": "Aktionen mit Apertus", "db.callsD": "Suchen, Vorschläge, Anfragen",
      "db.byRoute": "Nach Aktion", "db.byCase": "Nach Anfrage", "db.deleted": "gelöschte Anfrage",
      "db.col.action": "Aktion", "db.col.req": "Anzahl", "db.col.calls": "Aufrufe", "db.col.tokens": "Tokens", "db.col.cost": "Kosten (CHF)",
      "db.col.median": "Median", "db.col.p95": "95. Perz.", "db.col.company": "Anfrage", "db.col.last": "Zuletzt",
      "db.rx": "Vollständige Neuextraktion", "db.rxD": "{n} Seiten · {t} Tokens", "db.rxMeasured": "Gemessen bei der letzten Extraktion mit Apertus ({c} Aufrufe).",
      "db.rxEstimated": "Schätzung: Noch keine Extraktion mit Apertus gemessen, daher Tokens aus der Seitenlänge (etwa 4 Zeichen pro Token, 600 Ausgabe-Tokens pro Seite).",
      "db.quality": "Suchqualität (Referenzset)", "db.qualityD": "{q} Testanfragen; jeder Lauf wird mit make eval TAG=… gespeichert. Ziel: Recall@10 von mindestens {t} %.",
      "db.noRuns": "Noch kein gespeicherter Evaluationslauf. make eval TAG=rules ausführen, für Apertus make bench.", "db.target": "Ziel {t} %", "db.below": "unter dem Ziel",
      "db.col.run": "Lauf", "db.col.recall": "Recall@10", "db.col.twins": "Laienbegriffe", "db.col.trace": "Nachvollziehbarkeit", "db.col.abst": "Enthaltung",
      "db.col.lat": "Latenz", "db.col.callsQ": "Aufrufe / Suche", "db.col.cpq": "Kosten / Suche", "db.noLlm": "ohne Apertus",
      "db.r.search": "Suche", "db.r.suggest": "Firmenvorschläge", "db.r.create": "Neue Anfrage", "db.r.rematch": "Partner neu suchen",
      "db.r.draft": "E-Mail-Entwurf", "db.r.brief": "Executive Brief", "db.r.matches": "Partner hinzufügen", "db.r.details": "Anfragedetails", "db.r.reply": "Antwort der Firma",
      "bs.title": "Wonach suchen Sie?",
      "bs.ph": "z. B. Glukose-Firma aus Mailand — in jeder Sprache",
      "bs.place": "Ort",
      "bs.topic": "Thema",
      "bs.searching": "Suche in Bern nach",
      "bs.hint": "Thema, Art der Firma und/oder Ort eingeben.",
      "bs.langs": "Funktioniert auf English, Deutsch, Français, Italiano und Rumantsch.",
    },
    fr: {
      "m.sourcesLead": "structurées et traçables : qui, où, quoi, pourquoi — avec les pages d'origine",
      "src.function": "Fonction",
      "src.aff": "Affiliation",
      "src.contact": "Contact",
      "src.expertise": "Expertise",
      "src.projects": "Projets & activités",
      "src.infra": "Infrastructures & services",
      "src.about": "Description",
      "src.why": "Pourquoi cela correspond",
      "src.link": "Page source",
      "m.sources": "Sources",
      "skip": "Aller au contenu", "lang.label": "Langue", "theme": "Mode sombre",
      "ai.on": "IA Apertus active", "ai.off": "Mode règles · sans IA",
      "ai.onT": "Apertus, le modèle de langage ouvert suisse, aide à comprendre les demandes et rédige des résumés en langage clair. Chaque fait affiché est cité d'une source publique.",
      "ai.offT": "Le modèle d'IA n'est pas joignable. Résumés et résultats proviennent d'un glossaire vérifié et de règles fixes ; rien n'est généré.",
      "prov.apertus": "Résumé rédigé par Apertus (IA). À vérifier avec les sources analysées ci-dessous.",
      "prov.rules": "Résumé issu du glossaire vérifié et de règles fixes (sans IA).",
      "prov.ai": "Rédigé par l'IA", "prov.rule": "Règles",
      "prov.offer": "Construit uniquement à partir des données indexées des sources citées (sans IA). Chaque [n] renvoie à sa page publique.",
      "prov.searchAi": "Apertus a aidé à interpréter la recherche. Citations et sources sont reprises mot pour mot des pages publiques.",
      "prov.searchRules": "Recherche par mots-clés et par sens, sans IA. Citations et sources sont reprises mot pour mot des pages publiques.",
      "foot.proto": "Prototype (Hack Apertus 2026). Pas un service officiel du canton de Berne.",
      "col.todoD": "Choisir les partenaires", "col.readyD": "Envoyer l'invitation", "col.doneD": "Assurer le suivi",
      "col.none": "Aucune correspondance", "col.noneD": "Aucun atout bernois trouvé pour l'instant",
      "bs.short": "Saisissez au moins 3 caractères.",
      "u.sources": "Sources analysées",
      "u.kw": "Mots-clés de l'activité",
      "u.offer": "Solutions & offres",
      "brand.sub": "Recherche & expertise à Berne", "brand.staffSub": "Espace collaborateurs", "brand.briefSub": "Note de direction",
      "nav.search": "Recherche", "nav.dir": "Laboratoires & infrastructures", "nav.staff": "Espace collaborateurs",
      "nav.requests": "Demandes", "nav.new": "Nouvelle demande", "nav.public": "Site public",
      "staff.tag": "Interne", "who.switch": "Changer de personne", 
      "foot.public": "Informations issues des sites publics de l'Université de Berne, de l'ARTORG Center et du Diabetes Center Berne. Chaque résultat renvoie à sa source.",
      "foot.staff": "Espace collaborateurs (prototype) : identité déclarée, sans mot de passe. Les demandes sont stockées localement et jamais envoyées par le serveur.",
      "foot.brief": "Préparé avec le Bern Expertise Navigator. Chaque affirmation renvoie à sa source publique.",
      "home.title": "Trouver les personnes, laboratoires et infrastructures de la recherche bernoise",
      "home.lead": "Une seule recherche sur l'Université de Berne, l'ARTORG Center et le Diabetes Center Berne. Avec vos propres mots — chaque résultat est structuré et lié à la page publique qui le justifie.",
      "ph": "p. ex. capteurs de glucose, robots pour la neurochirurgie, impression 3D…", "go": "Rechercher",
      "try": "Essayer", "proof": "Berne en chiffres", "proofNote": "cités mot pour mot depuis les pages des institutions",
      "themes": "Points forts de la recherche", "themesNote": "d'après les pages publiques des institutions",
      "people": "personnes", "labsN": "laboratoires", "projects": "projets", "lead": "Direction",
      "home.more": "Tous les laboratoires & infrastructures", "res.n": "résultats", "res.also": "également cherché", "res.why": "Pourquoi ce résultat", "res.found": "Trouvé via",
      "f.role": "Fonction", "f.aff": "Rattachement", "f.exp": "Expertise", "f.proj": "Projets", "f.infra": "Infrastructures & services",
      "f.contact": "Contact", "res.verified": "Source vérifiée", "res.sources": "sources",
      "res.none": "Pas de réponse sans source", "res.noneHint": "Le navigateur ne répond qu'à partir des pages indexées et ne devine jamais de noms ni d'expertises.",
      "res.select": "Sélectionnez un résultat pour voir toutes les sources.", "res.open": "Ouvrir la page source", "res.about": "À propos",
      "res.linked": "Personnes et entités liées", "res.evidence": "Preuves (mot pour mot depuis les pages sources)",
      "res.add": "Ajouter à la demande", "res.added": "Ajouté à la demande",
      "flt.sources": "Sources", "flt.types": "Afficher",
      "type.person": "Personne", "type.unit": "Laboratoire", "type.project": "Projet", "type.infrastructure": "Infrastructure",
      "t.people": "Personnes", "t.labs": "Laboratoires", "t.projects": "Projets", "t.facilities": "Infrastructures",
      "dir.title": "Laboratoires & infrastructures", "dir.lead": "Tous les groupes de recherche et infrastructures des sites indexés, avec leur direction et un lien vers leur page.",
      "dir.labs": "Laboratoires & groupes", "dir.fac": "Infrastructures & services", "dir.all": "Toutes les institutions",
      "id.title": "Espace collaborateurs", "id.lead": "Indiquez votre nom : il apparaît dans l'historique et comme expéditeur des invitations. Enregistré uniquement dans ce navigateur.",
      "id.name": "Votre nom", "id.email": "Votre e-mail", "id.team": "Équipe / signature", "id.enter": "Entrer dans l'espace", "id.recent": "Utilisés récemment",
      "st.new": "Nouvelle", 
      "st.contacted": "Invitée", "st.call_scheduled": "Appel planifié", "st.closed": "Close",
      "st.interested": "L'entreprise a répondu", "col.replied": "Réponses", "col.repliedD": "L'entreprise a répondu : recontactez-la",
      "bv.title": "Nombre d'ouvertures du pitch par l'entreprise", "bv.none": "Pas encore ouverte", "bv.seen": "Ouverte {n}× · dernière fois {d}", "bv.until": "Lien valable jusqu'au {d}",
      "bv.revoke": "Désactiver le lien", "bv.revokeQ": "Désactiver ce lien maintenant ? L'entreprise ne pourra plus ouvrir le pitch.",
      "bv.revoked": "Lien désactivé. Préparez à nouveau le pitch pour obtenir un nouveau lien.", "bv.expired": "Lien expiré le {d}. Préparez à nouveau le pitch pour le renouveler.",
      "rp.title": "L'entreprise a répondu", "rp.visit": "Souhaite visiter Berne", "rp.call": "Souhaite d'abord un appel",
      "rp.question": "A une question", "rp.answer": "Répondre par e-mail",
      "rq.title": "Demandes d'entreprises", "rq.lead": "Chaque demande suit trois étapes : profil de l'entreprise → atouts bernois correspondants → pitch et invitation.",
      "kpi.open": "à traiter", "kpi.ready": "pitch prêt", "kpi.invited": "invitées",
      "col.todo": "À traiter", "col.ready": "Pitch prêt", "col.done": "Invitées",
      "col.empty": "Rien", "rq.empty": "Aucune demande", "rq.emptyD": "Commencez par le site web, les documents ou la demande d'une entreprise, ou ouvrez l'un des exemples fictifs.",
      "partners": "partenaires",
      "nw.title": "Nouvelle demande d'entreprise", "nw.lead": "Collez l'e-mail ou le message de l'entreprise.",
      "nw.company": "Entreprise", "nw.country": "Pays", "nw.contact": "Personne de contact", "nw.email": "E-mail de contact",
      "nw.text": "Que cherche l'entreprise ?", "nw.textHint": "toute langue", "nw.submit": "Comprendre et trouver des partenaires",
      "nw.examples": "Exemples fictifs", "nw.working": "Analyse de la demande et mise en correspondance avec les atouts bernois…",
      "nw.q": "De quelle entreprise s'agit-il ?", "nw.urlPh": "Site web de l'entreprise, p. ex. www.exemple-medtech.ch", "nw.info": "…ou collez des informations sur l'entreprise (e-mail, description)", "nw.infoPh": "Facultatif si vous indiquez le site web",
      "nw.need": "Besoin commercial (facultatif)", "nw.needPh": "p. ex. partenaire de validation clinique, infrastructure d'essais, entrée sur le marché suisse", "nw.missing": "Indiquez le site web de l'entreprise ou collez des informations à son sujet.", "nw.reading": "Analyse du site de l'entreprise et mise en correspondance avec les atouts bernois…",
      "nw.docs": "Documents partagés par l'entreprise (pitch deck, brochure…)", "nw.docsHint": "Déposez les fichiers ici ou cliquez — PDF, Word, PowerPoint, Excel, OpenDocument, texte",
      "nw.pages": "{n} pages/diapositives", "nw.remove": "Retirer", "nw.uploading": "Lecture de {n} fichier(s)…", "nw.tooBig": "dépasse {n} Mo.",
      "nw.readingDocs": "Analyse des documents et mise en correspondance avec les atouts bernois…", "u.docs": "Documents", "u.docText": "Afficher le texte lu",
      "u.web": "Site web de l'entreprise", "u.info": "Informations fournies",
      "nw.company2": "Entreprise (facultatif)", "nw.countryAny": "Pays de l'entreprise", "nw.canton": "Canton", "nw.cantonAny": "Tous les cantons",
      "nw.area": "Domaine medtech", "nw.niche": "Niche", "nw.any": "Tous", "nw.find": "Rechercher à Berne", "nw.try": "Essayer",
      "rq.untitled": "Nouvelle demande",
      "d.save": "Enregistrer", "d.edit": "Modifier",
      "cs.back": "Toutes les demandes", "cs.backQ": "Validations", "cs.received": "Reçue", "cs.contact": "Contact de l'entreprise", "cs.activity": "Historique",
      "cs.delete": "Supprimer la demande", "cs.confirmDelete": "Supprimer définitivement cette demande ?",
      "step.1": "Profil de l'entreprise", "step.2": "Atouts bernois", "step.3": "Pitch & invitation", 
      "u.title": "Profil de l'entreprise",
      "u.does": "Activité", "u.needs": "Besoins commerciaux", "u.orig": "Demande originale",
      "m.title": "Ce que Berne offre", "m.none": "Aucun atout correspondant n'a été trouvé dans les sources indexées.",
      "m.src": "source", 
      "i.title": "Pitch & invitation", "i.locked": "Aucun atout bernois n'a été trouvé pour cette entreprise ; le pitch ne peut pas encore être préparé.",
      "i.gen": "Générer le pitch",
      "i.forYou": "Pour vous", "i.forYouT": "Préface simplifiée", "i.forCeo": "Pour la direction", "i.forCeoT": "Pitch stratégique",
      "i.open": "Ouvrir la note", "i.pdf": "Enregistrer en PDF", "i.copyLink": "Copier le lien", "i.copied": "Lien copié",
      "i.teams": "partenaires potentiels", "i.stmt": "affirmations sourcées", "i.pubs": "publications", "i.srcs": "sources",
      "i.mail": "Envoi", "i.slots": "Proposer des créneaux d'appel", "i.dur": "Durée (min)", "i.prepMail": "Préparer l'e-mail",
      "i.subj": "Objet", "i.body": "E-mail (modifiable)", "i.openMail": "Ouvrir dans la messagerie", "i.copy": "Copier le texte", "i.sent": "Marquer comme envoyé",
      "i.ics": "Invitation calendrier (.ics)", "i.doneEmail": "Invitation envoyée le {d}.", "i.doneCall": "Appel planifié : {d}.",
      "ctx": "Ajout de partenaires à la demande de {c}", "ctxBack": "Retour à la demande",
      "bf.prepared": "préparée le {d}", "bf.missing": "Cette note n'existe pas ou a été retirée.", "bf.teams": "équipes de recherche",
      "err": "Une erreur est survenue",
      "st.pitch": "Pitch prêt",
      "bs.tab": "Recherche libre",
      "bs.tab2": "Détails de l'entreprise",
      "sg.working": "Recherche d'entreprises correspondantes…", "sg.title": "De quelle entreprise s'agit-il ?",
      "sg.lead": "Entreprises proposées par Apertus pour « {q} », chacune vérifiée sur son propre site. La description est celle de l'entreprise.",
      "sg.choose": "Choisir et analyser", "sg.none": "Aucune : continuer avec la recherche seule", "sg.back": "Modifier la recherche",
      "sg.place": "mentionne {p} sur son site", "sg.topic": "parle de", "sg.ai": "Proposées par Apertus : le modèle ne connaît pas toutes les entreprises, vérifiez avant tout contact.",
      "nav.dash": "Tableau de bord", "db.title": "Tableau de bord", "db.lead": "Ce que coûte Apertus par demande, et dans quelle mesure la recherche trouve les bons experts.",
      "db.priceSet": "Prix : CHF {i} par million de tokens d'entrée et CHF {o} par million de tokens de sortie ({m}).",
      "db.priceTodo": "Prix provisoire (CHF {i} / CHF {o} par million de tokens d'entrée / de sortie). Définissez LLM_PRICE_IN_CHF_PER_M et LLM_PRICE_OUT_CHF_PER_M dans .env pour des chiffres réels.",
      "db.cost": "Coût d'Apertus (en direct)", "db.since": "depuis le {d}",
      "db.noUsage": "Aucune demande n'a encore appelé Apertus. Les chiffres apparaissent après la première recherche, suggestion d'entreprise ou nouvelle demande.",
      "db.perReq": "Coût par demande", "db.perReqD": "moyenne sur {n} demandes", "db.total": "Coût total", "db.totalD": "{n} appels · {t} tokens",
      "db.lat": "Temps de réponse", "db.latD": "médiane · 95e centile {p}", "db.calls": "Actions utilisant Apertus", "db.callsD": "recherches, suggestions, demandes",
      "db.byRoute": "Par action", "db.byCase": "Par demande", "db.deleted": "demande supprimée",
      "db.col.action": "Action", "db.col.req": "Fois", "db.col.calls": "Appels", "db.col.tokens": "Tokens", "db.col.cost": "Coût (CHF)",
      "db.col.median": "Médiane", "db.col.p95": "95e cent.", "db.col.company": "Demande", "db.col.last": "Dernière",
      "db.rx": "Ré-extraction complète", "db.rxD": "{n} pages · {t} tokens", "db.rxMeasured": "Mesuré lors de la dernière extraction avec Apertus ({c} appels).",
      "db.rxEstimated": "Estimation : aucune extraction avec Apertus n'a encore été mesurée, les tokens sont donc déduits de la longueur des pages (environ 4 caractères par token, 600 tokens de sortie par page).",
      "db.quality": "Qualité de la recherche (jeu de référence)", "db.qualityD": "{q} requêtes de test ; chaque essai est enregistré avec make eval TAG=…. Objectif : un rappel@10 d'au moins {t} %.",
      "db.noRuns": "Aucun essai d'évaluation enregistré. Lancez make eval TAG=rules, et make bench pour Apertus.", "db.target": "objectif {t} %", "db.below": "sous l'objectif",
      "db.col.run": "Essai", "db.col.recall": "Rappel@10", "db.col.twins": "Termes courants", "db.col.trace": "Traçabilité", "db.col.abst": "Abstention",
      "db.col.lat": "Latence", "db.col.callsQ": "Appels / requête", "db.col.cpq": "Coût / requête", "db.noLlm": "sans Apertus",
      "db.r.search": "Recherche", "db.r.suggest": "Suggestions d'entreprises", "db.r.create": "Nouvelle demande", "db.r.rematch": "Rechercher à nouveau des partenaires",
      "db.r.draft": "Brouillon d'e-mail", "db.r.brief": "Note de synthèse", "db.r.matches": "Ajouter des partenaires", "db.r.details": "Détails de la demande", "db.r.reply": "Réponse de l'entreprise",
      "bs.title": "Que recherchez-vous ?",
      "bs.ph": "p. ex. entreprise de glucose à Milan — dans toute langue",
      "bs.place": "Lieu",
      "bs.topic": "Thème",
      "bs.searching": "Recherche à Berne de",
      "bs.hint": "Saisissez un thème, un type d'entreprise et/ou un lieu.",
      "bs.langs": "Fonctionne en English, Deutsch, Français, Italiano et Rumantsch.",
    },
  };
  let LANG = store.get("nav-lang", null) || ((navigator.language || "en").startsWith("de") ? "de" : (navigator.language || "").startsWith("fr") ? "fr" : "en");
  Object.assign(I18N.en, {
    'role.agent': 'Sales agent — leads and knowledge', 'role.representative': 'Representative — pitch and outreach', 'role.title': 'Preview role', 'role.apply': 'Apply role', 'role.noPitch': 'The sales agent enriches the lead and Knowledge Base. The representative creates and sends the pitch.',
    'kb.share': 'Approve this public passage for the pitch', 'kb.shareHint': 'Only explicitly selected public web passages enter the shared pitch. Private notes/documents remain internal.',
    'delivery.sent': 'Sent', 'delivery.pending': 'Pending', 'delivery.uncertain': 'Unconfirmed — check before resending',
    'i.moreWhy': 'Selection details and sources', 'i.deliveryLog': 'Delivery history',
    'nw.need': 'Ambitions and development objectives (optional)', 'nw.needPh': 'e.g. accelerate clinical research, develop a technology, explore investment partners', 'u.needs': 'Development objectives',
    'i.send': 'Send email with PDF', 'i.smtpOff': 'Server delivery requires a configured email account and public pitch URL. You can still use your email app.', 'i.sentServer': 'Email and PDF sent.', 'i.uncertain': 'Delivery is pending or unconfirmed. Check the delivery record before attempting another send.', 'i.forYouT': 'Your 20-second overview', 'i.brandColor': 'Company accent color', 'i.brandLogo': 'Company logo (optional PNG/JPEG)',
    'scope.title': 'Partner search area', 'scope.bern': 'Bern only', 'scope.north': 'Bern and nearby northern Switzerland', 'scope.hint': 'Extended area: Solothurn, Aargau, Basel, Zurich and Lucerne. Only indexed sources with a known location are included.',
    'kb.noContext': 'No relevant private knowledge sources found for this lead.',
    'kb.access': 'Access is reserved for explicitly enabled Kanton Bern accounts.', 'kb.signin': 'Canton staff sign in', 'kb.password': 'Password',
    "theme.dark": "Switch to dark mode", "theme.light": "Switch to light mode",
    "foot.canton": "Official canton website", "foot.contact": "Contact the canton", "foot.imprint": "Cantonal imprint", "foot.legal": "Cantonal legal & privacy information",
    "foot.project": "Research & Expertise Navigator · Hack Apertus prototype", "foot.logo": "Logo: © Kanton Bern",
    "loading": "Loading…", "retry": "Try again",
    "rq.loadError": "Company requests could not be loaded",
    "rq.filter": "Find a company request", "rq.filterHint": "Search company, needs, location or specialty",
    "rq.count": "{n} of {total} requests", "rq.noMatch": "No matching requests. Try another search.",
    "rq.workflow": "Request progress", "i.working": "Preparing your personalized pitch…",
    "i.failed": "The pitch could not be prepared. Your previous pitch is preserved. Please try again.",
  });
  Object.assign(I18N.de, {
    'role.agent': 'Vertriebsagent — Leads und Wissen', 'role.representative': 'Repräsentant — Pitch und Kontakt', 'role.title': 'Vorschaurolle', 'role.apply': 'Rolle anwenden', 'role.noPitch': 'Der Vertriebsagent ergänzt Lead und Wissensbasis. Der Repräsentant erstellt und versendet den Pitch.',
    'kb.share': 'Diesen öffentlichen Beleg für den Pitch freigeben', 'kb.shareHint': 'Nur ausdrücklich gewählte öffentliche Webbelege erscheinen im geteilten Pitch. Private Notizen/Dokumente bleiben intern.',
    'delivery.sent': 'Gesendet', 'delivery.pending': 'Ausstehend', 'delivery.uncertain': 'Unbestätigt — vor erneutem Versand prüfen',
    'i.moreWhy': 'Auswahl und Quellen im Detail', 'i.deliveryLog': 'Versandverlauf',
    'nw.need': 'Ambitionen und Entwicklungsziele (optional)', 'nw.needPh': 'z. B. klinische Forschung beschleunigen, Technologie entwickeln, Investitionspartner erkunden', 'u.needs': 'Entwicklungsziele',
    'i.send': 'E-Mail mit PDF senden', 'i.smtpOff': 'Serverversand benötigt ein eingerichtetes E-Mail-Konto und eine öffentliche Pitch-URL. Ihr E-Mail-Programm bleibt verfügbar.', 'i.sentServer': 'E-Mail und PDF versendet.', 'i.uncertain': 'Versand ausstehend oder unbestätigt. Vor einem weiteren Versand den Status prüfen.', 'i.forYouT': 'Ihr 20-Sekunden-Überblick', 'i.brandColor': 'Akzentfarbe der Firma', 'i.brandLogo': 'Firmenlogo (optional PNG/JPEG)',
    'scope.title': 'Region für die Partnersuche', 'scope.bern': 'Nur Bern', 'scope.north': 'Bern und nahe Regionen der Nordschweiz', 'scope.hint': 'Erweiterung: Solothurn, Aargau, Basel, Zürich und Luzern. Nur erfasste Quellen mit bekanntem Standort werden berücksichtigt.',
    'kb.noContext': 'Keine passenden privaten Wissensquellen für diesen Lead gefunden.',
    'kb.access': 'Zugang nur für ausdrücklich freigeschaltete Konten des Kantons Bern.', 'kb.signin': 'Anmeldung für Kantonsmitarbeitende', 'kb.password': 'Passwort',
    "theme.dark": "Dunklen Modus aktivieren", "theme.light": "Hellen Modus aktivieren",
    "foot.canton": "Website des Kantons", "foot.contact": "Kontakt zum Kanton", "foot.imprint": "Impressum des Kantons", "foot.legal": "Rechtliches & Datenschutz des Kantons",
    "foot.project": "Research & Expertise Navigator · Hack-Apertus-Prototyp", "foot.logo": "Logo: © Kanton Bern",
    "loading": "Wird geladen…", "retry": "Erneut versuchen",
    "rq.loadError": "Firmenanfragen konnten nicht geladen werden",
    "rq.filter": "Firmenanfrage finden", "rq.filterHint": "Firma, Bedarf, Standort oder Fachgebiet suchen",
    "rq.count": "{n} von {total} Anfragen", "rq.noMatch": "Keine passenden Anfragen. Versuchen Sie eine andere Suche.",
    "rq.workflow": "Fortschritt der Anfrage", "i.working": "Ihr persönlicher Pitch wird vorbereitet…",
    "i.failed": "Der Pitch konnte nicht erstellt werden. Ihr bisheriger Pitch bleibt erhalten. Bitte versuchen Sie es erneut.",
  });
  Object.assign(I18N.fr, {
    'role.agent': 'Agent commercial — prospects et connaissances', 'role.representative': 'Représentant — pitch et contact', 'role.title': 'Rôle de prévisualisation', 'role.apply': 'Appliquer le rôle', 'role.noPitch': 'L’agent commercial enrichit le prospect et la base. Le représentant crée et envoie le pitch.',
    'kb.share': 'Approuver ce passage public pour le pitch', 'kb.shareHint': 'Seuls les passages web publics explicitement sélectionnés entrent dans le pitch partagé. Notes et documents privés restent internes.',
    'delivery.sent': 'Envoyé', 'delivery.pending': 'En attente', 'delivery.uncertain': 'Non confirmé — vérifier avant de renvoyer',
    'i.moreWhy': 'Détails de la sélection et sources', 'i.deliveryLog': 'Historique des envois',
    'nw.need': 'Ambitions et objectifs de développement (facultatif)', 'nw.needPh': 'p. ex. accélérer la recherche clinique, développer une technologie, explorer des partenaires d’investissement', 'u.needs': 'Objectifs de développement',
    'i.send': 'Envoyer l’e-mail avec PDF', 'i.smtpOff': 'L’envoi serveur nécessite un compte e-mail et une URL publique configurés. Votre messagerie reste disponible.', 'i.sentServer': 'E-mail et PDF envoyés.', 'i.uncertain': 'Envoi en attente ou non confirmé. Vérifiez le statut avant tout nouvel envoi.', 'i.forYouT': 'Votre aperçu en 20 secondes', 'i.brandColor': 'Couleur de l’entreprise', 'i.brandLogo': 'Logo de l’entreprise (PNG/JPEG facultatif)',
    'scope.title': 'Zone de recherche des partenaires', 'scope.bern': 'Berne uniquement', 'scope.north': 'Berne et régions proches du nord de la Suisse', 'scope.hint': 'Extension : Soleure, Argovie, Bâle, Zurich et Lucerne. Seules les sources indexées avec un lieu connu sont incluses.',
    'kb.noContext': 'Aucune source privée pertinente trouvée pour ce prospect.',
    'kb.access': 'Accès réservé aux comptes explicitement autorisés du Canton de Berne.', 'kb.signin': 'Connexion du personnel cantonal', 'kb.password': 'Mot de passe',
    "theme.dark": "Activer le mode sombre", "theme.light": "Activer le mode clair",
    "foot.canton": "Site officiel du canton", "foot.contact": "Contacter le canton", "foot.imprint": "Impressum du canton", "foot.legal": "Informations juridiques et confidentialité du canton",
    "foot.project": "Research & Expertise Navigator · Prototype Hack Apertus", "foot.logo": "Logo : © Canton de Berne",
    "loading": "Chargement…", "retry": "Réessayer",
    "rq.loadError": "Impossible de charger les demandes d’entreprises",
    "rq.filter": "Trouver une demande", "rq.filterHint": "Rechercher une entreprise, un besoin, un lieu ou une spécialité",
    "rq.count": "{n} demandes sur {total}", "rq.noMatch": "Aucune demande correspondante. Essayez une autre recherche.",
    "rq.workflow": "Progression de la demande", "i.working": "Préparation de votre pitch personnalisé…",
    "i.failed": "Le pitch n’a pas pu être préparé. Le pitch précédent est conservé. Veuillez réessayer.",
  });
  if (!I18N[LANG]) LANG = "en";
  const t = (k, v = {}) => (I18N[LANG][k] ?? I18N.en[k] ?? k).replace(/\{(\w+)\}/g, (_, x) => v[x] ?? "");
  const fmtDate = (iso, withTime = true, lang = LANG) => {
    try { return new Intl.DateTimeFormat(lang === "en" ? "en-GB" : lang + "-CH", withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(new Date(iso)); }
    catch { return iso; }
  };

  /* ======================= reference lists ======================= */
  const COUNTRIES = ["Switzerland", "Germany", "France", "Italy", "Austria", "Liechtenstein", "United Kingdom", "Netherlands",
    "Belgium", "Denmark", "Sweden", "Ireland", "Spain", "Israel", "United States", "Canada", "Japan", "South Korea", "China", "Singapore", "India"];
  const CANTONS = ["Aargau", "Appenzell Ausserrhoden", "Appenzell Innerrhoden", "Basel-Landschaft", "Basel-Stadt", "Bern", "Fribourg", "Geneva",
    "Glarus", "Graubünden", "Jura", "Lucerne", "Neuchâtel", "Nidwalden", "Obwalden", "Schaffhausen", "Schwyz", "Solothurn", "St. Gallen",
    "Thurgau", "Ticino", "Uri", "Valais", "Vaud", "Zug", "Zurich"];
  const isSwiss = (c) => /^(switzerland|schweiz|suisse|svizzera|ch)$/i.test((c || "").trim());

  /* ======================= staff identity ======================= */
  let staff = store.get("nav-staff", null);
  let cantonMember = null;
  const recent = () => store.get("nav-recent", []);
  function setStaff(p) {
    staff = p; store.set("nav-staff", p);
    if (p) store.set("nav-recent", [p, ...recent().filter((x) => x.name !== p.name)].slice(0, 6));
  }
  const initialsOf = (name) => {
    const parts = (name || "?").split(/\s+/).filter((p) => !/^(prof\.?|dr\.?|pd|med\.?|phil\.?|em\.?|nat\.?|rer\.?|dr\.-ing\.?|ing\.?|msc|phd)$/i.test(p));
    return (((parts[0] || "")[0] || "") + ((parts.length > 1 ? parts[parts.length - 1][0] : "") || "")).toUpperCase() || "?";
  };
  const roleHome = () => "#/staff/requests";
  const asStaff = (extra = {}) => ({ actor: staff.name, ...extra });

  /* ======================= API ======================= */
  async function api(path, opts = {}) {
    const r = await fetch(path, { method: opts.method || "GET", headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined, signal: opts.signal });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
      const e = new Error(msg); e.status = r.status; throw e;
    }
    return r.json();
  }

  /* ======================= glossary / jargon ======================= */
  let GLOSS = { lang: null, rx: null, map: new Map() };
  async function loadGlossary() {
    if (GLOSS.lang === LANG) return;
    try {
      const g = await api(`/glossary?lang=${LANG}`);
      const map = new Map();
      for (const x of g) for (const f of x.forms) map.set(f, { term: x.term, plain: x.plain });
      const forms = [...map.keys()].sort((a, b) => b.length - a.length).map((f) => esc(f).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      GLOSS = { lang: LANG, map, rx: forms.length ? new RegExp(`(?<![\\p{L}\\p{N}-])(${forms.join("|")})(?![\\p{L}\\p{N}-])`, "giu") : null };
    } catch { GLOSS = { lang: LANG, rx: null, map: new Map() }; }
  }
  function jargon(text) {
    const h = esc(text);
    if (!GLOSS.rx) return h;
    return h.replace(GLOSS.rx, (m) => { const g = GLOSS.map.get(m.toLowerCase()); return g ? `<abbr class="jargon" title="${esc(g.plain)}">${m}</abbr>` : m; });
  }

  /* ======================= shared rendering ======================= */
  const avatar = (name, type, sm = false) =>
    `<div class="avatar ${sm ? "sm " : ""}${esc(type)}" aria-hidden="true">${type === "person" ? esc(initialsOf(name)) : ICON[type] || ""}</div>`;
  // who wrote a text the officer reads: Apertus (check it) or the deterministic rules
  const provBadge = (by, why) => { const ai = by === "apertus";
    return `<span class="ai-badge ${ai ? "" : "rules"}" title="${esc(why)}">${ai ? ICON.sparkle : ICON.check}${esc(t(ai ? "prov.ai" : "prov.rule"))}</span>`; };
  const pill = (status) => `<span class="pill st-${esc(status)}">${esc(t("st." + status))}</span>`;
  const spinner = (msg = "") => `<div class="working" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span>${msg ? `<span>${esc(msg)}</span>` : `<span class="sr">…</span>`}</div>`;
  function highlight(text, terms) {
    const h = esc(text);
    if (!terms.length) return h;
    const rx = new RegExp("(" + terms.map((x) => esc(x).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "giu");
    return h.replace(rx, "<mark>$1</mark>");
  }
  function termsFor(q, extra = []) {
    const stop = new Set("the and for with von und der die das des den ein eine in of on to at by or a an les une pour sur non".split(" "));
    return [...new Set([q, ...extra].join(" ").toLowerCase().split(/[^\p{L}\p{N}-]+/u).filter((x) => x.length > 2 && !stop.has(x)))]
      .sort((a, b) => b.length - a.length).slice(0, 30);
  }
  const view = () => $("#view");
  const L = (o) => (o && (o[LANG] || o.en)) || "";

  /* ======================= state ======================= */
  const S = { cases: [], stats: null, showcase: null, examples: null, entity: new Map(),
    sources: null, types: new Set(["person", "unit", "project", "infrastructure"]), data: null, ctl: null, ctx: store.get("nav-ctx", null) };
  const entity = async (id) => { if (!S.entity.has(id)) S.entity.set(id, await api(`/entity/${encodeURIComponent(id)}`)); return S.entity.get(id); };
  async function stats() { if (!S.stats) { try { S.stats = await api("/stats"); } catch { S.stats = { sources: [], entities_per_source: {}, pages_per_source: {} }; } } return S.stats; }
  async function showcase() { if (!S.showcase) { try { S.showcase = await api("/showcase"); } catch { S.showcase = { themes: [], highlights: [], labs: [], facilities: [], engage: [] }; } } return S.showcase; }
  async function refreshCases() {
    S.casesError = "";
    try { S.cases = await api("/cases"); }
    catch (e) { S.casesError = e.message; }
  }
  async function archetypes() { if (!S.arch) { try { S.arch = await api("/archetypes"); } catch { S.arch = []; } } return S.arch; }
  async function areas() { if (!S.areas) { try { S.areas = await api("/medtech-areas"); } catch { S.areas = []; } } return S.areas; }
  const areaLabel = (a, n) => {
    const A = (S.areas || []).find((x) => x.id === a); if (!A) return "";
    const N = A.niches.find((x) => x.id === n);
    return N ? `${L(A.label)} › ${L(N.label)}` : L(A.label);
  };
  const companyOf = (c) => c.company || t("rq.untitled");
  const placeOf = (c) => [c.city, c.canton !== c.city ? c.canton : "", c.country].filter(Boolean).join(", ");

  /* ======================= chrome per area ======================= */
  // DE · FR · EN as visible buttons: the canton is bilingual, so the switch must not hide in a dropdown
  const LANG_NAMES = { de: "Deutsch", fr: "Français", en: "English" };
  const langSel = () => `<div class="langs" role="group" aria-label="${esc(t("lang.label"))}">${["de", "fr", "en"].map((l) =>
    `<button type="button" data-lang="${l}" lang="${l}" aria-pressed="${l === LANG}" title="${LANG_NAMES[l]}"><span aria-hidden="true">${l.toUpperCase()}</span><span class="sr">${LANG_NAMES[l]}</span></button>`).join("")}</div>`;
  const isDark = () => (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  const themeBtn = () => `<button class="icon-btn" id="themeBtn" type="button" aria-pressed="${isDark()}" aria-label="${esc(t("theme"))}" title="${esc(t("theme"))}">${ICON.moon}</button>`
    + `<button class="icon-btn help-btn" id="helpBtn" type="button" aria-label="${esc(window.PlatformGuide?.title(LANG) || 'Help')}" title="${esc(window.PlatformGuide?.title(LANG) || 'Help')}"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5l11 7-11 7z"/></svg></button>`;

  /** Whether Apertus is answering right now (from /health). Shown wherever AI output can appear. */
  async function health() { if (!S.health) { try { S.health = await api("/health"); } catch { S.health = { llm_available: false }; } } return S.health; }
  const aiStatus = () => `<span class="ai-status" id="aiStatus" tabindex="0" role="status"><span class="dot"></span><span class="lbl">…</span></span>`;
  async function fillAiStatus() {
    const h = await health();
    $$(".ai-status").forEach((el) => {
      el.classList.toggle("on", !!h.llm_available); el.classList.toggle("off", !h.llm_available);
      el.title = t(h.llm_available ? "ai.onT" : "ai.offT");
      el.setAttribute("aria-label", `${t(h.llm_available ? "ai.on" : "ai.off")}. ${el.title}`);
      $(".lbl", el).textContent = t(h.llm_available ? "ai.on" : "ai.off");
    });
  }
  // the canton's logo and institutional links; the AI status where AI output can appear; the prototype note
  const footer = (text, ai = false) => `<div class="footer-main"><a href="https://www.be.ch/de/start.html" target="_blank" rel="noopener"><img class="canton-logo" src="/static/brand/logo-be.svg" width="400" height="178" alt="Kanton Bern / Canton de Berne"></a>
      <div><p class="footer-title">${esc(t("foot.project"))}</p><p>${esc(text)}</p>${ai ? `<span class="foot-ai">${aiStatus()}</span>` : ""}<p class="proto">${esc(t("foot.proto"))}</p></div></div>
    <nav class="footer-links" aria-label="${esc(t("foot.canton"))}"><a href="https://www.be.ch/de/start.html" target="_blank" rel="noopener">${esc(t("foot.canton"))}</a>
      <a href="https://www.be.ch/de/start/ueber-uns/kontaktformular.html" target="_blank" rel="noopener">${esc(t("foot.contact"))}</a>
      <a href="https://www.be.ch/de/tools/impressum.html" target="_blank" rel="noopener">${esc(t("foot.imprint"))}</a>
      <a href="https://www.be.ch/de/tools/rechtliches.html" target="_blank" rel="noopener">${esc(t("foot.legal"))}</a></nav><small>${esc(t("foot.logo"))}</small>`;

  function renderChrome(shell, active) {
    const bar = $("#topbar");
    bar.className = `topbar ${shell === "staff" ? "staff" : ""} ${shell === "brief" ? "brief" : ""}`;
    document.body.classList.toggle("brief-mode", shell === "brief");
    $(".skip").textContent = t("skip");
    const brand = (sub, href) => `<a class="brand" href="${href}"><img class="canton-logo" src="/static/brand/logo-be.svg" width="400" height="178" alt="Kanton Bern / Canton de Berne">
      <span class="brand-text"><b>Bern Expertise Navigator</b><small>${esc(sub)}</small></span></a>`;
    const tab = (href, key, label, count = "") => `<a href="${href}" class="${active === key ? "on" : ""}" ${active === key ? 'aria-current="page"' : ""}>${esc(label)}${count ? `<i class="count">${count}</i>` : ""}</a>`;
    if (shell === "brief") {
      bar.innerHTML = `<div class="topbar-in">${brand(t("brand.briefSub"), location.hash)}<div class="topbar-right">${themeBtn()}</div></div>`;
      $("#foot").innerHTML = footer(t("foot.brief"));
    } else if (shell === "public") {
      bar.innerHTML = `<div class="topbar-in">${brand(t("brand.sub"), "#/")}
        <nav class="tabs" aria-label="Main">${tab("#/", "search", t("nav.search"))}${tab("#/directory", "dir", t("nav.dir"))}</nav>
        <div class="topbar-right">${langSel()}${themeBtn()}<a class="staff-link" href="#/staff" title="${esc(t("nav.staff"))}">${ICON.lock}<span>${esc(t("nav.staff"))}</span></a></div></div>`;
      $("#foot").innerHTML = footer(t("foot.public"), true);
    } else {
      // still to do: requests without a pitch, and companies that replied
      const open = S.cases.filter((c) => (c.status === "new" && !c.has_brief && c.matched !== false) || c.status === "interested").length;
      const nav = !staff ? "" : tab("#/staff/requests", "requests", t("nav.requests"), open || "") + tab("#/staff/new", "new", t("nav.new")) + tab("#/staff/search", "ssearch", t("nav.search")) + tab("#/staff/dashboard", "dash", t("nav.dash")) + (cantonMember?.can_manage_knowledge ? `<a class="kb-nav ${active === 'knowledge' ? 'on' : ''}" href="#/staff/knowledge" ${active === 'knowledge' ? 'aria-current="page"' : ''}>${ICON.doc}<strong>${esc(window.KnowledgeWorkspace.title(LANG))}</strong></a>` + tab('#/staff/analytics', 'analytics', 'Analytics') : '');
      bar.innerHTML = `<div class="topbar-in">${brand(t("brand.staffSub"), staff ? roleHome() : "#/staff")}<span class="staff-tag">${esc(t("staff.tag"))}</span>
        ${nav ? `<nav class="tabs" aria-label="Workspace">${nav}</nav>` : ""}
        <div class="topbar-right">${aiStatus()}${langSel()}${themeBtn()}
          ${staff ? `<div class="whoami"><span class="av officer" aria-hidden="true">${esc(initialsOf(staff.name))}</span>
            <span class="txt"><b>${esc(staff.name)}</b>${staff.team ? `<small>${esc(staff.team)}</small>` : ""}</span>
            <button type="button" id="switchUser">${esc(t("who.switch"))}</button></div>` : ""}
          <a class="staff-link" href="#/" title="${esc(t("nav.public"))}">${ICON.ext}<span>${esc(t("nav.public"))}</span></a></div></div>`;
      $("#foot").innerHTML = footer(t("foot.staff"));
      $("#switchUser")?.addEventListener("click", async () => {
        if (cantonMember?.can_manage_knowledge) {
          try { await api('/staff/session', { method: 'DELETE' }); }
          catch (e) { toast(e.message); return; }
          cantonMember = null;
        }
        go("#/staff/who");
      });
    }
    fillAiStatus();
    $('#helpBtn')?.addEventListener('click', () => window.PlatformGuide?.open(LANG));
    bar.querySelector('.tabs [aria-current="page"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    $$("[data-lang]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.lang === LANG) return;
      LANG = b.dataset.lang; store.set("nav-lang", LANG); route();
    }));
    $("#themeBtn").addEventListener("click", (ev) => {
      const nx = isDark() ? "light" : "dark"; document.documentElement.dataset.theme = nx; store.set("nav-theme", nx);
      ev.currentTarget.setAttribute("aria-pressed", nx === "dark");
    });
  }

  /* ======================= router ======================= */
  async function route() {
    window.KnowledgeWorkspace?.unmount();
    window.PlatformAnalytics?.unmount();
    window.CompanyDiscovery?.unmount();
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, qs] = h.split("?");
    const p = path.split("/").filter(Boolean);
    const params = new URLSearchParams(qs || "");
    document.body.classList.remove("sheet-open");
    window.scrollTo(0, 0);
    document.documentElement.lang = LANG;

    if (p[0] === "b" && p[1]) { renderChrome("brief"); return viewBrief(p[1], params); }
    if (p[0] !== "staff") {
      renderChrome("public", p[0] === "directory" ? "dir" : "search");
      if (p[0] === "directory") return viewDirectory();
      if (p[0] === "search" && params.get("q")) return viewSearch(params, "public");
      return viewHome();
    }
    try { cantonMember = await api('/staff/session'); } catch { cantonMember = null; }
    if (p[1] === 'access') { renderChrome('staff', ''); return viewCantonAccess(); }
    if (p[1] === "who" || !staff) { renderChrome("staff", ""); return viewIdentity(); }
    if (p[1] === 'knowledge' || p[1] === 'analytics' || p[1] === 'discovery') {
      renderChrome('staff', p[1]);
      if (!cantonMember?.can_manage_knowledge) { view().innerHTML = `<section class="panel empty"><h1>Kanton Bern / Canton de Berne</h1><p>${esc(t('kb.access'))}</p><a class="btn-primary" href="#/staff/access">${esc(t('kb.signin'))}</a></section>`; return; }
      if (p[1] === 'analytics') return window.PlatformAnalytics.mount({ api, lang: LANG, esc, toast });
      if (p[1] === 'discovery') return window.CompanyDiscovery.mount({ api, lang: LANG, esc, toast, leadId: params.get('lead') });
      return window.KnowledgeWorkspace.mount({ api, lang: LANG, esc, accept: DOC_ACCEPT, toast, selectedId: params.get('company'), candidateId: params.get('candidate') });
    }
    await refreshCases();
    const sub = p[1] || "";
    if (!["requests", "new", "search", "case", "dashboard"].includes(sub)) return go(roleHome());
    renderChrome("staff", { requests: "requests", new: "new", search: "ssearch", case: "requests", dashboard: "dash" }[sub] || "");
    if (sub === "dashboard") return viewDashboard();
    if (S.casesError && sub === "requests") {
      view().innerHTML = `<section class="panel empty" role="alert"><h1>${esc(t("rq.loadError"))}</h1><p>${esc(S.casesError)}</p><button class="btn-primary" id="retryCases" type="button">${esc(t("retry"))}</button></section>`;
      $("#retryCases").addEventListener("click", () => route());
      return;
    }
    if (sub === "requests") return viewRequests();
    if (sub === "new") return viewNew();
    if (sub === "search") return params.get("q") ? viewSearch(params, "staff") : viewStaffSearchHome();
    if (sub === "case" && p[2]) return viewCase(p[2]);
    return go(roleHome());
  }

  /* ======================= PUBLIC: home ======================= */
  const searchBox = (q = "", target = "#/search") => `<form class="searchbox" id="sForm" role="search" data-target="${target}">${ICON.search}
      <input id="sQ" type="search" value="${esc(q)}" aria-label="${esc(t("go"))}" autocomplete="off">
      <button class="btn-primary" type="submit">${esc(t("go"))}</button></form>`;
  function bindSearchBox() {
    $("#sForm")?.addEventListener("submit", (ev) => {
      ev.preventDefault(); const v = $("#sQ").value.trim();
      if (v.length > 1) go(`${ev.target.dataset.target}?q=${encodeURIComponent(v)}`);
    });
    $$(".chip[data-q]").forEach((b) => b.addEventListener("click", () => go(`${$("#sForm").dataset.target}?q=${encodeURIComponent(b.dataset.q)}`)));
  }
  const exampleChips = () => `<div class="chips"><span class="muted">${esc(t("try"))}:</span>
    ${["glucose sensors", "kontinuierliche Glukosemessung", "robots for neurosurgery", "3D printing facility", "organs-on-chip"].map((x) => `<button class="chip" type="button" data-q="${esc(x)}">${esc(x)}</button>`).join("")}</div>`;

  async function viewHome() {
    await loadGlossary();
    view().innerHTML = `<section class="hero"><h1>${esc(t("home.title"))}</h1><p>${esc(t("home.lead"))}</p>${searchBox()}${exampleChips()}</section><div id="homeBody">${spinner()}</div>`;
    bindSearchBox();
    const sc = await showcase();
    const sQ = (q) => `#/search?q=${encodeURIComponent(q)}`;
    $("#homeBody").innerHTML = `
      ${sc.highlights.length ? `<div class="section-h"><h2>${esc(t("proof"))}</h2><span class="muted">${esc(t("proofNote"))}</span></div>
      <div class="proof">${sc.highlights.map((h) => `<article class="proof-card"><div class="fig">${esc(h.figure)}</div><div class="lbl">${esc(L(h.label))}</div>
        <q>${esc(h.quote)}</q><a href="${esc(safeUrl(h.url))}" target="_blank" rel="noopener">${ICON.link} ${esc(hostPath(h.url))}</a></article>`).join("")}</div>` : ""}
      <div class="section-h"><h2>${esc(t("themes"))}</h2><span class="muted">${esc(t("themesNote"))}</span></div>
      <div class="themes">${sc.themes.map((th) => `<a class="theme" href="${sQ(th.query)}" style="text-decoration:none">
        <h3>${esc(L(th.title))}</h3><p>${esc(L(th.blurb))}</p>
        <div class="nums"><span><b>${th.counts.person}</b> ${esc(t("people"))}</span><span><b>${th.counts.unit}</b> ${esc(t("labsN"))}</span><span><b>${th.counts.project}</b> ${esc(t("projects"))}</span></div>
        ${th.labs.length ? `<div class="labs">${th.labs.map((l) => esc(l.name)).join(" · ")}</div>` : ""}</a>`).join("")}</div>
      <div class="actions" style="margin-top:22px;justify-content:center"><a class="btn" href="#/directory">${esc(t("home.more"))}</a></div>`;
  }

  /* ======================= search (public and staff) ======================= */
  async function filtersHtml() {
    const st = await stats();
    if (!S.sources) S.sources = new Set(st.sources.map((x) => x.name));
    return `<div class="filters"><div class="fgroup" role="group" aria-label="${esc(t("flt.sources"))}">${st.sources.filter((x) => (st.entities_per_source[x.name] ?? 0) > 0).map((x) =>
      `<button type="button" class="fchip ${S.sources.has(x.name) ? "on" : ""}" data-src="${esc(x.name)}" title="${esc(x.label)}" aria-pressed="${S.sources.has(x.name)}">
        <i class="t-dot src"></i>${esc(({ unibe_web: "UniBE", unibe: "UniBE · OpenAlex" })[x.name] || x.name.toUpperCase())} <span class="muted">${st.entities_per_source[x.name] ?? 0}</span></button>`).join("")}</div>
      <div class="fgroup" role="group" aria-label="${esc(t("flt.types"))}">${[["person", "t.people"], ["unit", "t.labs"], ["project", "t.projects"], ["infrastructure", "t.facilities"]].map(([k, l]) =>
      `<button type="button" class="fchip ${S.types.has(k) ? "on" : ""}" data-type="${k}" aria-pressed="${S.types.has(k)}"><i class="t-dot ${k}"></i>${esc(t(l))}</button>`).join("")}</div></div>`;
  }

  async function viewSearch(params, shell) {
    await loadGlossary();
    const q = params.get("q") || "";
    const ctx = shell === "staff" ? S.ctx : null;
    view().innerHTML = `
      ${ctx ? `<div class="ctx-banner"><span>${ICON.info} ${esc(t("ctx", { c: ctx.company }))}</span>
        <span class="actions"><a class="btn btn-sm" href="#/staff/case/${esc(ctx.id)}">${esc(t("ctxBack"))}</a>
        <button class="link-btn" id="ctxClose" type="button" aria-label="Close">✕</button></span></div>` : ""}
      <div style="margin:4px 0 12px">${searchBox(q, shell === "staff" ? "#/staff/search" : "#/search")}</div>${await filtersHtml()}
      <div class="results-view"><div class="results-col"><div class="results-head" id="rHead" aria-live="polite"><span class="cnt">…</span></div>
        <div class="results" id="rList">${Array.from({ length: 3 }, () => `<div class="skel"><div class="sk" style="width:40%;height:16px"></div><div class="sk" style="width:70%"></div><div class="sk"></div></div>`).join("")}</div></div>
        <aside class="detail" id="detail" aria-label="Details"><div class="detail-empty"><p>${esc(t("res.select"))}</p></div></aside></div>`;
    bindSearchBox();
    $("#ctxClose")?.addEventListener("click", () => { S.ctx = null; store.set("nav-ctx", null); route(); });
    $$(".fchip").forEach((f) => f.addEventListener("click", () => {
      const set = f.dataset.src ? S.sources : S.types, key = f.dataset.src || f.dataset.type;
      if (set.has(key) && set.size === 1) return;
      set.has(key) ? set.delete(key) : set.add(key);
      f.classList.toggle("on"); f.setAttribute("aria-pressed", f.classList.contains("on"));
      runSearch(q, ctx);
    }));
    runSearch(q, ctx);
  }

  async function runSearch(q, ctx) {
    const p = new URLSearchParams({ q, k: "12" });
    if (S.stats && S.sources.size < S.stats.sources.length) S.sources.forEach((s) => p.append("source", s));
    if (S.types.size < 4) S.types.forEach((x) => p.append("type", x));
    S.ctl?.abort(); S.ctl = new AbortController();
    try { S.data = await api(`/search?${p}`, { signal: S.ctl.signal }); }
    catch (e) { if (e.name !== "AbortError") $("#rList").innerHTML = `<div class="abstain"><h3>${esc(t("err"))}</h3><p>${esc(e.message)}</p></div>`; return; }
    renderResults(ctx);
  }

  /** One result = the brief's structured record: who/what, role, affiliation, expertise, projects,
   *  infrastructure/services, contact, why it matches, verbatim source. Empty fields are omitted. */
  function resultCard(r, i, terms, ctx) {
    const hit = (s) => terms.reduce((n, w) => n + (s.toLowerCase().includes(w) ? 1 : 0), 0);
    const q0 = [...r.sources].sort((a, b) => hit(b.snippet) - hit(a.snippet) || (a.field === "name") - (b.field === "name"))[0];
    const aff = [r.affiliation.unit, r.affiliation.institute, r.affiliation.institution].filter(Boolean).filter((x, j, a) => a.indexOf(x) === j);
    const list = (xs, n) => `<div class="tags">${xs.slice(0, n).map((x) => `<span class="tag" title="${esc(x)}">${jargon(x.length > 70 ? x.slice(0, 67) + "…" : x)}</span>`).join("")}${xs.length > n ? `<span class="muted">+${xs.length - n}</span>` : ""}</div>`;
    const rows = [
      r.role && [t("f.role"), esc(r.role)],
      aff.length && [t("f.aff"), aff.map(esc).join(" · ")],
      r.expertise.length && [t("f.exp"), list(r.expertise, 4)],
      r.projects.length && [t("f.proj"), list(r.projects, 3)],
      r.infrastructure_services.length && [t("f.infra"), list(r.infrastructure_services, 3)],
      r.contact && [t("f.contact"), `<a href="mailto:${esc(r.contact)}">${esc(r.contact)}</a>`],
    ].filter(Boolean);
    return `<article class="card" tabindex="0" data-i="${i}" aria-label="${esc(r.person_or_unit)}">
      <div class="card-top">${avatar(r.person_or_unit, r.entity_type)}
        <div><h3>${esc(r.person_or_unit)}</h3>${r.role ? `<div class="sub2">${esc(r.role)}</div>` : ""}<div class="inst">${esc(r.institution)}</div></div>
        <span class="type-badge ${esc(r.entity_type)}">${esc(t("type." + r.entity_type))}</span></div>
      ${r.via ? `<div class="via">${esc(t("res.found"))} <b>${esc(r.via)}</b></div>` : ""}
      <p class="why-line"><b>${esc(t("res.why"))}:</b> ${highlight(r.why_match, terms)}</p>
      ${rows.length ? `<dl class="rfields">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>` : ""}
      ${q0 ? `<div class="src-line"><q>${highlight(q0.snippet.length > 220 ? q0.snippet.slice(0, 217) + "…" : q0.snippet, terms)}</q>
        <a href="${esc(safeUrl(q0.url))}" target="_blank" rel="noopener">${ICON.link} ${esc(hostPath(q0.url))}</a></div>` : ""}
      <div class="card-foot"><span class="verified">${ICON.check}${esc(t("res.verified"))}</span><span>${r.sources.length} ${esc(t("res.sources"))}</span>
        ${ctx ? `<span style="flex:1"></span><button class="btn btn-sm" type="button" data-add="${esc(r.id)}">${ICON.plus}${esc(t("res.add"))}</button>` : ""}</div>
    </article>`;
  }

  function renderResults(ctx) {
    const d = S.data, terms = termsFor(d.query, d.expanded_terms);
    $(".results-view").classList.toggle("solo", !!d.abstained);
    $("#rHead").innerHTML = d.abstained ? "" : `<span class="cnt">${d.results.length} ${esc(t("res.n"))}</span>
      ${d.expanded_terms.length ? `<span>${esc(t("res.also"))}</span>${d.expanded_terms.slice(0, 7).map((x) => `<span class="term">${esc(x)}</span>`).join("")}` : ""}
      <span class="prov" style="flex-basis:100%;margin:0"><span class="ai-badge ${d.llm_used ? "" : "rules"}">${d.llm_used ? ICON.sparkle : ICON.check}${esc(t(d.llm_used ? "prov.ai" : "prov.rule"))}</span>${esc(t(d.llm_used ? "prov.searchAi" : "prov.searchRules"))}</span>`;
    if (d.abstained) {
      $("#rList").innerHTML = `<div class="abstain"><div class="empty-ico" style="color:var(--warn);background:var(--warn-bg)">${ICON.shield}</div>
        <h3>${esc(t("res.none"))}</h3><p>${esc(d.message)}</p><p class="muted" style="margin-top:10px">${esc(t("res.noneHint"))}</p></div>`;
      return;
    }
    $("#rList").innerHTML = d.results.map((r, i) => resultCard(r, i, terms, ctx)).join("");
    $$(".card", $("#rList")).forEach((c) => {
      c.addEventListener("click", (ev) => { if (!ev.target.closest("a,button")) selectResult(+c.dataset.i, true, ctx); });
      c.addEventListener("keydown", (ev) => {
        if ((ev.key === "Enter" || ev.key === " ") && ev.target === c) { ev.preventDefault(); selectResult(+c.dataset.i, true, ctx); }
      });
    });
    $$("[data-add]").forEach((b) => b.addEventListener("click", () => addToCase(b.dataset.add, b)));
    if (!isNarrow() && d.results.length) selectResult(0, false, ctx);
  }

  async function addToCase(id, btn) {
    try {
      await api(`/cases/${S.ctx.id}/matches`, { method: "POST", body: asStaff({ entity_id: id }) });
      toast(t("res.added")); if (btn) { btn.disabled = true; btn.innerHTML = `${ICON.check}${esc(t("res.added"))}`; }
    } catch (e) { toast(e.message); }
  }

  function selectResult(i, open, ctx) {
    $$(".card").forEach((c, j) => c.classList.toggle("sel", j === i));
    showDetail(S.data.results[i].id, S.data.results[i], open, ctx);
  }

  async function showDetail(id, result, open, ctx) {
    const panel = $("#detail"); if (!panel) return;
    if (isNarrow() && open) { panel.classList.add("open"); document.body.classList.add("sheet-open"); }
    panel.innerHTML = `<div class="d-head"><div class="sk" style="width:60%;height:18px"></div></div>`;
    let det; try { det = await entity(id); } catch { panel.innerHTML = `<div class="detail-empty">${esc(t("err"))}</div>`; return; }
    const e = det.entity, terms = S.data ? termsFor(S.data.query, S.data.expanded_terms) : [];
    const byUrl = new Map();
    e.evidence.forEach((ev) => { if (!byUrl.has(ev.url)) byUrl.set(ev.url, []); byUrl.get(ev.url).push(ev); });
    panel.innerHTML = `
      <div class="d-head"><div class="row">${avatar(e.name, e.entity_type)}
        <div><h2>${esc(e.name)}</h2>${e.role ? `<div class="sub2">${esc(e.role)}</div>` : ""}
          <div class="crumbs">${[e.source_label, e.institute, e.unit].filter(Boolean).map(esc).join(" › ")}</div></div>
        <button class="icon-btn close-btn" id="dClose" type="button" aria-label="Close">${ICON.close}</button></div>
        <div class="d-actions">
          ${ctx ? `<button class="btn-primary btn-brand btn-sm" type="button" id="dAdd">${ICON.plus}${esc(t("res.add"))}</button>` : ""}
          ${e.email ? `<a class="btn btn-sm" href="mailto:${esc(e.email)}">${ICON.mail}${esc(e.email)}</a>` : ""}
          <a class="btn btn-sm" href="${esc(safeUrl(e.source_urls[0]))}" target="_blank" rel="noopener">${ICON.ext}${esc(t("res.open"))}</a></div></div>
      <div class="d-body">
        ${result ? `<section class="d-sec"><h4>${esc(t("res.why"))}</h4><p>${highlight(result.why_match, terms)}</p></section>` : ""}
        ${e.description?.length ? `<section class="d-sec"><h4>${esc(t("res.about"))}</h4><p>${jargon(e.description[0])}</p></section>` : ""}
        ${e.expertise.length ? `<section class="d-sec"><h4>${esc(t("f.exp"))}</h4><div class="tags">${e.expertise.slice(0, 12).map((x) => `<span class="tag" title="${esc(x)}">${jargon(x)}</span>`).join("")}</div></section>` : ""}
        ${det.related.length ? `<section class="d-sec"><h4>${esc(t("res.linked"))}</h4><div class="rel">${det.related.map((x) => `<button type="button" data-id="${esc(x.id)}">
          <span class="mini ${esc(x.entity_type)}">${esc(x.entity_type === "person" ? initialsOf(x.name) : x.entity_type[0].toUpperCase())}</span>
          <span>${esc(x.name)}</span>${x.role ? `<span class="r-role">· ${esc(x.role.slice(0, 28))}</span>` : ""}</button>`).join("")}</div></section>` : ""}
        <section class="d-sec"><h4>${esc(t("res.evidence"))} · ${e.evidence.length}</h4>
          ${[...byUrl.entries()].map(([u, evs]) => `<div class="ev-page"><a class="ev-url" href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${ICON.ext}<span>${esc(hostPath(u))}</span></a>
            <ul class="ev-list">${evs.map((ev) => `<li><span class="ev-field">${esc(ev.field)}</span><span>“${highlight(ev.snippet, terms)}”</span></li>`).join("")}</ul></div>`).join("")}</section>
      </div>`;
    $("#dClose")?.addEventListener("click", () => { panel.classList.remove("open"); document.body.classList.remove("sheet-open"); });
    $$(".rel button", panel).forEach((b) => b.addEventListener("click", () => showDetail(b.dataset.id, null, true, ctx)));
    $("#dAdd")?.addEventListener("click", (ev) => addToCase(e.id, ev.currentTarget));
  }

  /* ======================= PUBLIC: directory ======================= */
  async function viewDirectory() {
    await loadGlossary();
    view().innerHTML = `<div class="page-h"><div><h1>${esc(t("dir.title"))}</h1><p>${esc(t("dir.lead"))}</p></div></div>${spinner()}`;
    const sc = await showcase();
    let tab = store.get("nav-dirtab", "labs"), inst = "";
    const insts = [...new Set([...sc.labs, ...sc.facilities].map((x) => x.institution))].sort();
    const card = (f) => {
      const meta = [f.lead ? `${t("lead")}: ${f.lead.name}` : "", f.people ? `${f.people} ${t("people")}` : "", f.institution].filter(Boolean);
      return `<a class="dir-card" href="#/search?q=${encodeURIComponent(f.name)}" style="text-decoration:none">${avatar(f.name, f.entity_type, true)}
        <div><h3>${esc(f.name)}</h3><div class="lead">${esc(meta.join(" · "))}</div>${f.summary ? `<p>${jargon(f.summary)}</p>` : ""}</div></a>`;
    };
    const draw = () => {
      const xs = (tab === "labs" ? sc.labs : sc.facilities).filter((x) => !inst || x.institution === inst);
      view().innerHTML = `<div class="page-h"><div><h1>${esc(t("dir.title"))}</h1><p>${esc(t("dir.lead"))}</p></div></div>
        <div class="filters"><div class="seg-tabs" role="tablist">
          <button type="button" role="tab" data-tab="labs" aria-selected="${tab === "labs"}" class="${tab === "labs" ? "on" : ""}">${esc(t("dir.labs"))} (${sc.labs.length})</button>
          <button type="button" role="tab" data-tab="fac" aria-selected="${tab === "fac"}" class="${tab === "fac" ? "on" : ""}">${esc(t("dir.fac"))} (${sc.facilities.length})</button></div>
          <div class="fgroup"><button type="button" class="fchip ${!inst ? "on" : ""}" data-inst="">${esc(t("dir.all"))}</button>
          ${insts.map((i) => `<button type="button" class="fchip ${inst === i ? "on" : ""}" data-inst="${esc(i)}">${esc(i)}</button>`).join("")}</div></div>
        <div class="dir">${xs.map(card).join("")}</div>`;
      $$("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; store.set("nav-dirtab", tab); draw(); }));
      $$("[data-inst]").forEach((b) => b.addEventListener("click", () => { inst = b.dataset.inst; draw(); }));
    };
    draw();
  }

  /* ======================= STAFF: identity ======================= */
  function viewIdentity() {
    const rec = recent();
    view().innerHTML = `<div class="ident"><h1>${esc(t("id.title"))}</h1><p>${esc(t("id.lead"))}</p>
      <form class="panel" id="idForm"><div class="grid-form">
        <label class="field">${esc(t("id.name"))}<input name="name" required maxlength="80" value="${esc(staff?.name || "")}" autocomplete="name"></label>
        <label class="field">${esc(t("id.email"))}<input name="email" type="email" maxlength="120" value="${esc(staff?.email || "")}" autocomplete="email"></label>
        <label class="field full">${esc(t("id.team"))}<input name="team" maxlength="120" value="${esc(staff?.team || "")}"></label></div>
        <div class="sel-bar"><span></span><button class="btn-primary btn-brand" type="submit">${esc(t("id.enter"))}</button></div>
        ${rec.length ? `<div class="recent"><span class="muted">${esc(t("id.recent"))}:</span>${rec.map((p, i) => `<button type="button" data-rec="${i}">
          <span class="av officer">${esc(initialsOf(p.name))}</span>${esc(p.name)}</button>`).join("")}</div>` : ""}
      </form>${cantonMember?.preview ? `<div class="panel kb-form"><label class="field">${esc(t('role.title'))}<select class="input" id="previewRole">${['agent','representative'].map(role => `<option value="${role}" ${cantonMember.role === role ? 'selected' : ''}>${esc(t('role.' + role))}</option>`).join('')}</select></label><button class="btn" type="button" id="applyRole">${esc(t('role.apply'))}</button></div>` : ''}<p><a class="btn" href="#/staff/access">${esc(t('kb.signin'))}</a></p></div>`;
    $("#idForm").elements.namedItem('name').focus();
    $('#applyRole')?.addEventListener('click', async () => { try { await api('/staff/preview-role', {method:'PATCH',body:{role:$('#previewRole').value}}); go(roleHome()); } catch(e) {toast(e.message);} });
    $$("[data-rec]").forEach((b) => b.addEventListener("click", () => { setStaff(rec[+b.dataset.rec]); go(roleHome()); }));
    $("#idForm").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = ev.target;
      setStaff({ name: f.elements.namedItem('name').value.trim(), email: f.elements.namedItem('email').value.trim(), team: f.elements.namedItem('team').value.trim() });
      go(roleHome());
    });
  }

  function viewCantonAccess() {
    view().innerHTML = `<div class="ident"><h1>Kanton Bern / Canton de Berne</h1><p>${esc(t('kb.access'))}</p><form class="panel kb-form" id="cantonLogin"><label class="field">Email<input type="email" name="email" required autocomplete="username" maxlength="200"></label><label class="field">${esc(t('kb.password'))}<input type="password" name="password" required autocomplete="current-password" maxlength="200"></label><p id="cantonError" role="alert"></p><button class="btn-primary" type="submit">${esc(t('kb.signin'))}</button></form></div>`;
    $('#cantonLogin').onsubmit = async (event) => {
      event.preventDefault(); const form = event.target, button = form.querySelector('button'); button.disabled = true;
      try {
        await api('/staff/session', { method: 'POST', body: { email: form.elements.namedItem('email').value, password: form.elements.namedItem('password').value } });
        const member = await api('/staff/session');
        if (!member.can_manage_knowledge) throw new Error(t('kb.access'));
        setStaff({ name: member.name, email: member.email, team: 'Kanton Bern / Canton de Berne' });
        go('#/staff/knowledge');
      } catch (e) { $('#cantonError').textContent = e.message; button.disabled = false; }
    };
  }

  /* ======================= STAFF/officer: requests board ======================= */
  async function viewRequests() {
    await areas();
    // "matched === false": no Bern asset was found, so the request cannot move on (older lists lack the flag)
    const stage = (c) => (c.status === "interested" ? "replied" : c.status !== "new" ? "done" : c.has_brief ? "ready" : c.matched === false ? "none" : "todo");
    const by = (st) => S.cases.filter((c) => stage(c) === st);
    // "Replied" only appears when a company has answered: it is the most urgent column
    const cols = [...(by("replied").length ? [["col.replied", "replied"]] : []), ["col.todo", "todo"], ["col.ready", "ready"], ["col.done", "done"], ["col.none", "none"]];
    // the column already says the stage, so a status pill is shown only where it adds information (invited / call / closed)
    const card = (c) => `<a class="case-card" href="#/staff/case/${esc(c.id)}"><h3>${esc(companyOf(c))}</h3>${c.summary ? `<p>${esc(c.summary)}</p>` : ""}
      <div class="case-meta">${stage(c) === "done" ? pill(c.status) : ""}${c.niche || c.area ? `<span class="tag">${esc(areaLabel(c.area, c.niche))}</span>` : ""}${placeOf(c) ? `<span>${esc(placeOf(c))}</span>` : ""}
      ${c.selected ? `<span>${c.selected} ${esc(t("partners"))}</span>` : ""}${c.has_brief ? `<span class="views" title="${esc(t("bv.title"))}">${ICON.eye}${c.views || 0}</span>` : ""}
      <span><time datetime="${esc(c.updated_at)}">${esc(fmtDate(c.updated_at, false))}</time></span></div></a>`;
    view().innerHTML = `<div class="page-h"><div><h1>${esc(t("rq.title"))}</h1><p>${esc(t("rq.lead"))}</p></div>
        <a class="btn-primary btn-brand" href="#/staff/new">${ICON.plus}${esc(t("nav.new"))}</a></div>
      ${S.cases.length ? `<div class="request-tools"><label class="field" for="requestFilter">${esc(t("rq.filter"))}</label><input type="search" id="requestFilter" placeholder="${esc(t("rq.filterHint"))}" aria-controls="requestBoard"><p class="muted" id="requestCount" role="status"></p></div><div class="board${cols.length > 4 ? " five" : ""}" id="requestBoard"></div>`
      : `<div class="panel empty"><div class="empty-ico">${ICON.inbox}</div><h3>${esc(t("rq.empty"))}</h3><p>${esc(t("rq.emptyD"))}</p>
          <p style="margin-top:14px"><a class="btn-primary btn-brand" href="#/staff/new">${ICON.plus}${esc(t("nav.new"))}</a></p></div>`}`;
    const filter = $("#requestFilter");
    if (filter) {
      const draw = () => {
        const q = filter.value.trim().toLocaleLowerCase(LANG);
        const filtered = S.cases.filter((c) => [companyOf(c), c.summary, placeOf(c), areaLabel(c.area, c.niche)].join(" ").toLocaleLowerCase(LANG).includes(q));
        $("#requestCount").textContent = t("rq.count", { n: filtered.length, total: S.cases.length });
        $("#requestBoard").innerHTML = cols.map(([l, st]) => {
          const xs = filtered.filter((c) => stage(c) === st);
          return `<section class="col ${st}" aria-labelledby="col-${st}"><div class="col-h"><span id="col-${st}">${esc(t(l))}<small>${esc(t(l + "D"))}</small></span><i class="count" aria-label="${xs.length}">${xs.length || ""}</i></div>
            ${xs.map(card).join("") || `<div class="col-empty">${esc(t(q ? "rq.noMatch" : "col.empty"))}</div>`}</section>`;
        }).join("");
      };
      filter.addEventListener("input", draw);
      draw();
    }
  }

  /* ======================= STAFF: dashboard (Apertus cost, search recall) ======================= */
  const ROUTE_KEY = { "GET /search": "search", "POST /companies/suggest": "suggest", "POST /cases": "create",
    "POST /cases/{cid}/rematch": "rematch", "POST /cases/{cid}/draft": "draft", "POST /cases/{cid}/brief": "brief",
    "POST /cases/{cid}/matches": "matches", "POST /cases/{cid}/details": "details", "POST /briefs/{token}/reply": "reply" };
  const routeLabel = (r) => (ROUTE_KEY[r] ? t("db.r." + ROUTE_KEY[r]) : r);
  const nf = (v, d = 0) => (v == null ? "–" : Number(v).toLocaleString(LANG, { minimumFractionDigits: d, maximumFractionDigits: d }));
  // small amounts keep four decimals: a search costs fractions of a centime
  const chfN = (v) => (v == null ? "–" : nf(v, v !== 0 && Math.abs(v) < 0.1 ? 4 : 2));
  const chf = (v) => (v == null ? "–" : `CHF ${chfN(v)}`);
  const secs = (v) => (v == null ? "–" : `${nf(v, v < 1 ? 2 : 1)} s`);
  const pctTxt = (v) => (v == null ? "–" : LANG === "en" ? `${nf(v)}%` : `${nf(v)} %`);

  async function viewDashboard() {
    view().innerHTML = spinner();
    let d;
    try { d = await api("/dashboard"); }
    catch (e) { view().innerHTML = `<div class="callout warn">${ICON.info}<span>${esc(t("err"))}: ${esc(e.message)}</span></div>`; return; }
    const lv = d.live, pr = d.price, rx = d.reextraction, runs = d.quality, target = d.recall_target;
    const tile = (label, value, sub) => `<div class="db-tile"><span class="db-l">${esc(label)}</span><b class="db-v">${esc(value)}</b>${sub ? `<span class="db-s">${esc(sub)}</span>` : ""}</div>`;
    const table = (head, rows, num) => `<div class="db-scroll"><table class="db-table"><thead><tr>${head.map((h, i) => `<th scope="col"${num.includes(i) ? ' class="n"' : ""}>${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${num.includes(i) ? ' class="n"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    const priceNote = pr.configured
      ? `<p class="muted">${esc(t("db.priceSet", { i: nf(pr.in_chf_per_m, 2), o: nf(pr.out_chf_per_m, 2), m: pr.model }))}</p>`
      : `<div class="callout warn">${ICON.info}<span>${esc(t("db.priceTodo", { i: nf(pr.in_chf_per_m, 2), o: nf(pr.out_chf_per_m, 2) }))}</span></div>`;

    const cost = !lv.requests ? `<p class="muted">${esc(t("db.noUsage"))}</p>` : `
      <div class="db-tiles">
        ${tile(t("db.perReq"), chf(lv.cost_per_request_chf), lv.cases.length ? t("db.perReqD", { n: lv.cases.length }) : "")}
        ${tile(t("db.total"), chf(lv.cost_chf), t("db.totalD", { n: nf(lv.calls), t: nf(lv.prompt_tokens + lv.completion_tokens) }))}
        ${tile(t("db.lat"), secs(lv.median_s), t("db.latD", { p: secs(lv.p95_s) }))}
        ${tile(t("db.calls"), nf(lv.requests), t("db.callsD"))}
      </div>
      <h3 class="db-h3">${esc(t("db.byRoute"))}</h3>
      ${table([t("db.col.action"), t("db.col.req"), t("db.col.calls"), t("db.col.tokens"), t("db.col.cost"), t("db.col.median"), t("db.col.p95")],
        lv.by_route.map((r) => [esc(routeLabel(r.route)), nf(r.requests), nf(r.calls), nf(r.prompt_tokens + r.completion_tokens), esc(chfN(r.cost_chf)), esc(secs(r.median_s)), esc(secs(r.p95_s))]),
        [1, 2, 3, 4, 5, 6])}
      ${lv.cases.length ? `<h3 class="db-h3">${esc(t("db.byCase"))}</h3>
      ${table([t("db.col.company"), t("db.col.last"), t("db.col.calls"), t("db.col.tokens"), t("db.col.cost")],
        lv.cases.map((c) => [c.deleted ? `<span class="muted">${esc(t("db.deleted"))}</span>` : `<a href="#/staff/case/${esc(c.id)}">${esc(c.company || c.id)}</a>`,
          `<time datetime="${esc(c.last)}">${esc(fmtDate(c.last))}</time>`, nf(c.calls), nf(c.prompt_tokens + c.completion_tokens), esc(chfN(c.cost_chf))]),
        [2, 3, 4])}` : ""}`;

    // recall per run: one series, one hue; the target is a marked line, and a run below it says so in words
    const bars = runs.filter((r) => r.recall != null).map((r) => {
      const below = r.recall < target;
      return `<div class="db-bar" title="${esc(`${r.tag}: ${pctTxt(r.recall)} (${t("db.target", { t: target })})`)}">
        <span class="db-bar-l">${esc(r.tag)}</span>
        <span class="db-track"><span class="db-fill" style="width:${Math.max(0, Math.min(100, r.recall))}%"></span><span class="db-goal" style="left:${target}%"></span></span>
        <span class="db-bar-v">${esc(pctTxt(r.recall))}${below ? ` <span class="db-below">${ICON.info}${esc(t("db.below"))}</span>` : ""}</span></div>`;
    }).join("");
    const quality = !runs.length ? `<p class="muted">${esc(t("db.noRuns"))}</p>` : `
      <p class="muted">${esc(t("db.qualityD", { q: runs[runs.length - 1].queries ?? "–", t: target }))}</p>
      <div class="db-bars" role="img" aria-label="${esc(runs.map((r) => `${r.tag} ${pctTxt(r.recall)}`).join(", "))}">${bars}
        <div class="db-axis"><span></span><span class="db-goal-l" style="left:${target}%">${esc(t("db.target", { t: target }))}</span></div></div>
      ${table([t("db.col.run"), t("db.col.recall"), t("db.col.twins"), t("db.col.trace"), t("db.col.abst"), t("db.col.lat"), t("db.col.callsQ"), t("db.col.cpq")],
        runs.map((r) => [`<b>${esc(r.tag)}</b><br><span class="muted">${esc(r.mode)}${r.llm ? ` · ${esc(r.model)}` : ` · ${esc(t("db.noLlm"))}`}</span>`,
          esc(pctTxt(r.recall)), esc(pctTxt(r.twins)), esc(pctTxt(r.traceability)), esc(pctTxt(r.abstention)), esc(secs(r.median_s)),
          nf(r.calls_per_query, 1), esc(r.llm ? chf(r.cost_per_query_chf) : "–")]),
        [1, 2, 3, 4, 5, 6, 7])}`;

    view().innerHTML = `<div class="page-h"><div><h1>${esc(t("db.title"))}</h1><p>${esc(t("db.lead"))}</p></div></div>
      ${priceNote}
      <section class="panel db-sec" aria-labelledby="dbCost"><div class="panel-h"><h2 id="dbCost">${esc(t("db.cost"))}</h2>
        ${lv.since ? `<span class="muted">${esc(t("db.since", { d: fmtDate(lv.since, false) }))}</span>` : ""}</div>${cost}</section>
      <section class="panel db-sec" aria-labelledby="dbRx"><div class="panel-h"><h2 id="dbRx">${esc(t("db.rx"))}</h2></div>
        <div class="db-tiles">${tile(t("db.rx"), chf(rx.cost_chf), t("db.rxD", { n: nf(rx.pages), t: nf(rx.tokens) }))}</div>
        <p class="muted">${esc(rx.basis === "measured" ? t("db.rxMeasured", { c: nf(rx.measured_calls) }) : t("db.rxEstimated"))}</p></section>
      <section class="panel db-sec" aria-labelledby="dbQ"><div class="panel-h"><h2 id="dbQ">${esc(t("db.quality"))}</h2></div>${quality}</section>`;
  }

  /* ======================= STAFF/officer: new request (company link or info first) ======================= */
  /** New request: "Broad search" (one free-text field, any language) or "Company details" (website,
   *  documents, filters). The broad search reads place and topic itself and shows what it understood. */
  async function viewNew(prev = {}) {
    const mode = prev.mode || store.get("nav-newmode", "broad");
    store.set("nav-newmode", mode);
    if (mode === "broad") return viewNewBroad(prev);
    await viewNewDetails(prev);
    $(".back")?.insertAdjacentHTML("afterend", newTabs("details"));
    bindNewTabs();
  }

  const newTabs = (mode) => `<div class="nr-tabs"><div class="seg-tabs" role="tablist">
      <button type="button" role="tab" data-mode="broad" aria-selected="${mode === "broad"}" class="${mode === "broad" ? "on" : ""}">${ICON.search.replace("<svg", '<svg class="i"')}${esc(t("bs.tab"))}</button>
      <button type="button" role="tab" data-mode="details" aria-selected="${mode === "details"}" class="${mode === "details" ? "on" : ""}">${esc(t("bs.tab2"))}</button></div></div>`;
  const bindNewTabs = () => $$("[data-mode]").forEach((b) => b.addEventListener("click", () => viewNew({ mode: b.dataset.mode })));
  const matchScopeField = (value = 'bern') => `<label class="field nr-wide">${esc(t('scope.title'))}<select name="match_scope" id="matchScope" class="input"><option value="bern" ${value === 'bern' ? 'selected' : ''}>${esc(t('scope.bern'))}</option><option value="north" ${value === 'north' ? 'selected' : ''}>${esc(t('scope.north'))}</option></select><small>${esc(t('scope.hint'))}</small></label>`;

  async function viewNewBroad(prev = {}) {
    await areas();
    const examples = ["glucose company in Milan", "Glukosesensor-Firma aus München", "fabricant d'implants à Lausanne",
      "azienda di robotica chirurgica a Torino", "interpresa da glucosa a Cuira"];
    view().innerHTML = `<a class="back" href="#/staff/requests">${ICON.back}${esc(t("cs.back"))}</a>${newTabs("broad")}
      <form class="nr" id="broadForm" novalidate>
        <h1>${esc(t("bs.title"))}</h1>
        <div class="nr-box">${ICON.search}<input id="bsQ" maxlength="500" autocomplete="off" spellcheck="false" aria-label="${esc(t("bs.title"))}" value="${esc(prev.q || "")}">
          <button class="btn-primary btn-brand" type="submit">${esc(t("nw.find"))}</button></div>
        <p class="form-err" id="bsErr" role="alert"></p>
        ${matchScopeField(prev.match_scope)}<div class="bs-understood" id="bsU" aria-live="polite"></div>
        <div class="chips nr-try"><span class="muted">${esc(t("nw.try"))}:</span>${examples.map((x) => `<button type="button" class="chip" data-q="${esc(x)}">${esc(x)}</button>`).join("")}</div>
        <p class="muted bs-langs">${esc(t("bs.langs"))}</p>
      </form>`;
    bindNewTabs();
    const q = $("#bsQ");
    let timer, seq = 0;
    const preview = async () => {
      const v = q.value.trim(), my = ++seq;
      if (v.length < 2) { $("#bsU").innerHTML = `<span class="muted">${esc(t("bs.hint"))}</span>`; return; }
      let u; try { u = await api(`/understand?q=${encodeURIComponent(v)}`); } catch { return; }
      if (my !== seq) return;                                   // a newer keystroke already answered
      const place = [u.city, u.canton !== u.city ? u.canton : "", u.country].filter(Boolean).join(", ");
      const topic = u.area ? areaLabel(u.area, u.niche) : "";
      $("#bsU").innerHTML = [
        place && `<span class="u-chip place"><b>${esc(t("bs.place"))}</b>${esc(place)}</span>`,
        topic && `<span class="u-chip topic"><b>${esc(t("bs.topic"))}</b>${esc(topic)}</span>`,
        u.rest && `<span class="u-chip rest"><b>${esc(t("bs.searching"))}</b>“${esc(u.rest)}”</span>`,
      ].filter(Boolean).join("") || `<span class="muted">${esc(t("bs.hint"))}</span>`;
    };
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(preview, 220); if ($("#bsErr").textContent) { $("#bsErr").textContent = ""; q.removeAttribute("aria-invalid"); } });
    $$("[data-q]").forEach((b) => b.addEventListener("click", () => { q.value = b.dataset.q; preview(); q.focus(); }));
    preview(); q.focus();
    $("#broadForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const v = q.value.trim();
      if (v.length < 3) { $("#bsErr").textContent = t("bs.short"); q.setAttribute("aria-invalid", "true"); q.setAttribute("aria-describedby", "bsErr"); q.focus(); return; }
      const scope = $('#matchScope').value;
      // a website link goes straight to the analysis; otherwise Apertus suggests companies to choose from
      $("#broadForm").innerHTML = spinner(t("sg.working"));
      let s;
      try { s = await api("/companies/suggest", { method: "POST", body: { text: v, lang: LANG } }); }
      catch (e) { s = { candidates: [], message: e.message }; }
      if (s.link) return createBroad(v, { match_scope: scope });
      showSuggestions(v, s, scope);
    });
  }

  /** Create the request from the broad search, with the chosen company's website when there is one. */
  async function createBroad(v, extra = {}) {
    view().querySelector("#broadForm, .sg").outerHTML = `<div class="nr">${spinner(t("nw.working"))}</div>`;
    try { const c = await api("/cases", { method: "POST", body: asStaff({ request_text: v, broad: true, lang: LANG, ...extra }) }); go(`#/staff/case/${c.id}`); }
    catch (e) { toast(`${t("err")}: ${e.message}`, 9000); viewNewBroad({ q: v, match_scope: extra.match_scope }); }
  }

  /** Up to three companies, each verified on its own homepage; the officer picks one, or continues without. */
  function showSuggestions(v, s, scope = "bern") {
    const cs = s.candidates || [];
    $("#broadForm").outerHTML = `<section class="nr sg" aria-labelledby="sgT"><h1 id="sgT" tabindex="-1">${esc(t("sg.title"))}</h1>
      ${cs.length ? `<p class="muted">${esc(t("sg.lead", { q: v }))}</p>
        <div class="sg-list">${cs.map((c, i) => `<article class="sg-card">
          <div class="sg-h"><h3>${esc(c.name)}</h3><a href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener">${ICON.ext}${esc(hostPath(c.url).split("/")[0])}</a></div>
          ${c.description ? `<p>${esc(c.description)}</p>` : ""}
          <div class="sg-meta">${c.place_found ? `<span class="u-chip place">${esc(t("sg.place", { p: c.place_found }))}</span>` : ""}
            ${c.topic_found?.length ? `<span class="u-chip topic"><b>${esc(t("sg.topic"))}</b>${esc(c.topic_found.slice(0, 3).join(", "))}</span>` : ""}</div>
          <button class="btn-primary btn-brand" type="button" data-pick="${i}">${esc(t("sg.choose"))}</button></article>`).join("")}</div>
        <p class="muted sg-ai">${ICON.info}${esc(t("sg.ai"))}</p>` : ""}
      ${s.message ? `<div class="callout warn">${ICON.info}<span>${esc(s.message)}</span></div>` : ""}
      <div class="actions"><button class="btn" type="button" id="sgNone">${esc(t("sg.none"))}</button>
        <button class="btn" type="button" id="sgBack">${ICON.back}${esc(t("sg.back"))}</button></div></section>`;
    $$("[data-pick]").forEach((b) => b.addEventListener("click", () => {
      const c = cs[+b.dataset.pick]; createBroad(v, { company_url: c.url, company: c.name, match_scope: scope });
    }));
    $("#sgNone").addEventListener("click", () => createBroad(v, { match_scope: scope }));
    $("#sgBack").addEventListener("click", () => viewNewBroad({ q: v, match_scope: scope }));
    $(".sg h1").focus?.();
  }

  async function viewNewDetails(prev = {}) {
    if (!S.examples) { try { S.examples = await api("/examples"); } catch { S.examples = []; } }
    const ar = await areas();
    const f = { area: prev.area || "", niche: prev.niche || "", docs: [...(prev.documents || [])], pending: 0 };
    view().innerHTML = `<a class="back" href="#/staff/requests">${ICON.back}${esc(t("cs.back"))}</a>
      <form class="nr" id="newForm" novalidate>
        <h1>${esc(t("nw.q"))}</h1>
        <div class="nr-box">${ICON.link}<input name="company_url" id="nrUrl" inputmode="url" autocomplete="off" spellcheck="false" maxlength="500" placeholder="${esc(t("nw.urlPh"))}">
          <button class="btn-primary btn-brand" type="submit" id="nrGo">${esc(t("nw.find"))}</button></div>
        <p class="form-err" id="nrErr" role="alert"></p>
        <div class="nr-f nr-wide"><span>${esc(t("nw.docs"))}</span>
          <label class="drop" id="drop">${ICON.file}<span>${esc(t("nw.docsHint"))}</span>
            <input type="file" id="nrFiles" multiple accept="${esc(DOC_ACCEPT)}"></label>
          <ul class="docs" id="docList"></ul></div>
        <label class="nr-f nr-wide"><span>${esc(t("nw.info"))}</span>
          <textarea name="request_text" id="nrText" rows="3" maxlength="12000" placeholder="${esc(t("nw.infoPh"))}"></textarea></label>
        <label class="nr-f nr-wide"><span>${esc(t("nw.need"))}</span>
          <input name="need" maxlength="500" autocomplete="off" placeholder="${esc(t("nw.needPh"))}"></label>
        ${S.examples.length ? `<div class="chips nr-try"><span class="muted">${esc(t("nw.try"))}:</span>${S.examples.map((x, i) => `<button type="button" class="chip" data-ex="${i}">${esc(L(x.label) || x.company)}</button>`).join("")}</div>` : ""}
        ${matchScopeField(prev.match_scope)}<div class="nr-filters">
          <label class="nr-f"><span>${esc(t("nw.company2"))}</span><input name="company" maxlength="200" autocomplete="off"></label>
          <label class="nr-f"><span>${esc(t("nw.countryAny"))}</span><input name="country" list="countryList" maxlength="100" autocomplete="off">
            <datalist id="countryList">${COUNTRIES.map((c) => `<option value="${esc(c)}">`).join("")}</datalist></label>
          <label class="nr-f" id="cantonBox" hidden><span>${esc(t("nw.canton"))}</span><select class="input" name="canton"><option value="">${esc(t("nw.cantonAny"))}</option>
            ${CANTONS.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
        </div>
        <div class="nr-area"><div class="nr-lbl">${esc(t("nw.area"))}</div>
          <div class="chips" id="areaChips"><button type="button" class="chip on" data-area="">${esc(t("nw.any"))}</button>
            ${ar.map((a) => `<button type="button" class="chip" data-area="${esc(a.id)}">${esc(L(a.label))}</button>`).join("")}</div>
          <div id="nicheBox" hidden><div class="nr-lbl">${esc(t("nw.niche"))}</div><div class="chips" id="nicheChips"></div></div></div>
      </form>`;
    const form = $("#newForm"), url = $("#nrUrl"), txt = $("#nrText");
    form.addEventListener("input", () => { if ($("#nrErr").textContent) { $("#nrErr").textContent = ""; url.removeAttribute("aria-invalid"); } });
    for (const k of ["company_url", "request_text", "need", "company", "country"]) form[k].value = prev[k] || "";
    url.focus();
    const drawDocs = (errors = []) => {
      $("#docList").innerHTML = f.docs.map((d, i) => `<li class="ok">${ICON.check}<b>${esc(d.name)}</b><span class="muted">${esc(d.kind)}${d.pages ? " · " + esc(t("nw.pages", { n: d.pages })) : ""}</span>
          <button type="button" class="icon-btn" data-rm="${i}" aria-label="${esc(t("nw.remove"))}">${ICON.x}</button></li>`).join("")
        + (f.pending ? `<li class="muted">${esc(t("nw.uploading", { n: f.pending }))}</li>` : "")
        + errors.map((e) => `<li class="bad"><b>${esc(e.name)}</b> ${esc(e.msg)}</li>`).join("");
      $$("[data-rm]").forEach((b) => b.addEventListener("click", () => { f.docs.splice(+b.dataset.rm, 1); drawDocs(); }));
      $("#nrGo").disabled = f.pending > 0;
    };
    const upload = async (files) => {
      const errors = [];
      files = [...files].slice(0, Math.max(0, 5 - f.docs.length));
      f.pending += files.length; drawDocs();
      await Promise.all(files.map(async (file) => {
        try {
          if (file.size > DOC_MAX_MB * 1e6) throw new Error(t("nw.tooBig", { n: DOC_MAX_MB }));
          const r = await fetch(`/kb/documents?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file,
            headers: { "Content-Type": "application/octet-stream" } });
          const j = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `${r.status}`);
          f.docs.push(j);
        } catch (e) { errors.push({ name: file.name, msg: e.message }); }
        finally { f.pending -= 1; drawDocs(errors); }
      }));
    };
    $("#nrFiles").addEventListener("change", (ev) => { upload(ev.target.files); ev.target.value = ""; });
    const drop = $("#drop");
    ["dragenter", "dragover"].forEach((k) => drop.addEventListener(k, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((k) => drop.addEventListener(k, () => drop.classList.remove("over")));
    drop.addEventListener("drop", (ev) => { ev.preventDefault(); upload(ev.dataTransfer.files); });
    drawDocs();
    const syncCanton = () => { const sw = isSwiss(form.country.value); $("#cantonBox").hidden = !sw; if (!sw) form.canton.value = ""; };
    form.country.addEventListener("input", syncCanton); syncCanton(); form.canton.value = prev.canton || "";
    const drawNiches = () => {
      $$("#areaChips .chip").forEach((c) => c.classList.toggle("on", c.dataset.area === f.area));
      const A = ar.find((a) => a.id === f.area);
      $("#nicheBox").hidden = !A;
      $("#nicheChips").innerHTML = A ? `<button type="button" class="chip ${!f.niche ? "on" : ""}" data-niche="">${esc(t("nw.any"))}</button>` +
        A.niches.map((n) => `<button type="button" class="chip ${f.niche === n.id ? "on" : ""}" data-niche="${esc(n.id)}">${esc(L(n.label))}</button>`).join("") : "";
      $$("#nicheChips .chip").forEach((c) => c.addEventListener("click", () => { f.niche = c.dataset.niche; drawNiches(); }));
    };
    drawNiches();
    $$("#areaChips .chip").forEach((c) => c.addEventListener("click", () => { f.area = c.dataset.area; f.niche = ""; drawNiches(); }));
    $$("[data-ex]").forEach((b) => b.addEventListener("click", () => {
      const x = S.examples[+b.dataset.ex];
      url.value = ""; txt.value = x.request_text || ""; form.need.value = "";
      form.company.value = x.company || ""; form.country.value = x.country || ""; syncCanton(); form.canton.value = x.canton || "";
      f.area = x.area || ""; f.niche = x.niche || ""; f.example = x; drawNiches();
    }));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const ex = f.example?.company === form.company.value ? f.example : null;
      if (f.pending) return;
      const body = asStaff({ company_url: url.value.trim(), documents: f.docs, request_text: txt.value.trim(), need: form.need.value.trim(),
        company: form.company.value.trim(), country: form.country.value.trim(), canton: form.canton.value,
        area: f.area, niche: f.niche, lang: LANG, match_scope: $('#matchScope').value, contact_name: ex?.contact_name || "", contact_email: ex?.contact_email || "" });
      if (!body.company_url && !body.documents.length && body.request_text.length < 3) {
        $("#nrErr").textContent = t("nw.missing"); url.setAttribute("aria-invalid", "true"); url.setAttribute("aria-describedby", "nrErr"); url.focus(); return;
      }
      form.innerHTML = spinner(t(body.company_url ? "nw.reading" : body.documents.length ? "nw.readingDocs" : "nw.working"));
      try { const c = await api("/cases", { method: "POST", body }); go(`#/staff/case/${c.id}`); }
      catch (e) { toast(`${t("err")}: ${e.message}`, 9000); viewNew({ ...body, mode: "details" }); }
    });
  }

  /* ======================= STAFF: request page (different per role) ======================= */
  let CASE = null;
  // 2 = choosing partners, 3 = pitch & invite, 4 = invited (all steps done)
  const stepOf = (c) => (c.status !== "new" ? 4 : c.outreach?.brief || c.matches.some((m) => m.selected) || S.kbSelections?.[c.id]?.length ? 3 : 2);
  async function viewCase(id) {
    view().innerHTML = spinner();
    await Promise.all([loadGlossary(), areas()]);
    try { CASE = await api(`/cases/${encodeURIComponent(id)}`); }
    catch { view().innerHTML = `<div class="panel empty"><h3>${esc(t("err"))}</h3><p><a href="${roleHome()}">${esc(t("cs.back"))}</a></p></div>`; return; }
    if (!Object.prototype.hasOwnProperty.call(S.kbSelections || {}, id)) {
      S.kbSelections = { ...(S.kbSelections || {}), [id]: CASE.outreach?.brief?.knowledge_sources || [] };
    }
    renderOfficerCase();
  }

  function sidePanels(c) {
    return `<aside class="side">
      ${cantonMember?.can_manage_knowledge ? '<div class="panel" id="privateKnowledge"></div>' : ''}
      <div class="panel contact-box"><div class="panel-h"><h2>${esc(t("cs.contact"))}</h2></div>
        <dl><dt>${esc(t("nw.company"))}</dt><dd>${esc(c.company || "—")}</dd>
          ${c.contact_name ? `<dt>${esc(t("nw.contact"))}</dt><dd>${esc(c.contact_name)}</dd>` : ""}
          ${c.contact_email ? `<dt>Email</dt><dd><a href="mailto:${esc(c.contact_email)}">${esc(c.contact_email)}</a></dd>` : ""}
          ${placeOf(c) ? `<dt>${esc(t("nw.country"))}</dt><dd>${esc(placeOf(c))}</dd>` : ""}</dl>
        <button class="link-btn" type="button" id="editDetails">${esc(t("d.edit"))}</button>
        <form class="details" id="detailsForm" hidden>
          <label class="field">${esc(t("nw.company"))}<input name="company" required maxlength="200" value="${esc(c.company)}"></label>
          <label class="field">${esc(t("nw.contact"))}<input name="contact_name" maxlength="200" value="${esc(c.contact_name)}"></label>
          <label class="field">${esc(t("nw.email"))}<input name="contact_email" type="email" maxlength="200" value="${esc(c.contact_email)}"></label>
          <div class="actions" style="margin-top:10px"><button class="btn-primary btn-sm" type="submit">${ICON.check}${esc(t("d.save"))}</button></div></form></div>
      <div class="panel"><div class="panel-h"><h2>${esc(t("cs.activity"))}</h2></div>
        <ol class="timeline">${[...c.events].reverse().map((e) => `<li><b>${esc(e.actor)}</b> · ${esc(e.text)}<time>${esc(fmtDate(e.at))}</time></li>`).join("")}</ol></div>
      <button class="link-btn" id="delCase" type="button">${ICON.trash}${esc(t("cs.delete"))}</button>
    </aside>`;
  }

  function termLabel(w) {
    const f = w.found_as || w.term;
    const shown = f.length <= 4 || /^(ce|mdr|fda|iso|ivdr|ai|ip)\b/.test(f) ? f.toUpperCase() : f;
    return shown.toLowerCase() === (w.term || "").toLowerCase() ? shown : `${shown} · ${w.term}`;
  }

  function panelUnderstand(a) {
    const site = CASE.website, docs = CASE.documents || [];
    const list = (xs) => (xs.length ? `<ul>${xs.map((n) => `<li>${jargon(n)}</li>`).join("")}</ul>` : "<p>—</p>");
    const offer = a.offerings || [], kw = a.keywords || [];
    const ai = a.generated_by === "apertus";
    return `<section class="panel done"><div class="panel-h"><h2><span class="num">✓</span>${esc(t("u.title"))}</h2>
        ${provBadge(a.generated_by, t(ai ? "prov.apertus" : "prov.rules"))}</div>
      <p class="prov">${esc(t(ai ? "prov.apertus" : "prov.rules"))}</p>
      <p class="plain-summary">${jargon(a.summary)}</p>
      <div class="facts"><div class="fact"><h4>${esc(t("u.does"))}</h4><p>${jargon(a.company_does || "—")}</p></div>
        <div class="fact"><h4>${esc(t("u.needs"))}</h4>${list(a.company_needs)}</div></div>
      ${offer.length || kw.length ? `<div class="facts biz">
        ${offer.length ? `<div class="fact"><h4>${esc(t("u.offer"))}</h4>${list(offer)}</div>` : ""}
        ${kw.length ? `<div class="fact"><h4>${esc(t("u.kw"))}</h4><div class="kw">${kw.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div></div>` : ""}</div>` : ""}
      ${site || docs.length || CASE.request_text ? `<details class="orig"><summary>${esc(t("u.sources"))}</summary><div class="web-src">${ICON.link}<div>
        ${site ? `<b>${esc(t("u.web"))}</b> <a href="${esc(safeUrl(site.url))}" target="_blank" rel="noopener">${esc(hostPath(site.url))}</a>
          <ul>${site.pages.map((p) => `<li><a href="${esc(safeUrl(p.url))}" target="_blank" rel="noopener">${esc(p.title || hostPath(p.url))}</a></li>`).join("")}</ul>` : ""}
        ${docs.length ? `<b>${esc(t("u.docs"))}</b><ul>${docs.map((d) => `<li>${esc(d.name)} <span class="muted">(${esc(d.kind)}${d.pages ? ", " + esc(t("nw.pages", { n: d.pages })) : ""})</span>
          <details class="doc-text"><summary>${esc(t("u.docText"))}</summary><div class="orig-text">${esc(d.text)}</div></details></li>`).join("")}</ul>` : ""}
        ${CASE.request_text ? `<b>${esc(t(site || docs.length || CASE.need ? "u.info" : "u.orig"))}</b><div class="orig-text">${esc(CASE.request_text)}</div>` : ""}
      </div></div></details>` : ""}</section>`;
  }

  /* ---------- officer ---------- */
  function renderOfficerCase() {
    const c = CASE, step = stepOf(c), cls = (n) => (n < step ? "done" : n === step ? "now" : "");
    view().innerHTML = `<a class="back" href="#/staff/requests">${ICON.back}${esc(t("cs.back"))}</a>
      <div class="case-h"><div><h1>${esc(companyOf(c))}</h1><div class="sub">${placeOf(c) ? `<span>${esc(placeOf(c))}</span>` : ""}${c.area ? `<span class="tag">${esc(areaLabel(c.area, c.niche))}</span>` : ""}<span>${esc(t("cs.received"))} ${esc(fmtDate(c.created_at))}</span></div></div>${pill(c.status)}</div>
      ${cantonMember?.can_manage_knowledge ? `<p><a class="btn" href="#/staff/discovery?lead=${esc(c.id)}">${esc(window.CompanyDiscovery?.title(LANG) || 'Explore complementary companies')}</a></p>` : ''}
      <ol class="stepper three" aria-label="${esc(t("rq.workflow"))}">${[1, 2, 3].map((n) => `<li class="${cls(n)}" ${n === step ? 'aria-current="step"' : ""}><span class="dotn" aria-hidden="true">${n < step ? "✓" : n}</span>${esc(t("step." + n))}</li>`).join("")}</ol>
      ${repliesBox(c)}
      <div class="case-grid"><div>${panelUnderstand(c.analysis)}${officerPartners(c, step)}${officerPitch(c, step)}</div>${sidePanels(c)}</div>`;
    bindOfficerCase();
    if (cantonMember?.can_manage_knowledge) {
      const target = $('#privateKnowledge');
      target.innerHTML = `<h2>${esc(window.KnowledgeWorkspace.title(LANG))}</h2>${spinner()}`;
      api('/kb/search?scope=' + encodeURIComponent(c.match_scope || 'bern') + '&q=' + encodeURIComponent((c.analysis.search_query || c.analysis.summary || c.company).slice(0, 500))).then((hits) => {
        if (!target.isConnected) return;
        const selected = S.kbSelections?.[c.id] || [];
        target.innerHTML = `<div class="panel-h"><h2>${esc(window.KnowledgeWorkspace.title(LANG))}</h2></div><p class="muted">${esc(t(c.match_scope === 'north' ? 'scope.north' : 'scope.bern'))}</p><p class="muted">${esc(t('kb.shareHint'))}</p>` + (hits.length ? hits.map((hit, i) => `<details><summary>${esc(hit.company)} · ${esc(hit.canton)} · ${esc(hit.source)}</summary><p>${esc(hit.snippet)}</p><p class="muted">${esc(hit.method || '')} · ${esc(hit.explanation || '')}</p>${hit.kind === 'web' ? `<label class="kb-check"><input type="checkbox" data-kb-source="${i}" ${selected.some((s) => s.source_id === hit.source_id) ? 'checked' : ''}>${esc(t('kb.share'))}</label>` : ''}<a href="#/staff/knowledge?company=${esc(hit.id)}">${esc(window.KnowledgeWorkspace.title(LANG))}</a></details>`).join('') : `<p class="muted">${esc(t('kb.noContext'))}</p>`);
        target.querySelectorAll('[data-kb-source]').forEach((checkbox) => checkbox.onchange = () => {
          const chosen = hits[+checkbox.dataset.kbSource];
          const refs = (S.kbSelections?.[c.id] || []).filter((s) => s.source_id !== chosen.source_id);
          if (checkbox.checked) refs.push({ id: chosen.id, source_id: chosen.source_id, revision: chosen.revision });
          S.kbSelections = { ...(S.kbSelections || {}), [c.id]: refs };
          const y = window.scrollY; renderOfficerCase(); window.scrollTo(0, y);
        });
      }).catch((e) => { if (target.isConnected) target.textContent = e.message; });
    }
  }

  /** One cited asset as a structured, traceable result. */
  function sourceCard(x) {
    const row = (k, v) => (v ? `<div class="sf"><dt>${esc(t(k))}</dt><dd>${v}</dd></div>` : "");
    const list = (xs) => (xs?.length ? xs.map(esc).join(" · ") : "");
    const aff = [x.unit, x.institute && x.institute !== x.institution ? x.institute : "", x.institution].filter(Boolean).map(esc).join(" · ");
    return `<li class="src-card" id="src-${x.n}"><div class="src-h"><span class="src-n">${x.n}</span><h3>${esc(x.name)}</h3><span class="type-badge ${esc(x.entity_type)}">${esc(x.kind)}</span></div>
      <dl class="src-f">${row("src.function", esc(x.role || ""))}${row("src.aff", aff)}
        ${row("src.contact", x.contact ? `<a href="mailto:${esc(x.contact)}">${esc(x.contact)}</a>` : "")}
        ${row("src.expertise", (x.expertise || []).map((e) => `<span class="tag">${esc(e)}</span>`).join(" "))}
        ${row("src.projects", list(x.projects))}${row("src.infra", list(x.infrastructure))}
        ${row("src.about", esc(x.about || ""))}${row("src.why", esc(x.why || ""))}</dl>
      <div class="src-links"><a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener">${ICON.ext}${esc(t("src.link"))}: ${esc(hostPath(x.url))}</a>
        ${(x.links || []).map((u) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${ICON.ext}${esc(hostPath(u))}</a>`).join("")}</div></li>`;
  }

  /** Step 2: what Bern offers — readable prose; each [n] jumps to the structured source below. */
  function officerPartners(c, step) {
    const o = c.offer, srcs = o?.sources || [];
    const ns = new Set(srcs.map((x) => String(x.n)));
    const text = esc(o?.text || "").replace(/\[(\d+)\]/g, (all, n) => (ns.has(n) ? `<button type="button" class="cite" data-cite="${n}" aria-label="${esc(t("m.sources"))} ${n}">${n}</button>` : all));
    return `<section class="panel ${step === 2 ? "active" : step > 2 ? "done" : ""}">
      <div class="panel-h"><h2><span class="num">${step > 2 ? "✓" : 2}</span>${esc(t("m.title"))}</h2></div>
      ${srcs.length ? `<p class="offer-text">${text}</p>
        <div class="sub-h">${esc(t("m.sources"))} <span class="muted" style="font-weight:400">${esc(t("m.sourcesLead"))}</span></div>
        <ol class="offer-src">${srcs.map(sourceCard).join("")}</ol>`
        : `<div class="callout warn">${ICON.info}<span>${esc(c.no_match_message || o?.text || t("m.none"))}</span></div>`}</section>`;
  }

  function nextSlots() {
    const out = [], d = new Date(), pad = (n) => String(n).padStart(2, "0");
    while (out.length < 3) { d.setDate(d.getDate() + 1); if (d.getDay() === 0 || d.getDay() === 6) continue;
      out.push(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${out.length % 2 ? "14" : "10"}:00`); }
    return out;
  }

  /** Step 4: Output 1 (plain, for her) + Output 2 (executive brief, for the CEO) + sending. */
  /** The brief's private link still opens for the company (not disabled, not expired). */
  const briefLive = (b) => !!b && !b.revoked_at && !(b.expires_at && new Date(b.expires_at) <= new Date());

  /** What the company answered from the brief, newest first. */
  const repliesBox = (c) => {
    const rs = c.outreach?.replies || [];
    if (!rs.length) return "";
    return `<div class="replies"><h3>${ICON.inbox}${esc(t("rp.title"))}</h3>${[...rs].reverse().map((r) => `<div class="reply">
      <div class="rp-h"><b>${esc(t("rp." + r.kind))}</b><time>${esc(fmtDate(r.at))}</time></div>
      ${r.message ? `<p>${esc(r.message)}</p>` : ""}
      <div class="rp-who">${[r.name, r.email].filter(Boolean).map(esc).join(" · ")}
        ${r.email || c.contact_email ? `<a class="btn btn-sm" href="mailto:${esc(r.email || c.contact_email)}?subject=${encodeURIComponent(`${companyOf(c)} — Bern`)}">${ICON.mail}${esc(t("rp.answer"))}</a>` : ""}</div></div>`).join("")}</div>`;
  };

  function pitchOutputs(c) {
    const b = c.outreach?.brief;
    if (!b) return "";
    const s = b.stats || {}, live = briefLive(b);
    return `<div class="pitch-grid">
      <div class="explain"><h3><span class="tag1">${esc(t("i.forYou"))}</span>${esc(t("i.forYouT"))}</h3>
        ${b.summary?.text ? `<p>${esc(b.summary.text)}</p>` : ''}
        <div id="operatorEcosystem"></div>
        <details><summary>${esc(t('i.moreWhy'))}</summary>${(b.explainer || []).map((sec) => `<section><h4>${esc(sec.title)}</h4>${sec.lines.map((l) => `<p>${jargon(l.text)}</p>${l.plain ? `<p class="mean">${esc(l.plain)}</p>` : ""}`).join("")}</section>`).join("")}</details></div>
      <div class="preview"><div class="pv-top"><small>${esc(t("i.forCeo"))} · ${esc(t("i.forCeoT"))}</small><h3>${b.data.company ? `${esc(b.data.company)} × ` : ""}Bern</h3><p>${esc(b.data.hook)}</p></div>
        <div class="pitch-commercial">${b.data.objective ? `<p>${esc(b.data.objective)}</p>` : ''}${(b.data.featured || []).slice(0, 3).map((o) => `<section><h4><a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${esc(o.name)}</a></h4><p>${esc(o.benefit)}</p></section>`).join('')}</div>
        <div class="pv-body"><div class="stat-chips"><span><b>${b.data.items.length}</b> ${esc(t("i.teams"))}</span><span><b>${s.claims ?? "–"}</b> ${esc(t("i.stmt"))}</span>
          <span><b>${s.publications ?? 0}</b> ${esc(t("i.pubs"))}</span><span><b>${s.sources ?? b.data.sources.length}</b> ${esc(t("i.srcs"))}</span></div>
          ${live ? `<div class="actions"><a class="btn-primary btn-brand btn-sm" href="#/b/${esc(b.token)}?preview=1" target="_blank" rel="noopener">${ICON.doc}${esc(t("i.open"))}</a>
            <a class="btn btn-sm" href="#/b/${esc(b.token)}?preview=1&print=1" target="_blank" rel="noopener">${ICON.printer}${esc(t("i.pdf"))}</a>
            <button class="btn btn-sm" type="button" id="copyBrief">${ICON.link}${esc(t("i.copyLink"))}</button></div>`
            : `<div class="callout warn">${ICON.info}<span>${esc(b.revoked_at ? t("bv.revoked") : t("bv.expired", { d: fmtDate(b.expires_at, false) }))}</span></div>`}
          <p class="muted" style="margin:0">${esc(t("bf.prepared", { d: fmtDate(b.at) }))} · ${esc(b.lang.toUpperCase())}</p>
          ${live ? `<p class="link-state"><span>${ICON.eye}${esc(b.views ? t("bv.seen", { n: b.views, d: fmtDate(b.last_view) }) : t("bv.none"))}</span>
            ${b.expires_at ? `<span>${esc(t("bv.until", { d: fmtDate(b.expires_at, false) }))}</span>` : ""}
            <button class="linkish" type="button" id="revokeBrief">${esc(t("bv.revoke"))}</button></p>` : ""}</div></div></div>`;
  }

  function officerPitch(c, step) {
    if (cantonMember?.role === 'agent') return `<section class="panel"><p>${esc(t('role.noPitch'))}</p></section>`;
    if (step < 3) return `<section class="panel locked"><div class="panel-h"><h2><span class="num">3</span>${esc(t("i.title"))}</h2><span class="muted">${ICON.lock}</span></div>
      <p class="muted" style="margin:0">${esc(t("i.locked"))}</p></section>`;
    const done = ["contacted", "call_scheduled", "interested", "closed"].includes(c.status), b = c.outreach?.brief;
    return `<section class="panel ${done ? "done" : "active"}"><div class="panel-h"><h2><span class="num">${done ? "✓" : 3}</span>${esc(t("i.title"))}</h2></div>
      ${c.outreach?.sent_at ? `<div class="callout ok" style="margin-bottom:12px">${ICON.check}<span>${esc(t("i.doneEmail", { d: fmtDate(c.outreach.sent_at) }))}</span></div>` : ""}
      ${c.outreach?.call ? `<div class="callout ok" style="margin-bottom:12px">${ICON.cal}<span>${esc(t("i.doneCall", { d: c.outreach.call }))}</span></div>` : ""}
      <div class="actions"><button class="btn-primary btn-brand" id="prepBrief" type="button">${ICON.sparkle}${esc(t("i.gen"))}</button></div>
      <details class="pitch-branding"><summary>${esc(t('i.brandColor'))} / ${esc(t('i.brandLogo'))}</summary><div class="grid-form"><label class="field">${esc(t('i.brandColor'))}<input type="color" id="pitchColor" value="${esc(/^#[\da-f]{6}$/i.test(b?.data?.branding?.primary_color || '') ? b.data.branding.primary_color : '#dc0018')}"></label><label class="field">${esc(t('i.brandLogo'))}<input type="file" id="pitchLogo" accept="image/png,image/jpeg"></label></div></details>
      <div id="pitchBox">${pitchOutputs(c)}</div>
      ${briefLive(b) ? `<div class="sub-h">${ICON.mail}${esc(t("i.mail"))}</div>
        <div class="grid-form"><div class="field full">${esc(t("i.slots"))}<div class="slots">${nextSlots().map((s) => `<input type="datetime-local" class="slot" value="${s}" aria-label="${esc(t("i.slots"))}">`).join("")}</div></div>
          <label class="field">${esc(t("i.dur"))}<select class="input" id="callMin"><option>30</option><option>45</option><option>60</option></select></label></div>
        <div class="actions" style="margin-top:12px"><button class="btn-primary" id="prepMail" type="button">${ICON.mail}${esc(t("i.prepMail"))}</button>
          <button class="btn" id="dlIcs" type="button">${ICON.cal}${esc(t("i.ics"))}</button></div><div id="mailBox"></div>` : ""}
    </section>`;
  }

  function bindOfficerCase() {
    const c = CASE;
    if (c.outreach?.brief) window.PitchVisual?.mount($('#operatorEcosystem'), c.outreach.brief.data, { compact: true });
    const rerender = (keep = true) => { const y = window.scrollY; renderOfficerCase(); if (keep) window.scrollTo(0, y); };
    $$("[data-cite]").forEach((b) => b.addEventListener("click", () => {
      const el = $(`#src-${b.dataset.cite}`); if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    }));
    $("#delCase")?.addEventListener("click", async () => { if (!confirm(t("cs.confirmDelete"))) return; await api(`/cases/${c.id}`, { method: "DELETE" }); go("#/staff/requests"); });
    $("#editDetails")?.addEventListener("click", () => { $("#detailsForm").hidden = false; $("#detailsForm").company.focus(); });
    $("#detailsForm")?.addEventListener("submit", async (ev) => {
      ev.preventDefault(); const f = ev.target;
      try { CASE = await api(`/cases/${c.id}/details`, { method: "POST", body: asStaff({ company: f.company.value.trim(), contact_name: f.contact_name.value.trim(), contact_email: f.contact_email.value.trim() }) }); rerender(); }
      catch (e) { toast(e.message); }
    });
    $("#prepBrief")?.addEventListener("click", async (ev) => {
      ev.currentTarget.disabled = true;
      $("#pitchBox").setAttribute("aria-busy", "true");
      $("#pitchBox").innerHTML = spinner(t("i.working"));
      try {
        let company_logo;
        const logo = $('#pitchLogo')?.files?.[0];
        if (logo) {
          if (logo.size > 250000) throw new Error('Logo: maximum 250 KB.');
          company_logo = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('Logo could not be read')); reader.readAsDataURL(logo); });
        }
        await api(`/cases/${c.id}/brief`, { method: "POST", body: asStaff({ ui_lang: LANG, email: staff.email || "", team: staff.team || "", knowledge_sources: S.kbSelections?.[c.id] || [], primary_color: $('#pitchColor')?.value, ...(company_logo ? { company_logo } : {}) }) });
        CASE = await api(`/cases/${c.id}`); rerender();
      } catch (e) {
        rerender();
        const error = document.createElement("p");
        error.className = "callout warn";
        error.setAttribute("role", "alert");
        error.textContent = `${t("i.failed")} ${e.message}`;
        $("#pitchBox").prepend(error);
      }
    });
    $("#copyBrief")?.addEventListener("click", () => { navigator.clipboard?.writeText(briefUrl(c.outreach.brief.token)); toast(t("i.copied")); });
    $("#revokeBrief")?.addEventListener("click", async () => {
      if (!confirm(t("bv.revokeQ"))) return;
      try { CASE = await api(`/cases/${c.id}/brief/revoke`, { method: "POST", body: asStaff() }); rerender(); }
      catch (e) { toast(e.message); }
    });
    const slotLabels = () => $$(".slot").map((i) => i.value).filter(Boolean).map((v) => fmtDate(v, true, c.outreach?.brief?.lang || LANG));
    $("#prepMail")?.addEventListener("click", async () => {
      const lang = c.outreach.brief.lang;
      let delivery = { configured: false };
      try { delivery = await api(`/cases/${c.id}/delivery`); } catch {}
      const d = await api(`/cases/${c.id}/draft`, { method: "POST", body: asStaff({ lang, slots: slotLabels(), sender: staff.name, team: staff.team || "", link: delivery.public_link || briefUrl(c.outreach.brief.token) }) });
      $("#mailBox").innerHTML = `<div class="email-box"><label class="field">${esc(t("i.subj"))}<input id="mSubj" value="${esc(d.subject)}"></label>
        <label class="field">${esc(t("i.body"))}<textarea id="mBody">${esc(d.body)}</textarea></label>
        <div class="actions"><a class="btn-primary" id="mOpen" href="#">${ICON.mail}${esc(t("i.openMail"))}</a>
          <button class="btn" id="mCopy" type="button">${ICON.copy}${esc(t("i.copy"))}</button><button class="btn" id="mSent" type="button">${ICON.check}${esc(t("i.sent"))}</button><button class="btn-primary" id="mSendServer" type="button" ${delivery.configured && c.contact_email ? '' : 'disabled'}>${ICON.mail}${esc(t('i.send'))}</button></div><p class="muted" role="status" id="deliveryStatus">${delivery.configured ? '' : esc(t('i.smtpOff'))}</p></div>`;
      if (delivery.history?.length) $('#deliveryStatus').insertAdjacentHTML('afterend', `<details><summary>${esc(t('i.deliveryLog'))}</summary><ul>${delivery.history.map((h) => `<li>${esc(fmtDate(h.at))} · ${esc(t('delivery.' + h.status))}</li>`).join('')}</ul></details>`);
      $('#mSendServer').addEventListener('click', async (event) => {
        const button = event.currentTarget; button.disabled = true;
        try {
          const subject = $('#mSubj').value, body = $('#mBody').value;
          const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([c.id, c.contact_email, c.outreach.brief.at, subject, body])));
          const idempotency_key = [...new Uint8Array(digest)].map((v) => v.toString(16).padStart(2, '0')).join('');
          const result = await api(`/cases/${c.id}/delivery`, { method: 'POST', body: { subject, body, idempotency_key } });
          $('#deliveryStatus').textContent = t(result.status === 'sent' ? 'i.sentServer' : 'i.uncertain');
        } catch (error) { $('#deliveryStatus').textContent = error.message; button.disabled = false; }
      });
      $("#mOpen").addEventListener("click", (ev) => { ev.preventDefault();
        location.href = `mailto:${encodeURIComponent(c.contact_email || "")}?subject=${encodeURIComponent($("#mSubj").value)}&body=${encodeURIComponent($("#mBody").value)}`; });
      $("#mCopy").addEventListener("click", () => { navigator.clipboard?.writeText(`${$("#mSubj").value}\n\n${$("#mBody").value}`); toast("✓"); });
      $("#mSent").addEventListener("click", async () => {
        CASE = await api(`/cases/${c.id}/outcome`, { method: "POST", body: asStaff({ kind: "email", subject: $("#mSubj").value, body: $("#mBody").value }) });
        toast(t("st.contacted")); rerender(false);
      });
      $("#mBody").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("#dlIcs")?.addEventListener("click", async () => {
      const start = $$(".slot")[0]?.value; if (!start) return;
      const p = new URLSearchParams({ start, minutes: $("#callMin").value, organizer: staff.name, organizer_email: staff.email || "" });
      const a = document.createElement("a"); a.href = `/cases/${c.id}/invite.ics?${p}`; a.download = ""; a.click();
      CASE = await api(`/cases/${c.id}/outcome`, { method: "POST", body: asStaff({ kind: "call", detail: fmtDate(start) }) });
      toast(t("st.call_scheduled")); rerender();
    });
  }

  function viewStaffSearchHome() {
    view().innerHTML = `<section class="hero" style="padding-top:8px"><h1 style="font-size:28px">${esc(t("home.title"))}</h1>${searchBox("", "#/staff/search")}${exampleChips()}</section>`;
    bindSearchBox();
  }

  /* ======================= BRIEF: the CEO's executive brief ======================= */
  /** A source as a short clickable label: the page's subject ("Prof. X"), "doi:…", or the site's name. */
  const srcLabel = (s) => (s.kind === "doi" ? `doi:${s.url.replace(/^https?:\/\/doi\.org\//, "")}`
    : (s.label || "").includes(" — ") ? s.label.split(" — ").pop() : hostPath(s.url).split("/")[0]);
  async function viewBrief(token, params) {
    view().innerHTML = spinner();
    // the officer's own preview is not counted as an opening, and cannot send replies
    const preview = params.get("preview") === "1";
    let b;
    try { b = await api(`/briefs/${encodeURIComponent(token)}${preview ? "?preview=1" : ""}`); }
    catch (e) {
      let gone = null;   // 410: disabled or expired; the answer says, in the brief's language, whom to ask
      if (e.status === 410) { try { gone = JSON.parse(e.message); } catch {} }
      view().innerHTML = gone ? `<div class="panel empty"><h3>${esc(gone.labels[gone.state === "expired" ? "gone_expired" : "gone_revoked"])}</h3>
        <p>${esc(gone.labels.gone_lead)}${gone.email ? ` <a href="mailto:${esc(gone.email)}">${esc(gone.email)}</a>` : ""}</p></div>`
        : `<div class="panel empty"><h3>${esc(t("bf.missing"))}</h3></div>`;
      return;
    }
    const rl = b.reply;
    const lb = b.labels, sup = (n) => `<sup class="ref"><a href="#src-${n}" data-ref="${n}">[${n}]</a></sup>`;
    document.title = b.company ? `${b.company} × Bern` : "Bern";
    const nClaims = b.items.reduce((n, i) => n + (i.quote ? 1 : 0) + i.technical.length, 0) + b.proof.length;
    const nPubs = b.items.reduce((n, i) => n + i.publications.length, 0);
    view().innerHTML = `<article class="brief" lang="${esc(b.lang)}">
      <header class="b-hero"><div class="kick">${esc(b.kicker)}</div>
        ${/^data:image\/png;base64,/.test(b.branding?.company_logo || '') ? `<img class="recipient-logo" src="${esc(b.branding.company_logo)}" alt="${esc(b.company)}">` : ''}
        <h1>${b.company ? `${esc(b.company)} <span>×</span> ` : ""}Bern</h1><p>${esc(b.hook)}</p>
        <div class="stat-chips"><span><b>${b.items.length}</b> ${esc(lb.teams)}</span><span>${ICON.check}<b>${nClaims}</b> ${esc(lb.stmt)}</span>${nPubs ? `<span><b>${nPubs}</b> ${esc(lb.pubs_n)} (DOI)</span>` : ""}</div></header>

      ${b.needs?.length ? `<section class="b-sec"><h2>${esc(b.needs_title)}</h2><p class="b-lead">${esc(b.needs_lead)}</p><div class="b-needs">${b.needs.map((n) => `<article class="b-need">
        <div class="nd-q"><small>${esc(lb["n.need"])}</small><p>${esc(n.need)}</p></div>
        <div class="nd-a"><small>${esc(lb["n.answer"])}</small><p>${esc(n.solve)}</p>
          <p class="nd-with"><b>${esc(lb["n.with"])}:</b> ${n.partners.length ? n.partners.map((x) => `${esc(x.name)} ${sup(x.ref)}`).join(" · ") : esc(lb["n.canton"])}</p></div>
        <div class="nd-est">${n.figure ? `<small>${esc(lb["n.est"])}</small><div class="fig">${esc(n.figure)}</div><div class="gain">${esc(n.gain)}</div>` : ""}<p class="basis">${esc(n.basis)}</p>
          ${n.calc ? `<div class="calc"><small>${esc(lb["n.calc"])}</small><p>${esc(n.calc)}</p></div>` : ""}</div>
      </article>`).join("")}</div></section>` : ""}

      ${b.opportunities?.length ? `<section class="b-sec"><h2>${esc(b.opp_title)}</h2><div class="b-opp">${b.opportunities.map((o) => `<div>
        <h3>${esc(o.title)}</h3><p>${o.items.map((i) => `${esc(i.name)} ${sup(i.ref)}`).join(" · ")}</p></div>`).join("")}</div></section>` : ""}

      ${b.featured?.length ? `<section class="b-sec pitch-commercial"><p>${esc(b.objective || '')}</p>${b.featured.slice(0, 3).map((o) => `<section><h3><a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${esc(o.name)}</a></h3><p>${esc(o.benefit)}</p>${o.evidence?.ref ? sup(o.evidence.ref) : ''}</section>`).join('')}</section>` : ''}
      <section class="b-sec"><h2>${esc(lb.why)}</h2><div class="b-cards">${b.items.map((it, k) => `<article class="b-card">
        <div class="hd">${avatar(it.name, it.type)}<div><h3>${esc(it.name)}</h3><div class="meta">${[it.role, it.unit, it.institution].filter(Boolean).map(esc).join(" · ")} ${sup(it.page_ref)}</div></div></div>
        ${it.topics.length ? `<div class="tags">${it.topics.map((x) => `<span class="topic" title="${esc(x.plain)}">${esc(x.term)}</span>`).join("")}</div>
          <p class="plain-topic">${esc(it.topics[0].plain)}</p>` : ""}
        ${it.quote ? `<blockquote>“${esc(it.quote.text)}” ${sup(it.quote.ref)}${it.quote.via ? `<span class="via">— ${esc(it.quote.via)}</span>` : ""}</blockquote>` : ""}
        <button class="tech-btn" type="button" aria-expanded="false" aria-controls="tech-${k}">${esc(lb.tech)} <span class="chev">▾</span></button>
        <div class="tech" id="tech-${k}"><ul>${it.technical.map((x) => `<li><span class="f">${esc(x.field)}</span>${esc(x.text)} ${sup(x.ref)}</li>`).join("")}</ul>
          ${it.publications.length ? `<h4>${esc(lb.pubs)}</h4><ul>${it.publications.map((p) => `<li class="pub">${esc(p.citation)} — <a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">doi:${esc(p.doi)}</a> ${sup(p.page_ref)}</li>`).join("")}</ul>` : ""}</div>
      </article>`).join("")}</div></section>

      ${b.proof.length ? `<section class="b-sec"><h2>${esc(lb.proof)}</h2><div class="b-proof">${b.proof.map((h) => `<div><div class="fig">${esc(h.figure)}</div><div class="lbl">${esc(h.label)}</div>
        <q>${esc(h.quote)}</q> ${sup(h.ref)}</div>`).join("")}</div></section>` : ""}

      <section class="b-sec"><h2>${esc(lb.visit)}</h2><div class="b-visit">
        <ol class="agenda">${b.agenda.map((a) => `<li>${esc(a)}</li>`).join("")}</ol>
        <div class="cta-box">${rl ? `<a class="btn-primary" href="#bReply" id="bCta">${ICON.cal}${esc(lb.cta)}</a>`
          : b.contact.email ? `<a class="btn-primary" href="mailto:${esc(b.contact.email)}?subject=${encodeURIComponent(`${b.company} — Bern`)}">${ICON.cal}${esc(lb.cta)}</a>` : ""}
          <button class="btn" type="button" id="bPrint">${ICON.printer}${esc(lb.pdf)}</button>
          <small>${esc(b.from)}${b.contact.email ? ` · <a href="mailto:${esc(b.contact.email)}">${esc(b.contact.email)}</a>` : ""}</small></div></div></section>

      ${rl ? `<section class="b-sec b-reply no-print" id="bReply"><h2>${esc(rl.title)}</h2>
        <form id="replyForm" class="reply-form"><p class="b-lead">${esc(rl.lead)}</p>
          <div class="rp-kinds" role="radiogroup" aria-label="${esc(rl.title)}">${["visit", "call", "question"].map((k, i) =>
            `<label class="rp-kind"><input type="radio" name="kind" value="${k}"${i ? "" : " checked"}><span>${esc(rl[k])}</span></label>`).join("")}</div>
          <div class="grid-form"><label class="field">${esc(rl.name)}<input class="input" name="name" maxlength="120" autocomplete="name"></label>
            <label class="field">${esc(rl.email)}<input class="input" name="email" type="email" maxlength="200" autocomplete="email"></label>
            <label class="field full">${esc(rl.message)}<textarea class="input" name="message" maxlength="1500" rows="3" placeholder="${esc(rl.hint)}"></textarea></label></div>
          ${preview ? `<div class="callout warn">${ICON.info}<span>${esc(rl.preview)}</span></div>` : ""}
          <div class="actions"><button class="btn-primary" type="submit"${preview ? " disabled" : ""}>${ICON.send}${esc(rl.send)}</button><small>${esc(rl.privacy)}</small></div>
        </form></section>` : ""}

      <div class="honest">${ICON.shield}<span>${esc(b.honest)}</span></div>
      <section class="b-sources"><h2>${esc(lb.sources)}</h2><div class="src-chips">${b.sources.map((s, i) =>
        `<a class="src-chip" id="src-${i + 1}" href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener" title="${esc(s.label)}"><b>${i + 1}</b><span>${esc(srcLabel(s))}</span></a>`).join("")}</div></section>
    </article>`;
    window.PitchVisual?.mount(view().querySelector('.brief'), b, { skipIntro: params.get('print') === '1' });
    $$(".tech-btn").forEach((btn) => btn.addEventListener("click", () => {
      const box = $("#" + btn.getAttribute("aria-controls")), open = !box.classList.contains("open");
      box.classList.toggle("open", open); btn.setAttribute("aria-expanded", open);
    }));
    $$("sup.ref a").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); const el = $("#src-" + a.dataset.ref); el?.scrollIntoView({ behavior: "smooth", block: "center" }); el?.animate?.([{ background: "var(--mark)" }, { background: "transparent" }], { duration: 1600 }); }));
    $("#bPrint").addEventListener("click", () => window.print());
    $("#bCta")?.addEventListener("click", (ev) => { ev.preventDefault(); $("#bReply").scrollIntoView({ behavior: "smooth" }); $("#replyForm input[name=kind]:checked")?.focus(); });
    $("#replyForm")?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = ev.target, btn = f.querySelector("button[type=submit]");
      if (preview) return;
      btn.disabled = true;
      try {
        await api(`/briefs/${encodeURIComponent(token)}/reply`, { method: "POST", body: { kind: f.kind.value,
          name: f.name.value.trim(), email: f.email.value.trim(), message: f.message.value.trim() } });
        f.outerHTML = `<div class="callout ok" role="status">${ICON.check}<span>${esc(rl.sent)}</span></div>`;
      } catch { btn.disabled = false; toast(rl.error); }
    });
    if (params.get("print") === "1") setTimeout(() => window.print(), 400);
  }

  /* ======================= boot ======================= */
  function boot() {
    document.documentElement.dataset.theme = store.get("nav-theme", "light") === "dark" ? "dark" : "light";
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && document.body.classList.contains("sheet-open")) { $("#detail")?.classList.remove("open"); document.body.classList.remove("sheet-open"); }
      if (ev.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) && $("#sQ")) { ev.preventDefault(); $("#sQ").focus(); }
    });
    document.addEventListener("click", (ev) => {
      if (document.body.classList.contains("sheet-open") && !ev.target.closest("#detail") && !ev.target.closest(".card")) {
        $("#detail")?.classList.remove("open"); document.body.classList.remove("sheet-open");
      }
    });
    window.addEventListener("hashchange", route);
    route();
  }
  boot();
})();
