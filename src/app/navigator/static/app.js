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
  };

  /* ======================= i18n ======================= */
  const I18N = {
    en: {
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
      "d.title": "Company details", "d.lead": "Needed for the pitch and the email to the company.", "d.save": "Save details", "d.edit": "Edit",
      "cs.back": "All requests", "cs.backQ": "Review queue", "cs.received": "Received", "cs.contact": "Company contact", "cs.activity": "Activity",
      "cs.delete": "Delete request", "cs.confirmDelete": "Delete this request permanently?",
      "step.1": "Company profile", "step.2": "Bern assets", "step.3": "Pitch & invitation", 
      "u.title": "Company profile",
      "u.does": "Business activity", "u.needs": "Business needs", "u.orig": "Original request",
      "m.title": "Matching assets in Bern", "m.lead": "Select the assets to include in the pitch. Each entry is supported by a public source.",
      "m.again": "Search again", "m.more": "Find more in search", "m.sel": "selected", "m.none": "No matching assets were found in the indexed sources.",
      "m.src": "source", 
      "i.title": "Pitch & invite", "i.locked": "Select at least one asset above to prepare the pitch.",
      "i.lead": "Two outputs: an internal briefing for you and a concise, fully sourced executive brief for the company's leadership. Objective: a visit to Bern.",
      "i.lang": "Language of the pitch", "i.prep": "Prepare the pitch", "i.regen": "Update the pitch",
      "i.forYou": "For you", "i.forYouT": "Internal briefing", "i.forCeo": "For the CEO", "i.forCeoT": "Executive brief",
      "i.open": "Open the brief", "i.pdf": "Save as PDF", "i.copyLink": "Copy link", "i.copied": "Link copied",
      "i.teams": "research teams", "i.stmt": "sourced statements", "i.pubs": "publications", "i.srcs": "sources",
      "i.mail": "Send", "i.slots": "Propose call times", "i.dur": "Call length (min)", "i.prepMail": "Prepare the email",
      "i.subj": "Subject", "i.body": "Email (editable)", "i.openMail": "Open in email app", "i.copy": "Copy text", "i.sent": "Mark as sent",
      "i.ics": "Calendar invite (.ics)", "i.doneEmail": "Invitation sent on {d}.", "i.doneCall": "Call scheduled: {d}.",
      "ctx": "Adding partners to the request from {c}", "ctxBack": "Back to the request",
      "bf.prepared": "prepared {d}", "bf.missing": "This brief does not exist or has been withdrawn.", "bf.teams": "research teams",
      "err": "Something went wrong",
      "st.pitch": "Pitch ready",
      "bs.tab": "Broad search",
      "bs.tab2": "Company details",
      "bs.title": "What are you looking for?",
      "bs.ph": "e.g. glucose company in Milan — in any language",
      "bs.place": "Place",
      "bs.topic": "Topic",
      "bs.searching": "Searching Bern for",
      "bs.hint": "Type a topic, a company type and/or a place.",
      "bs.langs": "Works in English, Deutsch, Français, Italiano and Rumantsch.",
    },
    de: {
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
      "d.title": "Angaben zur Firma", "d.lead": "Nötig für den Pitch und die E-Mail an die Firma.", "d.save": "Angaben speichern", "d.edit": "Bearbeiten",
      "cs.back": "Alle Anfragen", "cs.backQ": "Prüfungen", "cs.received": "Eingegangen", "cs.contact": "Kontakt der Firma", "cs.activity": "Verlauf",
      "cs.delete": "Anfrage löschen", "cs.confirmDelete": "Diese Anfrage endgültig löschen?",
      "step.1": "Firmenprofil", "step.2": "Berner Angebote", "step.3": "Pitch & Einladung", 
      "u.title": "Firmenprofil",
      "u.does": "Geschäftstätigkeit", "u.needs": "Geschäftlicher Bedarf", "u.orig": "Ursprüngliche Anfrage",
      "m.title": "Passende Angebote in Bern", "m.lead": "Wählen Sie die Angebote für den Pitch. Jeder Eintrag ist durch eine öffentliche Quelle belegt.",
      "m.again": "Neu suchen", "m.more": "Mehr in der Suche finden", "m.sel": "ausgewählt", "m.none": "In den indexierten Quellen wurden keine passenden Angebote gefunden.",
      "m.src": "Quelle", 
      "i.title": "Pitch & Einladung", "i.locked": "Wählen Sie oben mindestens ein Angebot, um den Pitch vorzubereiten.",
      "i.lead": "Zwei Ergebnisse: ein internes Briefing für Sie und ein kurzes, vollständig belegtes Executive Brief für die Geschäftsleitung der Firma. Ziel: ein Besuch in Bern.",
      "i.lang": "Sprache des Pitch", "i.prep": "Pitch vorbereiten", "i.regen": "Pitch aktualisieren",
      "i.forYou": "Für Sie", "i.forYouT": "Internes Briefing", "i.forCeo": "Für die Geschäftsleitung", "i.forCeoT": "Executive Brief",
      "i.open": "Brief öffnen", "i.pdf": "Als PDF speichern", "i.copyLink": "Link kopieren", "i.copied": "Link kopiert",
      "i.teams": "Forschungsteams", "i.stmt": "belegte Aussagen", "i.pubs": "Publikationen", "i.srcs": "Quellen",
      "i.mail": "Versand", "i.slots": "Gesprächstermine vorschlagen", "i.dur": "Dauer (Min.)", "i.prepMail": "E-Mail vorbereiten",
      "i.subj": "Betreff", "i.body": "E-Mail (bearbeitbar)", "i.openMail": "Im E-Mail-Programm öffnen", "i.copy": "Text kopieren", "i.sent": "Als gesendet markieren",
      "i.ics": "Kalendereinladung (.ics)", "i.doneEmail": "Einladung gesendet am {d}.", "i.doneCall": "Gespräch geplant: {d}.",
      "ctx": "Partner für die Anfrage von {c} hinzufügen", "ctxBack": "Zurück zur Anfrage",
      "bf.prepared": "erstellt {d}", "bf.missing": "Dieses Dokument existiert nicht oder wurde zurückgezogen.", "bf.teams": "Forschungsteams",
      "err": "Etwas ist schiefgelaufen",
      "st.pitch": "Pitch bereit",
      "bs.tab": "Freie Suche",
      "bs.tab2": "Angaben zur Firma",
      "bs.title": "Wonach suchen Sie?",
      "bs.ph": "z. B. Glukose-Firma aus Mailand — in jeder Sprache",
      "bs.place": "Ort",
      "bs.topic": "Thema",
      "bs.searching": "Suche in Bern nach",
      "bs.hint": "Thema, Art der Firma und/oder Ort eingeben.",
      "bs.langs": "Funktioniert auf English, Deutsch, Français, Italiano und Rumantsch.",
    },
    fr: {
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
      "d.title": "Coordonnées de l'entreprise", "d.lead": "Nécessaires pour le pitch et l'e-mail à l'entreprise.", "d.save": "Enregistrer", "d.edit": "Modifier",
      "cs.back": "Toutes les demandes", "cs.backQ": "Validations", "cs.received": "Reçue", "cs.contact": "Contact de l'entreprise", "cs.activity": "Historique",
      "cs.delete": "Supprimer la demande", "cs.confirmDelete": "Supprimer définitivement cette demande ?",
      "step.1": "Profil de l'entreprise", "step.2": "Atouts bernois", "step.3": "Pitch & invitation", 
      "u.title": "Profil de l'entreprise",
      "u.does": "Activité", "u.needs": "Besoins commerciaux", "u.orig": "Demande originale",
      "m.title": "Atouts correspondants à Berne", "m.lead": "Sélectionnez les atouts à inclure dans le pitch. Chaque entrée s'appuie sur une source publique.",
      "m.again": "Relancer", "m.more": "Chercher davantage", "m.sel": "sélectionné(s)", "m.none": "Aucun atout correspondant n'a été trouvé dans les sources indexées.",
      "m.src": "source", 
      "i.title": "Pitch & invitation", "i.locked": "Sélectionnez au moins un atout ci-dessus pour préparer le pitch.",
      "i.lead": "Deux livrables : une note interne pour vous et une note de synthèse concise et entièrement sourcée pour la direction de l'entreprise. Objectif : une visite à Berne.",
      "i.lang": "Langue du pitch", "i.prep": "Préparer le pitch", "i.regen": "Mettre à jour le pitch",
      "i.forYou": "Pour vous", "i.forYouT": "Note interne", "i.forCeo": "Pour la direction", "i.forCeoT": "Note de direction",
      "i.open": "Ouvrir la note", "i.pdf": "Enregistrer en PDF", "i.copyLink": "Copier le lien", "i.copied": "Lien copié",
      "i.teams": "équipes de recherche", "i.stmt": "affirmations sourcées", "i.pubs": "publications", "i.srcs": "sources",
      "i.mail": "Envoi", "i.slots": "Proposer des créneaux d'appel", "i.dur": "Durée (min)", "i.prepMail": "Préparer l'e-mail",
      "i.subj": "Objet", "i.body": "E-mail (modifiable)", "i.openMail": "Ouvrir dans la messagerie", "i.copy": "Copier le texte", "i.sent": "Marquer comme envoyé",
      "i.ics": "Invitation calendrier (.ics)", "i.doneEmail": "Invitation envoyée le {d}.", "i.doneCall": "Appel planifié : {d}.",
      "ctx": "Ajout de partenaires à la demande de {c}", "ctxBack": "Retour à la demande",
      "bf.prepared": "préparée le {d}", "bf.missing": "Cette note n'existe pas ou a été retirée.", "bf.teams": "équipes de recherche",
      "err": "Une erreur est survenue",
      "st.pitch": "Pitch prêt",
      "bs.tab": "Recherche libre",
      "bs.tab2": "Détails de l'entreprise",
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
  const pill = (status) => `<span class="pill st-${esc(status)}">${esc(t("st." + status))}</span>`;
  const spinner = (msg = "") => `<div class="working"><span class="spinner"></span>${msg ? `<span>${esc(msg)}</span>` : ""}</div>`;
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
  async function refreshCases() { try { S.cases = await api("/cases"); } catch { S.cases = []; } }
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
  const langSel = () => `<select id="lang" class="lang" aria-label="Language">${["en", "de", "fr"].map((l) => `<option value="${l}" ${l === LANG ? "selected" : ""}>${l.toUpperCase()}</option>`).join("")}</select>`;
  const themeBtn = () => `<button class="icon-btn" id="themeBtn" type="button" aria-label="Dark mode" title="Dark mode">${ICON.moon}</button>`;

  function renderChrome(shell, active) {
    const bar = $("#topbar");
    bar.className = `topbar ${shell === "staff" ? "staff" : ""} ${shell === "brief" ? "brief" : ""}`;
    document.body.classList.toggle("brief-mode", shell === "brief");
    const brand = (sub, href) => `<a class="brand" href="${href}"><svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8"/><path d="M9 23V9h7.5a4 4 0 0 1 0 8H9m7.5 0a3.5 3.5 0 0 1 0 6H9"/></svg>
      <span class="brand-text"><b>Bern Expertise Navigator</b><small>${esc(sub)}</small></span></a>`;
    const tab = (href, key, label, count = "") => `<a href="${href}" class="${active === key ? "on" : ""}" ${active === key ? 'aria-current="page"' : ""}>${esc(label)}${count ? `<i class="count ${key === "queue" ? "warn" : ""}">${count}</i>` : ""}</a>`;
    if (shell === "brief") {
      bar.innerHTML = `<div class="topbar-in">${brand(t("brand.briefSub"), location.hash)}<div class="topbar-right">${themeBtn()}</div></div>`;
      $("#foot").innerHTML = `<span>${esc(t("foot.brief"))}</span>`;
    } else if (shell === "public") {
      bar.innerHTML = `<div class="topbar-in">${brand(t("brand.sub"), "#/")}
        <nav class="tabs" aria-label="Main">${tab("#/", "search", t("nav.search"))}${tab("#/directory", "dir", t("nav.dir"))}</nav>
        <div class="topbar-right">${langSel()}${themeBtn()}<a class="staff-link" href="#/staff">${ICON.lock}<span>${esc(t("nav.staff"))}</span></a></div></div>`;
      $("#foot").innerHTML = `<span>${esc(t("foot.public"))}</span>`;
    } else {
      const open = S.cases.filter((c) => c.status === "new" && !c.has_brief).length;   // still to do
      const nav = !staff ? "" : tab("#/staff/requests", "requests", t("nav.requests"), open || "") + tab("#/staff/new", "new", t("nav.new")) + tab("#/staff/search", "ssearch", t("nav.search"));
      bar.innerHTML = `<div class="topbar-in">${brand(t("brand.staffSub"), staff ? roleHome() : "#/staff")}<span class="staff-tag">${esc(t("staff.tag"))}</span>
        ${nav ? `<nav class="tabs" aria-label="Workspace">${nav}</nav>` : ""}
        <div class="topbar-right">${langSel()}${themeBtn()}
          ${staff ? `<div class="whoami"><span class="av officer">${esc(initialsOf(staff.name))}</span>
            <span class="txt"><b>${esc(staff.name)}</b>${staff.team ? `<small>${esc(staff.team)}</small>` : ""}</span>
            <button type="button" id="switchUser">${esc(t("who.switch"))}</button></div>` : ""}
          <a class="staff-link" href="#/">${ICON.ext}<span>${esc(t("nav.public"))}</span></a></div></div>`;
      $("#foot").innerHTML = `<span>${esc(t("foot.staff"))}</span>`;
      $("#switchUser")?.addEventListener("click", () => go("#/staff/who"));
    }
    $("#lang")?.addEventListener("change", (ev) => { LANG = ev.target.value; store.set("nav-lang", LANG); route(); });
    $("#themeBtn").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const nx = cur === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = nx; store.set("nav-theme", nx);
    });
  }

  /* ======================= router ======================= */
  async function route() {
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
    if (p[1] === "who" || !staff) { renderChrome("staff", ""); return viewIdentity(); }
    await refreshCases();
    const sub = p[1] || "";
    if (!["requests", "new", "search", "case"].includes(sub)) return go(roleHome());
    renderChrome("staff", { requests: "requests", new: "new", search: "ssearch", case: "requests" }[sub] || "");
    if (sub === "requests") return viewRequests();
    if (sub === "new") return viewNew();
    if (sub === "search") return params.get("q") ? viewSearch(params, "staff") : viewStaffSearchHome();
    if (sub === "case" && p[2]) return viewCase(p[2]);
    return go(roleHome());
  }

  /* ======================= PUBLIC: home ======================= */
  const searchBox = (q = "", target = "#/search") => `<form class="searchbox" id="sForm" role="search" data-target="${target}">${ICON.search}
      <input id="sQ" type="search" value="${esc(q)}" placeholder="${esc(t("ph"))}" aria-label="${esc(t("go"))}" autocomplete="off">
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
        <i class="t-dot src"></i>${esc(x.name === "unibe" ? "UniBE" : x.name.toUpperCase())} <span class="muted">${st.entities_per_source[x.name] ?? 0}</span></button>`).join("")}</div>
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
      <div class="results-view"><div class="results-col"><div class="results-head" id="rHead"><span class="cnt">…</span></div>
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
    return `<article class="card" tabindex="0" data-i="${i}">
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
      ${d.expanded_terms.length ? `<span>${esc(t("res.also"))}</span>${d.expanded_terms.slice(0, 7).map((x) => `<span class="term">${esc(x)}</span>`).join("")}` : ""}`;
    if (d.abstained) {
      $("#rList").innerHTML = `<div class="abstain"><div class="empty-ico" style="color:var(--warn);background:var(--warn-bg)">${ICON.shield}</div>
        <h3>${esc(t("res.none"))}</h3><p>${esc(d.message)}</p><p class="muted" style="margin-top:10px">${esc(t("res.noneHint"))}</p></div>`;
      return;
    }
    $("#rList").innerHTML = d.results.map((r, i) => resultCard(r, i, terms, ctx)).join("");
    $$(".card", $("#rList")).forEach((c) => {
      c.addEventListener("click", (ev) => { if (!ev.target.closest("a,button")) selectResult(+c.dataset.i, true, ctx); });
      c.addEventListener("keydown", (ev) => { if (ev.key === "Enter") selectResult(+c.dataset.i, true, ctx); });
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
      </form></div>`;
    $("#idForm").name.focus();
    $$("[data-rec]").forEach((b) => b.addEventListener("click", () => { setStaff(rec[+b.dataset.rec]); go(roleHome()); }));
    $("#idForm").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = ev.target;
      setStaff({ name: f.name.value.trim(), email: f.email.value.trim(), team: f.team.value.trim() });
      go(roleHome());
    });
  }

  /* ======================= STAFF/officer: requests board ======================= */
  async function viewRequests() {
    await areas();
    const stage = (c) => (c.status !== "new" ? "done" : c.has_brief ? "ready" : "todo");
    const by = (st) => S.cases.filter((c) => stage(c) === st);
    const cols = [["col.todo", "todo"], ["col.ready", "ready"], ["col.done", "done"]];
    const card = (c) => `<a class="case-card" href="#/staff/case/${esc(c.id)}"><h3>${esc(companyOf(c))}</h3><p>${esc(c.summary)}</p>
      <div class="case-meta">${pill(c.status === "new" && c.has_brief ? "pitch" : c.status)}${c.niche || c.area ? `<span class="tag">${esc(areaLabel(c.area, c.niche))}</span>` : ""}${placeOf(c) ? `<span>${esc(placeOf(c))}</span>` : ""}
      ${c.selected ? `<span>${c.selected} ${esc(t("partners"))}</span>` : ""}
      <span>${esc(fmtDate(c.updated_at, false))}</span></div></a>`;
    const kpi = (v, l) => `<div class="kpi"><div class="v">${v}</div><div class="l">${esc(t(l))}</div></div>`;
    view().innerHTML = `<div class="page-h"><div><h1>${esc(t("rq.title"))}</h1><p>${esc(t("rq.lead"))}</p></div>
        <a class="btn-primary btn-brand" href="#/staff/new">${ICON.plus}${esc(t("nav.new"))}</a></div>
      <div class="kpis">${kpi(by("todo").length, "kpi.open")}${kpi(by("ready").length, "kpi.ready")}${kpi(by("done").length, "kpi.invited")}</div>
      ${S.cases.length ? `<div class="board">${cols.map(([l, st]) => { const xs = by(st);
        return `<section class="col" aria-label="${esc(t(l))}"><div class="col-h"><span>${esc(t(l))}</span><i class="count">${xs.length || ""}</i></div>
          ${xs.map(card).join("") || `<div class="col-empty">${esc(t("col.empty"))}</div>`}</section>`; }).join("")}</div>`
      : `<div class="panel empty"><div class="empty-ico">${ICON.inbox}</div><h3>${esc(t("rq.empty"))}</h3><p>${esc(t("rq.emptyD"))}</p>
          <p style="margin-top:14px"><a class="btn-primary btn-brand" href="#/staff/new">${ICON.plus}${esc(t("nav.new"))}</a></p></div>`}`;
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

  async function viewNewBroad(prev = {}) {
    await areas();
    const examples = ["glucose company in Milan", "Glukosesensor-Firma aus München", "fabricant d'implants à Lausanne",
      "azienda di robotica chirurgica a Torino", "interpresa da glucosa a Cuira"];
    view().innerHTML = `<a class="back" href="#/staff/requests">${ICON.back}${esc(t("cs.back"))}</a>${newTabs("broad")}
      <form class="nr" id="broadForm" novalidate>
        <h1>${esc(t("bs.title"))}</h1>
        <div class="nr-box">${ICON.search}<input id="bsQ" maxlength="500" autocomplete="off" spellcheck="false" placeholder="${esc(t("bs.ph"))}" value="${esc(prev.q || "")}">
          <button class="btn-primary btn-brand" type="submit">${esc(t("nw.find"))}</button></div>
        <div class="bs-understood" id="bsU" aria-live="polite"></div>
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
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(preview, 220); });
    $$("[data-q]").forEach((b) => b.addEventListener("click", () => { q.value = b.dataset.q; preview(); q.focus(); }));
    preview(); q.focus();
    $("#broadForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const v = q.value.trim();
      if (v.length < 3) { q.focus(); return; }
      $("#broadForm").innerHTML = spinner(t("nw.working"));
      try { const c = await api("/cases", { method: "POST", body: asStaff({ request_text: v, broad: true, lang: LANG }) }); go(`#/staff/case/${c.id}`); }
      catch (e) { toast(`${t("err")}: ${e.message}`, 9000); viewNewBroad({ q: v }); }
    });
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
        <div class="nr-f nr-wide"><span>${esc(t("nw.docs"))}</span>
          <label class="drop" id="drop">${ICON.file}<span>${esc(t("nw.docsHint"))}</span>
            <input type="file" id="nrFiles" multiple accept="${esc(DOC_ACCEPT)}"></label>
          <ul class="docs" id="docList"></ul></div>
        <label class="nr-f nr-wide"><span>${esc(t("nw.info"))}</span>
          <textarea name="request_text" id="nrText" rows="3" maxlength="12000" placeholder="${esc(t("nw.infoPh"))}"></textarea></label>
        <label class="nr-f nr-wide"><span>${esc(t("nw.need"))}</span>
          <input name="need" maxlength="500" autocomplete="off" placeholder="${esc(t("nw.needPh"))}"></label>
        ${S.examples.length ? `<div class="chips nr-try"><span class="muted">${esc(t("nw.try"))}:</span>${S.examples.map((x, i) => `<button type="button" class="chip" data-ex="${i}">${esc(L(x.label) || x.company)}</button>`).join("")}</div>` : ""}
        <div class="nr-filters">
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
          const r = await fetch(`/documents?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file,
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
        area: f.area, niche: f.niche, lang: LANG, contact_name: ex?.contact_name || "", contact_email: ex?.contact_email || "" });
      if (!body.company_url && !body.documents.length && body.request_text.length < 3) { toast(t("nw.missing")); url.focus(); return; }
      form.innerHTML = spinner(t(body.company_url ? "nw.reading" : body.documents.length ? "nw.readingDocs" : "nw.working"));
      try { const c = await api("/cases", { method: "POST", body }); go(`#/staff/case/${c.id}`); }
      catch (e) { toast(`${t("err")}: ${e.message}`, 9000); viewNew({ ...body, mode: "details" }); }
    });
  }

  /* ======================= STAFF: request page (different per role) ======================= */
  let CASE = null;
  // 2 = choosing partners, 3 = pitch & invite, 4 = invited (all steps done)
  const stepOf = (c) => (c.status !== "new" ? 4 : c.matches.some((m) => m.selected) ? 3 : 2);
  async function viewCase(id) {
    view().innerHTML = spinner();
    await Promise.all([loadGlossary(), areas(), archetypes()]);
    try { CASE = await api(`/cases/${encodeURIComponent(id)}`); }
    catch { view().innerHTML = `<div class="panel empty"><h3>${esc(t("err"))}</h3><p><a href="${roleHome()}">${esc(t("cs.back"))}</a></p></div>`; return; }
    renderOfficerCase();
  }

  function sidePanels(c) {
    return `<aside class="side">
      <div class="panel contact-box"><div class="panel-h"><h2>${esc(t("cs.contact"))}</h2></div>
        <dl><dt>${esc(t("nw.company"))}</dt><dd>${esc(c.company || "—")}</dd>
          ${c.contact_name ? `<dt>${esc(t("nw.contact"))}</dt><dd>${esc(c.contact_name)}</dd>` : ""}
          ${c.contact_email ? `<dt>Email</dt><dd><a href="mailto:${esc(c.contact_email)}">${esc(c.contact_email)}</a></dd>` : ""}
          ${placeOf(c) ? `<dt>${esc(t("nw.country"))}</dt><dd>${esc(placeOf(c))}</dd>` : ""}</dl></div>
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
    return `<section class="panel done"><div class="panel-h"><h2><span class="num">✓</span>${esc(t("u.title"))}</h2></div>
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
      <ol class="stepper three">${[1, 2, 3].map((n) => `<li class="${cls(n)}"><span class="dotn">${n < step ? "✓" : n}</span>${esc(t("step." + n))}</li>`).join("")}</ol>
      <div class="case-grid"><div>${panelUnderstand(c.analysis)}${officerPartners(c, step)}${officerPitch(c, step)}</div>${sidePanels(c)}</div>`;
    bindOfficerCase();
  }

  function matchRow(m, editable) {
    const who = [m.role, m.unit].filter(Boolean).map(esc).join(" · ");
    return `<div class="match ${m.selected ? "sel" : ""}">
      <input type="checkbox" data-sel="${esc(m.id)}" ${m.selected ? "checked" : ""} ${editable ? "" : "disabled"} aria-label="${esc(m.name)}">
      ${avatar(m.name, m.entity_type, true)}
      <div><h3>${esc(m.name)}</h3><div class="who">${who ? who + " · " : ""}${esc(m.institution)}</div>
        ${m.plain ? `<p class="plain">${jargon(m.plain.length > 240 ? m.plain.slice(0, 237) + "…" : m.plain)}</p>` : ""}
        <p class="why">${esc(m.why)}</p></div>
      <div class="right"><span class="type-badge ${esc(m.entity_type)}">${esc(m.archetype ? archLabel(m.archetype) : t("type." + m.entity_type))}</span>
        <a class="link-btn" href="${esc(safeUrl(m.url))}" target="_blank" rel="noopener">${ICON.ext}${esc(t("m.src"))}</a></div></div>`;
  }

  const archLabel = (id) => L((S.arch || []).find((a) => a.id === id)?.label) || t("type.person");
  function officerPartners(c, step) {
    const editable = c.status === "new";
    const nSel = c.matches.filter((m) => m.selected).length;
    const shown = editable ? c.matches : c.matches.filter((m) => m.selected);
    const order = (S.arch || []).map((a) => a.id);
    const groups = [...new Set(shown.map((m) => m.archetype))].sort((x, y) => order.indexOf(x) - order.indexOf(y));
    if (!groups.includes(S.atab?.[c.id])) S.atab = { ...(S.atab || {}), [c.id]: groups[0] };
    const cur = S.atab[c.id];
    const tabs = groups.map((g) => {
      const xs = shown.filter((m) => m.archetype === g), sel = xs.filter((m) => m.selected).length;
      return `<button type="button" role="tab" class="atab ${g === cur ? "on" : ""}" aria-selected="${g === cur}" data-atab="${esc(g)}">${esc(archLabel(g))}
        <span class="n">${xs.length}</span>${sel ? `<span class="s">${ICON.check}${sel}</span>` : ""}</button>`;
    }).join("");
    return `<section class="panel ${step === 2 ? "active" : step > 2 ? "done" : ""}">
      <div class="panel-h"><h2><span class="num">${step > 2 ? "✓" : 2}</span>${esc(t("m.title"))}</h2><span class="muted">${nSel} ${esc(t("m.sel"))}</span></div>
      ${editable ? `<p class="muted" style="margin:-4px 0 12px">${esc(t("m.lead"))}</p>
        <form class="match-tools" id="rematch"><input name="q" value="${esc(c.analysis.search_query)}" aria-label="${esc(t("m.again"))}">
          <button class="btn" type="submit">${esc(t("m.again"))}</button><button class="btn" type="button" id="moreSearch">${esc(t("m.more"))}</button></form>` : ""}
      ${shown.length ? `<div class="atabs" role="tablist">${tabs}</div>
        <div class="matches">${shown.filter((m) => m.archetype === cur).map((m) => matchRow(m, editable)).join("")}</div>`
        : `<div class="callout warn">${ICON.info}<span>${esc(c.no_match_message || t("m.none"))}</span></div>`}</section>`;
  }

  function nextSlots() {
    const out = [], d = new Date(), pad = (n) => String(n).padStart(2, "0");
    while (out.length < 3) { d.setDate(d.getDate() + 1); if (d.getDay() === 0 || d.getDay() === 6) continue;
      out.push(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${out.length % 2 ? "14" : "10"}:00`); }
    return out;
  }

  /** Step 4: Output 1 (plain, for her) + Output 2 (executive brief, for the CEO) + sending. */
  function pitchOutputs(c) {
    const b = c.outreach?.brief;
    if (!b) return "";
    const s = b.stats || {};
    return `<div class="pitch-grid">
      <div class="explain"><h3><span class="tag1">${esc(t("i.forYou"))}</span>${esc(t("i.forYouT"))}</h3>
        ${(b.explainer || []).map((sec) => `<section><h4>${esc(sec.title)}</h4>${sec.lines.map((l) => `<p>${jargon(l.text)}</p>${l.plain ? `<p class="mean">${esc(l.plain)}</p>` : ""}`).join("")}</section>`).join("")}</div>
      <div class="preview"><div class="pv-top"><small>${esc(t("i.forCeo"))} · ${esc(t("i.forCeoT"))}</small><h3>${esc(c.company)} × Bern</h3><p>${esc(b.data.hook)}</p></div>
        <div class="pv-body"><div class="stat-chips"><span><b>${b.data.items.length}</b> ${esc(t("i.teams"))}</span><span><b>${s.claims ?? "–"}</b> ${esc(t("i.stmt"))}</span>
          <span><b>${s.publications ?? 0}</b> ${esc(t("i.pubs"))}</span><span><b>${s.sources ?? b.data.sources.length}</b> ${esc(t("i.srcs"))}</span></div>
          <div class="actions"><a class="btn-primary btn-brand btn-sm" href="#/b/${esc(b.token)}" target="_blank" rel="noopener">${ICON.doc}${esc(t("i.open"))}</a>
            <a class="btn btn-sm" href="#/b/${esc(b.token)}?print=1" target="_blank" rel="noopener">${ICON.printer}${esc(t("i.pdf"))}</a>
            <button class="btn btn-sm" type="button" id="copyBrief">${ICON.link}${esc(t("i.copyLink"))}</button></div>
          <p class="muted" style="margin:0">${esc(t("bf.prepared", { d: fmtDate(b.at) }))} · ${esc(b.lang.toUpperCase())}</p></div></div></div>`;
  }

  function officerPitch(c, step) {
    if (step < 3) return `<section class="panel locked"><div class="panel-h"><h2><span class="num">3</span>${esc(t("i.title"))}</h2><span class="muted">${ICON.lock}</span></div>
      <p class="muted" style="margin:0">${esc(t("i.locked"))}</p></section>`;
    const done = ["contacted", "call_scheduled", "closed"].includes(c.status), b = c.outreach?.brief;
    const details = `<form class="details ${c.company ? "" : "need"}" id="detailsForm" ${c.company ? "hidden" : ""}>
        <div class="sub-h" style="margin-top:0">${esc(t("d.title"))}<span class="muted" style="font-weight:400">${esc(t("d.lead"))}</span></div>
        <div class="grid-form"><label class="field">${esc(t("nw.company"))}<input name="company" required maxlength="200" value="${esc(c.company)}"></label>
          <label class="field">${esc(t("nw.contact"))}<input name="contact_name" maxlength="200" value="${esc(c.contact_name)}"></label>
          <label class="field full">${esc(t("nw.email"))}<input name="contact_email" type="email" maxlength="200" value="${esc(c.contact_email)}"></label></div>
        <div class="actions" style="margin-top:10px"><button class="btn-primary" type="submit">${ICON.check}${esc(t("d.save"))}</button></div></form>
      ${c.company ? `<div class="details-line">${ICON.briefcase.replace("<svg", '<svg class="i"')}<b>${esc(c.company)}</b>${c.contact_name ? ` · ${esc(c.contact_name)}` : ""}${c.contact_email ? ` · ${esc(c.contact_email)}` : ""}
        <button class="link-btn" type="button" id="editDetails">${esc(t("d.edit"))}</button></div>` : ""}`;
    return `<section class="panel ${done ? "done" : "active"}"><div class="panel-h"><h2><span class="num">${done ? "✓" : 3}</span>${esc(t("i.title"))}</h2></div>
      <p class="muted" style="margin:-4px 0 12px">${esc(t("i.lead"))}</p>${details}
      ${c.outreach?.sent_at ? `<div class="callout ok" style="margin-bottom:12px">${ICON.check}<span>${esc(t("i.doneEmail", { d: fmtDate(c.outreach.sent_at) }))}</span></div>` : ""}
      ${c.outreach?.call ? `<div class="callout ok" style="margin-bottom:12px">${ICON.cal}<span>${esc(t("i.doneCall", { d: c.outreach.call }))}</span></div>` : ""}
      <div class="actions"><label class="field" style="min-width:180px">${esc(t("i.lang"))}<select class="input" id="pitchLang">${["en", "de", "fr"].map((l) => `<option value="${l}" ${l === (b?.lang || LANG) ? "selected" : ""}>${l.toUpperCase()}</option>`).join("")}</select></label>
        <button class="btn-primary btn-brand" id="prepBrief" type="button" style="align-self:flex-end" ${c.company ? "" : "disabled"}>${ICON.sparkle}${esc(t(b ? "i.regen" : "i.prep"))}</button></div>
      <div id="pitchBox">${pitchOutputs(c)}</div>
      ${b ? `<div class="sub-h">${ICON.mail}${esc(t("i.mail"))}</div>
        <div class="grid-form"><div class="field full">${esc(t("i.slots"))}<div class="slots">${nextSlots().map((s) => `<input type="datetime-local" class="slot" value="${s}" aria-label="${esc(t("i.slots"))}">`).join("")}</div></div>
          <label class="field">${esc(t("i.dur"))}<select class="input" id="callMin"><option>30</option><option>45</option><option>60</option></select></label></div>
        <div class="actions" style="margin-top:12px"><button class="btn-primary" id="prepMail" type="button">${ICON.mail}${esc(t("i.prepMail"))}</button>
          <button class="btn" id="dlIcs" type="button">${ICON.cal}${esc(t("i.ics"))}</button></div><div id="mailBox"></div>` : ""}
    </section>`;
  }

  function bindOfficerCase() {
    const c = CASE;
    const rerender = (keep = true) => { const y = window.scrollY; renderOfficerCase(); if (keep) window.scrollTo(0, y); };
    $$("[data-atab]").forEach((b) => b.addEventListener("click", () => { S.atab[c.id] = b.dataset.atab; rerender(); }));
    $("#delCase")?.addEventListener("click", async () => { if (!confirm(t("cs.confirmDelete"))) return; await api(`/cases/${c.id}`, { method: "DELETE" }); go("#/staff/requests"); });
    let timer;
    $$("[data-sel]").forEach((cb) => cb.addEventListener("change", () => {
      c.matches.find((x) => x.id === cb.dataset.sel).selected = cb.checked;
      cb.closest(".match").classList.toggle("sel", cb.checked);
      clearTimeout(timer);
      timer = setTimeout(async () => {
        try { CASE = await api(`/cases/${c.id}/selection`, { method: "POST", body: asStaff({ selected: c.matches.filter((x) => x.selected).map((x) => x.id) }) }); rerender(); }
        catch (e) { toast(e.message); }
      }, 250);
    }));
    $("#rematch")?.addEventListener("submit", async (ev) => {
      ev.preventDefault(); const q = ev.target.q.value.trim(); if (q.length < 2) return;
      ev.target.querySelector("button").disabled = true;
      CASE = await api(`/cases/${c.id}/rematch`, { method: "POST", body: asStaff({ query: q }) }); rerender();
    });
    $("#moreSearch")?.addEventListener("click", () => {
      S.ctx = { id: c.id, company: c.company }; store.set("nav-ctx", S.ctx);
      go(`#/staff/search?q=${encodeURIComponent(c.analysis.search_query)}`);
    });
    $("#editDetails")?.addEventListener("click", () => { $("#detailsForm").hidden = false; $("#detailsForm").company.focus(); });
    $("#detailsForm")?.addEventListener("submit", async (ev) => {
      ev.preventDefault(); const f = ev.target;
      try { CASE = await api(`/cases/${c.id}/details`, { method: "POST", body: asStaff({ company: f.company.value.trim(), contact_name: f.contact_name.value.trim(), contact_email: f.contact_email.value.trim() }) }); rerender(); }
      catch (e) { toast(e.message); }
    });
    $("#prepBrief")?.addEventListener("click", async (ev) => {
      ev.currentTarget.disabled = true;
      $("#pitchBox").innerHTML = spinner();
      try {
        await api(`/cases/${c.id}/brief`, { method: "POST", body: asStaff({ lang: $("#pitchLang").value, email: staff.email || "", team: staff.team || "" }) });
        CASE = await api(`/cases/${c.id}`); rerender();
      } catch (e) { toast(e.message); rerender(); }
    });
    $("#copyBrief")?.addEventListener("click", () => { navigator.clipboard?.writeText(briefUrl(c.outreach.brief.token)); toast(t("i.copied")); });
    const slotLabels = () => $$(".slot").map((i) => i.value).filter(Boolean).map((v) => fmtDate(v, true, c.outreach?.brief?.lang || LANG));
    $("#prepMail")?.addEventListener("click", async () => {
      const lang = c.outreach.brief.lang;
      const d = await api(`/cases/${c.id}/draft`, { method: "POST", body: asStaff({ lang, slots: slotLabels(), sender: staff.name, team: staff.team || "", link: briefUrl(c.outreach.brief.token) }) });
      $("#mailBox").innerHTML = `<div class="email-box"><label class="field">${esc(t("i.subj"))}<input id="mSubj" value="${esc(d.subject)}"></label>
        <label class="field">${esc(t("i.body"))}<textarea id="mBody">${esc(d.body)}</textarea></label>
        <div class="actions"><a class="btn-primary" id="mOpen" href="#">${ICON.mail}${esc(t("i.openMail"))}</a>
          <button class="btn" id="mCopy" type="button">${ICON.copy}${esc(t("i.copy"))}</button><button class="btn" id="mSent" type="button">${ICON.check}${esc(t("i.sent"))}</button></div></div>`;
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
  async function viewBrief(token, params) {
    view().innerHTML = spinner();
    let b;
    try { b = await api(`/briefs/${encodeURIComponent(token)}`); }
    catch { view().innerHTML = `<div class="panel empty"><h3>${esc(t("bf.missing"))}</h3></div>`; return; }
    const lb = b.labels, sup = (n) => `<sup class="ref"><a href="#src-${n}" data-ref="${n}">[${n}]</a></sup>`;
    document.title = `${b.company} × Bern`;
    const nClaims = b.items.reduce((n, i) => n + (i.quote ? 1 : 0) + i.technical.length, 0) + b.proof.length;
    const nPubs = b.items.reduce((n, i) => n + i.publications.length, 0);
    view().innerHTML = `<article class="brief" lang="${esc(b.lang)}">
      <header class="b-hero"><div class="kick">${esc(b.kicker)}</div>
        <h1>${esc(b.company)} <span>×</span> Bern</h1><p>${esc(b.hook)}</p>
        <div class="stat-chips"><span><b>${b.items.length}</b> ${esc(lb.teams)}</span><span>${ICON.check}<b>${nClaims}</b> ${esc(lb.stmt)}</span>${nPubs ? `<span><b>${nPubs}</b> ${esc(lb.pubs_n)} (DOI)</span>` : ""}</div></header>

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
        <div class="cta-box">${b.contact.email ? `<a class="btn-primary" href="mailto:${esc(b.contact.email)}?subject=${encodeURIComponent(`${b.company} — Bern`)}">${ICON.cal}${esc(lb.cta)}</a>` : ""}
          <button class="btn" type="button" id="bPrint">${ICON.printer}${esc(lb.pdf)}</button>
          <small>${esc(b.from)}${b.contact.email ? ` · ${esc(b.contact.email)}` : ""}</small></div></div></section>

      <div class="honest">${ICON.shield}<span>${esc(b.honest)}</span></div>
      <section class="b-sources"><h2 style="font-size:15px;margin:0">${esc(lb.sources)}</h2><ol>${b.sources.map((s, i) =>
        `<li id="src-${i + 1}"><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.kind === "doi" ? s.label : hostPath(s.url))}</a>${s.kind === "doi" ? ` <span class="muted">${esc(s.url)}</span>` : ""}</li>`).join("")}</ol></section>
    </article>`;
    $$(".tech-btn").forEach((btn) => btn.addEventListener("click", () => {
      const box = $("#" + btn.getAttribute("aria-controls")), open = !box.classList.contains("open");
      box.classList.toggle("open", open); btn.setAttribute("aria-expanded", open);
    }));
    $$("sup.ref a").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); const el = $("#src-" + a.dataset.ref); el?.scrollIntoView({ behavior: "smooth", block: "center" }); el?.animate?.([{ background: "var(--mark)" }, { background: "transparent" }], { duration: 1600 }); }));
    $("#bPrint").addEventListener("click", () => window.print());
    if (params.get("print") === "1") setTimeout(() => window.print(), 400);
  }

  /* ======================= boot ======================= */
  function boot() {
    const theme = store.get("nav-theme", null);
    if (theme) document.documentElement.dataset.theme = theme;
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
