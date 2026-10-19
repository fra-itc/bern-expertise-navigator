/* Source-backed ecosystem visual. No network calls or dependencies. */
(function () {
  'use strict';
  const copy = {
    en: { title: 'Your next step, connected to Bern', map: 'Explore your complementary ecosystem', skip: 'Read the pitch now', support: 'Complementary expertise', empty: 'Select source-backed partners to build this map.', more: 'More partners in the pitch', bern: 'Bern ecosystem' },
    de: { title: 'Ihr nächster Schritt, verbunden mit Bern', map: 'Ihr ergänzendes Ökosystem entdecken', skip: 'Pitch jetzt lesen', support: 'Ergänzende Kompetenzen', empty: 'Wählen Sie quellenbelegte Partner für diese Karte.', more: 'Weitere Partner im Pitch', bern: 'Ökosystem Bern' },
    fr: { title: 'Votre prochaine étape, connectée à Berne', map: 'Explorer votre écosystème complémentaire', skip: 'Lire le pitch maintenant', support: 'Expertises complémentaires', empty: 'Sélectionnez des partenaires documentés pour cette carte.', more: 'Autres partenaires dans le pitch', bern: 'Écosystème bernois' }
  };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function url(value) { try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } }
  function normalize(data) {
    const brief = data.brief || data.data || data;
    const featured = brief.ecosystem?.nodes?.map(node => node.id);
    const items = (brief.items || []).filter(item => (!featured?.length || featured.includes(item.id)) && (url(item.page) || url(brief.sources?.[item.page_ref - 1]?.url)));
    if (featured?.length) items.sort((a, b) => featured.indexOf(a.id) - featured.indexOf(b.id));
    return { ...brief, items };
  }
  function mapMarkup(b, t) {
    const items = b.items.slice(0, 6), n = items.length;
    return `<div class="pv-system" style="--pv-count:${n}"><svg class="pv-connections" viewBox="0 0 1000 480" preserveAspectRatio="none" aria-hidden="true"><ellipse cx="500" cy="240" rx="355" ry="180"/>${items.map((_, i) => { const a = (i / n * Math.PI * 2) - Math.PI / 2; return `<path style="--pv-i:${i}" d="M500 240 L${500 + Math.cos(a) * 355} ${240 + Math.sin(a) * 180}"/>`; }).join('')}</svg>
      <div class="pv-center">${/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(b.branding?.company_logo || '') ? `<img class="pv-client-logo" src="${esc(b.branding.company_logo)}" alt="">` : '<span class="pv-center-mark" aria-hidden="true">✦</span>'}<strong>${esc(b.company)}</strong><small>${esc(t.bern)}</small></div>
      ${items.map((item, i) => { const a = (i / n * Math.PI * 2) - Math.PI / 2, href = url(item.page) || url(b.sources[item.page_ref - 1].url); return `<a class="pv-node" style="--pv-i:${i};--pv-x:${50 + Math.cos(a) * 35.5}%;--pv-y:${50 + Math.sin(a) * 37.5}%" href="${esc(href)}" target="_blank" rel="noopener noreferrer"><span class="pv-node-dot" aria-hidden="true"></span><strong>${esc(item.name)}</strong><span>${esc(item.topics?.[0]?.term || item.institution || t.support)}</span></a>`; }).join('')}</div>${b.items.length > 6 ? `<p class="pv-more">+${b.items.length - 6} · ${esc(t.more)}</p>` : ''}`;
  }
  function mount(container, data, options = {}) {
    if (!container) return null;
    container.querySelector(':scope > .pitch-visual')?.remove();
    const b = normalize(data), t = copy[b.lang] || copy.en, compact = !!options.compact;
    const root = document.createElement('section'); root.className = 'pitch-visual' + (compact ? ' pv-compact' : ''); root.lang = b.lang || 'en';
    // Only a supplied hex colour is accepted; logo URLs are intentionally not fetched here.
    const accent = b.branding?.primary_color;
    if (/^#[\da-f]{6}$/i.test(accent || '')) root.style.setProperty('--pv-accent', accent);
    root.innerHTML = compact ? `<h3>${esc(t.support)}</h3>${b.items.length ? mapMarkup(b, t) : `<p>${esc(t.empty)}</p>`}` : `<details open><summary>${esc(t.map)}</summary><div class="pv-stage"><div class="pv-heading"><div><small>${esc(b.kicker || t.bern)}</small><h2>${esc(t.title)}</h2></div><button type="button" class="pv-skip">${esc(t.skip)} <span aria-hidden="true">↓</span></button></div>${b.items.length ? mapMarkup(b, t) : `<p>${esc(t.empty)}</p>`}</div></details>`;
    if (options.prepend === false) container.append(root); else container.prepend(root);
    let timer;
    if (!compact) {
      const details = root.querySelector('details'), skip = root.querySelector('button');
      const finish = () => { clearTimeout(timer); root.classList.remove('pv-intro'); details.open = false; };
      skip.addEventListener('click', finish);
      details.addEventListener('toggle', () => { if (!details.open) { clearTimeout(timer); root.classList.remove('pv-intro'); } });
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && b.items.length && !options.skipIntro) {
        root.classList.add('pv-intro'); timer = setTimeout(() => { if (root.isConnected) finish(); }, 4500);
      } else details.open = !!options.skipIntro;
      // Navigation removes the root; the bounded timer holds no persistent listeners.
    }
    return root;
  }
  window.PitchVisual = Object.freeze({ mount });
})();
