/* Private knowledge workspace. Visibility is driven by a verified server session. */
window.KnowledgeWorkspace = (() => {
  const copy = {
    en: { title: 'Knowledge Base', lead: 'Enrich the platform with company sources, documents and notes.', add: 'Add company', name: 'Company name', links: 'Websites and social links', docs: 'Documents', notes: 'Notes', match: 'Find opportunities and partners in the background', save: 'Save and process', remove: 'Delete company', confirm: 'Delete this company and its knowledge sources?', empty: 'Add your first company to enrich the platform.', profile: 'Overview', sources: 'Sources', matches: 'Suggested partners', uploading: 'Reading documents…', cancel: 'Cancel', queued: 'Queued', processing: 'Processing sources', matching: 'Finding partners', ready: 'Ready', partial: 'Ready with warnings', error: 'Processing failed', retry: 'Edit / retry', noMatches: 'No partner suggestions available.', saved: 'Saved. Processing continues in the background.', docHint: 'Original files and extracted content are retained in private storage.', search: 'Find a company', loading: 'Loading…' },
    de: { title: 'Wissensbasis', lead: 'Die Plattform mit Firmenquellen, Dokumenten und Notizen ergänzen.', add: 'Firma hinzufügen', name: 'Firmenname', links: 'Websites und Social-Media-Links', docs: 'Dokumente', notes: 'Notizen', match: 'Chancen und Partner im Hintergrund suchen', save: 'Speichern und verarbeiten', remove: 'Firma löschen', confirm: 'Diese Firma und ihre Wissensquellen löschen?', empty: 'Fügen Sie die erste Firma hinzu.', profile: 'Übersicht', sources: 'Quellen', matches: 'Partnervorschläge', uploading: 'Dokumente werden gelesen…', cancel: 'Abbrechen', queued: 'In Warteschlange', processing: 'Quellen werden verarbeitet', matching: 'Partnersuche', ready: 'Bereit', partial: 'Bereit mit Hinweisen', error: 'Verarbeitung fehlgeschlagen', retry: 'Bearbeiten / erneut versuchen', noMatches: 'Keine Partnervorschläge verfügbar.', saved: 'Gespeichert. Die Verarbeitung läuft im Hintergrund.', docHint: 'Originaldateien und extrahierte Inhalte bleiben im privaten Speicher.', search: 'Firma suchen', loading: 'Wird geladen…' },
    fr: { title: 'Base de connaissances', lead: 'Enrichir la plateforme avec des sources, documents et notes.', add: 'Ajouter une entreprise', name: 'Nom de l’entreprise', links: 'Sites web et réseaux sociaux', docs: 'Documents', notes: 'Notes', match: 'Rechercher des opportunités et partenaires en arrière-plan', save: 'Enregistrer et traiter', remove: 'Supprimer l’entreprise', confirm: 'Supprimer cette entreprise et ses sources ?', empty: 'Ajoutez votre première entreprise.', profile: 'Vue d’ensemble', sources: 'Sources', matches: 'Partenaires suggérés', uploading: 'Lecture des documents…', cancel: 'Annuler', queued: 'En attente', processing: 'Traitement des sources', matching: 'Recherche de partenaires', ready: 'Prêt', partial: 'Prêt avec avertissements', error: 'Échec du traitement', retry: 'Modifier / réessayer', noMatches: 'Aucune suggestion disponible.', saved: 'Enregistré. Le traitement continue en arrière-plan.', docHint: 'Les originaux et le contenu extrait restent dans le stockage privé.', search: 'Rechercher une entreprise', loading: 'Chargement…' },
  };
  let cleanup = () => {};
  async function mount({ api, lang, esc, accept, toast, selectedId = null, candidateId = null }) {
    cleanup();
    const root = document.querySelector('#view'), t = copy[lang] || copy.en;
    let active = true, timer, entries = [], selected = selectedId, editing = false, query = '';
    cleanup = () => { active = false; clearTimeout(timer); };
    const $ = (s) => root.querySelector(s);
    const safe = (url) => /^https?:\/\//i.test(url || '') ? esc(url) : '#';
    const fetchEntries = async () => {
      clearTimeout(timer);
      const result = await api('/kb/companies');
      if (!active) return;
      entries = result;
      if (!editing) draw();
      if (entries.some((e) => ['queued', 'processing', 'matching'].includes(e.status))) timer = setTimeout(() => fetchEntries().catch((e) => toast(e.message)), 3000);
    };
    function draw() {
      if (!active) return;
      root.innerHTML = `<div class="page-h"><div><h1>${esc(t.title)}</h1><p>${esc(t.lead)}</p></div><button class="btn-primary" id="kbAdd">+ ${esc(t.add)}</button></div>
        <div class="kb-layout"><aside class="panel kb-tree"><label class="field">${esc(t.search)}<input type="search" id="kbFilter" value="${esc(query)}"></label><div id="kbTree"></div></aside><section class="panel" id="kbDetail"></section></div>`;
      $('#kbAdd').onclick = () => edit();
      $('#kbFilter').oninput = (event) => { query = event.target.value; tree(); };
      tree(); detail();
    }
    function tree() {
      $('#kbTree').innerHTML = entries.filter((e) => e.name.toLowerCase().includes(query.toLowerCase())).map((e) => `<details ${selected === e.id ? 'open' : ''}><summary>${esc(e.name)} <span class="tag">${esc(t[e.status])}</span></summary>${['profile', 'sources', 'docs', 'notes'].map((section) => `<button type="button" class="link-btn" data-entry="${esc(e.id)}" data-section="${section}">${esc(t[section])}</button>`).join('')}</details>`).join('');
      root.querySelectorAll('[data-entry]').forEach((b) => b.onclick = () => { editing = false; selected = b.dataset.entry; detail(); $('#kb-' + b.dataset.section)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); });
    }
    function detail() {
      const e = entries.find((e) => e.id === selected);
      if (!e) { $('#kbDetail').innerHTML = `<div class="empty">${esc(t.empty)}<p><button class="btn-primary" id="kbFirst">+ ${esc(t.add)}</button></p></div>`; $('#kbFirst').onclick = () => edit(); return; }
      $('#kbDetail').innerHTML = `<div class="panel-h"><h2>${esc(e.name)}</h2><span class="tag" role="status">${esc(t[e.status])}</span></div><div class="actions"><button class="btn" id="kbEdit">${esc(t.retry)}</button><button class="link-btn" id="kbDelete">${esc(t.remove)}</button></div>
        ${(e.errors || []).map((err) => `<p class="callout warn">${esc(err.url || '')} ${esc(err.message)}</p>`).join('')}
        <section id="kb-profile"><h3>${esc(t.profile)}</h3><p>${esc(e.profile?.summary || t[e.status])}</p>${(e.profile?.keywords || []).map((k) => `<span class="tag">${esc(k)}</span>`).join(' ')}</section>
        <section id="kb-sources"><h3>${esc(t.sources)}</h3><ul>${e.links.map((u) => `<li><a href="${safe(u)}" target="_blank" rel="noopener">${esc(u)}</a></li>`).join('')}</ul></section>
        <section id="kb-docs"><h3>${esc(t.docs)}</h3>${e.documents.map((d) => `<details><summary>${esc(d.name)}</summary>${d.original_id ? `<a href="/kb/originals/${esc(d.original_id)}" target="_blank" rel="noopener">${esc(d.name)} ↓</a>` : ''}<p class="orig-text">${esc(d.text)}</p></details>`).join('')}</section>
        <section id="kb-notes"><h3>${esc(t.notes)}</h3><p class="kb-notes">${esc(e.notes || '—')}</p></section>`;
      $('#kbEdit').onclick = () => edit(e);
      $('#kbDelete').onclick = async () => { if (!confirm(t.confirm)) return; try { await api('/kb/companies/' + e.id, { method: 'DELETE' }); selected = null; await fetchEntries(); } catch (err) { toast(err.message); } };
    }
    function edit(e = {}) {
      editing = true;
      const docs = [...(e.documents || [])];
      const cantonLabel = lang === 'fr' ? 'Canton' : lang === 'de' ? 'Kanton' : 'Canton';
      const sectorNames = { en: ['Sector', 'Not classified', 'Tech', 'Medical', 'Manufacturing', 'Consulting', 'Energy', 'Other', 'Topics / strengths (comma-separated)'], de: ['Branche', 'Nicht klassifiziert', 'Technologie', 'Medizin', 'Fertigung', 'Beratung', 'Energie', 'Andere', 'Themen / Stärken (durch Kommas getrennt)'], fr: ['Secteur', 'Non classé', 'Technologie', 'Médical', 'Industrie', 'Conseil', 'Énergie', 'Autre', 'Thèmes / points forts (séparés par des virgules)'] }[lang] || ['Sector', 'Not classified', 'Tech', 'Medical', 'Manufacturing', 'Consulting', 'Energy', 'Other', 'Topics / strengths'];
      const cantons = ['Aargau', 'Appenzell Ausserrhoden', 'Appenzell Innerrhoden', 'Basel-Landschaft', 'Basel-Stadt', 'Bern', 'Fribourg', 'Geneva', 'Glarus', 'Graubünden', 'Jura', 'Lucerne', 'Neuchâtel', 'Nidwalden', 'Obwalden', 'Schaffhausen', 'Schwyz', 'Solothurn', 'St. Gallen', 'Thurgau', 'Ticino', 'Uri', 'Valais', 'Vaud', 'Zug', 'Zurich'];
      $('#kbDetail').innerHTML = `<h2>${esc(e.name || t.add)}</h2><form id="kbForm" class="kb-form"><label class="field">${esc(t.name)}<input name="name" required maxlength="200" value="${esc(e.name || '')}"></label><label class="field">${cantonLabel}<select name="canton" class="input" required><option value="">—</option>${cantons.map((c) => `<option value="${esc(c)}" ${e.canton === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label><fieldset><legend>${esc(t.links)}</legend><div id="kbLinks"></div></fieldset>
        <div class="grid-form"><label class="field">${esc(sectorNames[0])}<select class="input" name="sector">${['', 'tech', 'medical', 'manufacturing', 'consulting', 'energy', 'other'].map((s, i) => `<option value="${s}" ${e.sector === s ? 'selected' : ''}>${esc(sectorNames[i + 1])}</option>`).join('')}</select></label><label class="field">${esc(sectorNames[8])}<input name="topics" maxlength="2000" value="${esc((e.topics || []).join(', '))}"></label></div>
        <label class="field">${esc(t.docs)}<input type="file" id="kbFiles" accept="${esc(accept)}" multiple><small>${esc(t.docHint)}</small></label><ul id="kbDocs" class="docs"></ul><label class="field">${esc(t.notes)}<textarea name="notes" maxlength="12000">${esc(e.notes || '')}</textarea></label><p id="kbMessage" role="status"></p><div class="actions"><button type="submit" class="btn-primary" id="kbSave">${esc(t.save)}</button><button type="button" class="btn" id="kbCancel">${esc(t.cancel)}</button></div></form>`;
      function addLink(value = '') {
        const label = document.createElement('label'); label.className = 'field';
        const n = $('#kbLinks').children.length + 1;
        label.append(`${t.links} ${n}`);
        const input = document.createElement('input'); input.type = 'url'; input.value = value; input.placeholder = 'https://'; input.maxLength = 1000;
        input.oninput = () => { if (input === $('#kbLinks').lastElementChild.querySelector('input') && input.value.trim() && n < 12) addLink(); };
        label.append(input); $('#kbLinks').append(label);
      }
      (e.links || []).forEach(addLink); if ((e.links || []).length < 12) addLink();
      function drawDocs() { $('#kbDocs').innerHTML = docs.map((d, i) => `<li>${esc(d.name)}<button type="button" class="link-btn" data-doc="${i}" aria-label="${esc(t.remove)}: ${esc(d.name)}">×</button></li>`).join(''); root.querySelectorAll('[data-doc]').forEach((b) => b.onclick = () => { docs.splice(+b.dataset.doc, 1); drawDocs(); }); }
      drawDocs();
      $('#kbFiles').onchange = async (event) => {
        const files = [...event.target.files]; $('#kbSave').disabled = true; $('#kbFiles').disabled = true; $('#kbMessage').textContent = t.uploading;
        try {
          for (const file of files) {
            if (docs.length >= 20 || file.size > 25000000) throw new Error('Maximum 20 documents, 25 MB each.');
            const response = await fetch('/kb/documents?name=' + encodeURIComponent(file.name), { method: 'POST', body: file });
            if (!active || !editing || !$('#kbMessage')) return;
            const body = await response.json(); if (!response.ok) throw new Error(body.detail || 'Upload failed'); docs.push(body); drawDocs();
          }
          if (active && $('#kbMessage')) $('#kbMessage').textContent = '';
        } catch (err) { if (active && $('#kbMessage')) $('#kbMessage').textContent = err.message; }
        finally { if (active && $('#kbSave')) { $('#kbSave').disabled = false; $('#kbFiles').disabled = false; $('#kbFiles').value = ''; } }
      };
      $('#kbCancel').onclick = () => { editing = false; draw(); };
      $('#kbForm').onsubmit = async (event) => {
        event.preventDefault(); const form = event.target; $('#kbSave').disabled = true;
        try {
          const entry = await api('/kb/companies' + (e.id ? '/' + e.id : ''), { method: e.id ? 'PUT' : 'POST', body: { discovery_candidate_id: e.discovery_candidate_id || null, name: form.elements.namedItem('name').value, canton: form.elements.namedItem('canton').value, sector: form.elements.namedItem('sector').value, topics: form.elements.namedItem('topics').value.split(',').map((v) => v.trim()).filter(Boolean), notes: form.elements.namedItem('notes').value, links: [...root.querySelectorAll('#kbLinks input')].map((i) => i.value.trim()).filter(Boolean), documents: docs, lang } });
          selected = entry.id; editing = false; toast(t.saved); await fetchEntries();
        } catch (err) { if (active && $('#kbMessage')) { $('#kbMessage').textContent = err.message; $('#kbSave').disabled = false; } }
      };
      $('#kbForm input').focus();
    }
    root.innerHTML = `<p role="status">${esc(t.loading)}</p>`;
    try { await fetchEntries(); if (active && candidateId) edit(await api('/discovery/candidates/' + encodeURIComponent(candidateId) + '/export')); } catch (e) { if (active) root.textContent = e.message; }
  }
  return { mount, unmount: () => cleanup(), title: (lang) => (copy[lang] || copy.en).title };
})();
