// Optional UI checks: install jsdom@26 outside the repo and set NODE_PATH to its node_modules.
// Run: node --test src/tests/ui-workspace.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { JSDOM } = require('jsdom');
const source = readFileSync(require('node:path').join(__dirname, '../app/navigator/static/app.js'), 'utf8');
const requests = [
  { id: 'a', company: 'Alpha <Sensors>', summary: 'Glucose monitoring', country: 'Germany', status: 'new', updated_at: '2026-10-18', has_brief: false },
  { id: 'b', company: 'Beta AG', summary: 'Cardiac devices', city: 'Bern', country: 'Switzerland', status: 'new', updated_at: '2026-10-18', has_brief: true },
];
async function until(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail('UI did not reach the expected state');
}
function app(t, { lang = 'en', hash = '/staff/requests', fetcher } = {}) {
  const dom = new JSDOM('<a class="skip" href="#view"></a><header id="topbar"></header><main id="view"></main><footer id="foot"></footer><div id="toast"></div>', {
    url: `https://navigator.test/#${hash}`, runScripts: 'outside-only',
  });
  t.after(() => dom.window.close());
  const w = dom.window;
  w.localStorage.setItem('nav-staff', JSON.stringify({ name: 'Demo officer', email: '', team: '' }));
  w.localStorage.setItem('nav-lang', JSON.stringify(lang));
  w.matchMedia = () => ({ matches: false });
  w.scrollTo = () => {};
  w.fetch = async (url, options) => {
    const result = fetcher ? await fetcher(url, options) : undefined;
    if (result !== undefined) return result;
    return { ok: true, json: async () => url === '/cases' ? requests : [] };
  };
  w.eval(readFileSync(require('node:path').join(__dirname, '../app/navigator/static/knowledge.js'), 'utf8'));
  w.eval(readFileSync(require('node:path').join(__dirname, '../app/navigator/static/analytics.js'), 'utf8'));
  w.eval(readFileSync(require('node:path').join(__dirname, '../app/navigator/static/technical-guide.js'), 'utf8'));
  w.eval(readFileSync(require('node:path').join(__dirname, '../app/navigator/static/guide.js'), 'utf8'));
  w.eval(readFileSync(require('node:path').join(__dirname, '../app/navigator/static/pitch-visual.js'), 'utf8'));
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new w.Event('close')); };
  w.eval(readFileSync(require('node:path').join(__dirname, '../app/navigator/static/discovery.js'), 'utf8'));
  w.eval(source);
  return w;
}
test('lead search filters by company, need and location; clearing restores cards', async (t) => {
  const w = app(t), d = w.document;
  await until(() => d.querySelector('#requestFilter'));
  const input = d.querySelector('#requestFilter');
  const search = (q) => { input.value = q; input.dispatchEvent(new w.Event('input')); };
  assert.equal(d.querySelectorAll('.case-card').length, 2);
  for (const q of ['ALPHA', ' glucose ', 'Germany', 'Bern']) {
    search(q);
    assert.equal(d.querySelectorAll('.case-card').length, 1, q);
    assert.equal(d.querySelector('#requestCount').textContent, '1 of 2 requests');
  }
  search('unknown');
  assert.equal(d.querySelectorAll('.case-card').length, 0);
  assert.match(d.querySelector('#requestBoard').textContent, /Try another search/);
  search('');
  assert.equal(d.querySelectorAll('.case-card').length, 2);
  assert.equal(d.querySelector('.case-card h3').textContent, 'Alpha <Sensors>');
  assert.equal(d.querySelector('.case-card h3').children.length, 0);
});

test('Knowledge Base follows Search only for server-approved canton sessions', async (t) => {
  const w = app(t, { fetcher: async (url) => url === '/staff/session' ? { ok: true, json: async () => ({ can_manage_knowledge: true }) } : undefined });
  await until(() => w.document.querySelector('.kb-nav'));
  const nav = w.document.querySelector('.kb-nav');
  assert.equal(nav.previousElementSibling.getAttribute('href'), '#/staff/dashboard');
  assert.equal(nav.querySelector('strong').textContent, 'Knowledge Base');
});
test('private workspace adds link inputs progressively and saves company knowledge', async (t) => {
  let saved;
  const w = app(t, { hash: '/staff/knowledge', fetcher: async (url, opts) => {
    if (url === '/staff/session') return { ok: true, json: async () => ({ can_manage_knowledge: true }) };
    if (url === '/kb/companies') {
      if (opts?.method === 'POST') saved = JSON.parse(opts.body);
      return { ok: true, json: async () => opts?.method === 'POST' ? { id: 'saved' } : [] };
    }
  } });
  const d = w.document;
  await until(() => d.querySelector('#kbAdd'));
  d.querySelector('#kbAdd').click();
  assert.equal(d.querySelectorAll('#kbLinks input').length, 1);
  d.querySelector('#kbForm input[name="name"]').value = 'Test company';
  const input = d.querySelector('#kbLinks input');
  input.value = 'https://example.org'; input.dispatchEvent(new w.Event('input'));
  assert.equal(d.querySelectorAll('#kbLinks input').length, 2);
  d.querySelector('#kbForm textarea').value = 'Glucose sensor research';
  assert.equal(d.querySelector('#kbForm input[name="match"]'), null);
  d.querySelector('#kbForm select[name="canton"]').value = 'Bern';
  d.querySelector('#kbForm').dispatchEvent(new w.Event('submit', { cancelable: true }));
  await until(() => saved);
  assert.deepEqual(saved.links, ['https://example.org']);
  assert.equal(saved.name, 'Test company');
  assert.equal(saved.canton, 'Bern');
  assert.equal(saved.match, undefined);
});
test('manual team information does not reveal the private navigation or route', async (t) => {
  const w = app(t, { hash: '/staff/knowledge' });
  await until(() => w.document.querySelector('a[href="#/staff/access"]'));
  assert.equal(w.document.querySelector('.kb-nav'), null);
  assert.equal(w.document.querySelector('#kbAdd'), null);
});

test('lead creation offers Bern or northern scope and submits the selected scope', async (t) => {
  let submitted;
  const w = app(t, { hash: '/staff/new', fetcher: async (url, opts) => {
    if (url === '/companies/suggest') return { ok: true, json: async () => ({ candidates: [], message: '' }) };
    if (url === '/cases' && opts?.method === 'POST') {
      submitted = JSON.parse(opts.body);
      return { ok: false, status: 503, json: async () => ({ detail: 'Test save unavailable' }) };
    }
  } });
  const d = w.document;
  await until(() => d.querySelector('#matchScope'));
  const scope = d.querySelector('#matchScope');
  assert.equal(scope.value, 'bern');
  assert.deepEqual([...scope.options].map((o) => o.value), ['bern', 'north']);
  scope.value = 'north';
  d.querySelector('#bsQ').value = 'glucose sensor lead';
  d.querySelector('#broadForm').dispatchEvent(new w.Event('submit', { cancelable: true }));
  await until(() => d.querySelector('#sgNone'));   // no company suggested: continue without one
  d.querySelector('#sgNone').click();
  await until(() => submitted);
  assert.equal(submitted.match_scope, 'north');
  await until(() => d.querySelector('#matchScope'));
  assert.equal(d.querySelector('#matchScope').value, 'north');
});

for (const [lang, title] of [['en', 'Discover the platform'], ['de', 'Plattform entdecken'], ['fr', 'Découvrir la plateforme']]) {
  test(`help guide follows the selected ${lang} language and supports steps and close`, async (t) => {
    const w = app(t, { lang }), d = w.document;
    await until(() => d.querySelector('#requestFilter'));
    d.querySelector('#helpBtn').click();
    assert.equal(d.querySelector('#guideTitle').textContent, title);
    assert.equal(d.querySelector('#guideCount').textContent, '01 / 7');
    assert.equal(d.querySelector('#guideBack').disabled, true);
    d.querySelector('#guideNext').click();
    assert.equal(d.querySelector('#guideCount').textContent, '02 / 7');
    d.querySelector('#guideBack').click();
    assert.equal(d.querySelector('#guideCount').textContent, '01 / 7');
    d.querySelector('#guideClose').click();
    assert.equal(d.querySelector('#platformGuide'), null);
  });
}

test('analytics renders source metrics, sector filters and pitch actions', async (t) => {
  const data = { counts: {knowledge_companies: 1, lead_companies: 0, contacted: 0, opportunities: 0, collaboration: 0, established: 0}, sectors: {tech: 1}, topics: {sensors: 1}, suggested_topics: {}, leads: [], companies: [{id: 'x', name: 'Sensors AG', canton: 'Bern', sector: 'tech', topics: ['sensors'], summary: 'Sensor research', source_count: 2}] };
  const w = app(t, { hash: '/staff/analytics', fetcher: async (url) => {
    if (url === '/staff/session') return { ok: true, json: async () => ({can_manage_knowledge: true}) };
    if (url === '/kb/analytics') return { ok: true, json: async () => data };
  } }), d = w.document;
  await until(() => d.querySelector('#analyticsDirectory'));
  assert.equal(d.querySelectorAll('.analytics-kpis .kpi').length, 6);
  assert.match(d.querySelector('#analyticsDirectory').textContent, /Sensors AG/);
  d.querySelector('[data-sector="tech"]').click();
  assert.equal(d.querySelector('[data-sector="tech"]').getAttribute('aria-pressed'), 'true');
  d.querySelector('#analyticsQuery').value = 'other';
  d.querySelector('#analyticsQuery').dispatchEvent(new w.Event('input'));
  assert.equal(d.querySelector('#analyticsDirectory tbody'), null);
});

test('ecosystem map uses curated sourced partners, client branding and can skip animation', async (t) => {
  const w = app(t), d = w.document;
  await until(() => d.querySelector('#requestFilter'));
  const container = d.createElement('div'); d.body.append(container);
  const visual = w.PitchVisual.mount(container, { company: 'Client <AG>', lang: 'en', branding: {primary_color: '#123456'}, ecosystem: {nodes: [{id: 'good'}]}, items: [
    {id: 'good', name: 'Complementary lab', page: 'https://example.org/lab', topics: [{term: 'Sensors'}]},
    {id: 'excluded', name: 'Not featured', page: 'https://example.org/other'},
    {id: 'bad', name: 'Unsafe', page: 'javascript:alert(1)'},
  ] });
  assert.equal(visual.querySelectorAll('.pv-node').length, 1);
  assert.equal(visual.style.getPropertyValue('--pv-accent'), '#123456');
  assert.equal(visual.querySelector('.pv-center strong').textContent, 'Client <AG>');
  assert.equal(visual.querySelector('details').open, true);
  visual.querySelector('.pv-skip').click();
  assert.equal(visual.querySelector('details').open, false);
});
for (const [lang, label] of [['en', 'Find a company request'], ['de', 'Firmenanfrage finden'], ['fr', 'Trouver une demande']]) {
  test(`request filter is localized in ${lang}`, async (t) => {
    const w = app(t, { lang });
    await until(() => w.document.querySelector('#requestFilter'));
    assert.equal(w.document.querySelector('label[for="requestFilter"]').textContent, label);
  });
}
test('failed case loading shows an error instead of an empty board and can recover', async (t) => {
  let failed = true;
  const w = app(t, { fetcher: async (url) => {
    if (url === '/cases' && failed) return { ok: false, status: 503, json: async () => ({ detail: 'Temporarily unavailable' }) };
  } });
  await until(() => w.document.querySelector('#retryCases'));
  assert.match(w.document.querySelector('[role="alert"]').textContent, /Temporarily unavailable/);
  assert.equal(w.document.querySelector('.kpis'), null);
  failed = false;
  w.document.querySelector('#retryCases').click();
  await until(() => w.document.querySelector('#requestFilter'));
  assert.equal(w.document.querySelectorAll('.case-card').length, 2);
});

function companyCase() {
  return {
    ...requests[0], created_at: '2026-10-18', contact_name: '', contact_email: '', events: [],
    analysis: { summary: 'Glucose monitoring', company_does: 'Sensors', company_needs: ['Study partner'], search_query: 'sensors' },
    matches: [{ id: 'partner', name: 'Research partner', selected: true, archetype: 'research', entity_type: 'unit', institution: 'Bern', url: 'https://example.org', why: 'Sensors' }],
    outreach: { brief: { token: 'existing', at: '2026-10-18', lang: 'en', explainer: [], data: { hook: 'Original pitch', items: [], sources: [] } } },
  };
}
test('canton branding replaces the placeholder mark and provides institutional footer links', async (t) => {
  const w = app(t), d = w.document;
  await until(() => d.querySelector('#requestFilter'));
  assert.equal(d.documentElement.dataset.theme, 'light');
  assert.equal(d.querySelector('.brand img').getAttribute('src'), '/static/brand/logo-be.svg');
  assert.equal(d.querySelector('.brand svg'), null);
  const theme = d.querySelector('#themeBtn');
  assert.equal(theme.getAttribute('aria-pressed'), 'false');
  theme.click();
  assert.equal(d.documentElement.dataset.theme, 'dark');
  assert.equal(theme.getAttribute('aria-pressed'), 'true');
  assert.equal(JSON.parse(w.localStorage.getItem('nav-theme')), 'dark');
  theme.click();
  assert.equal(d.documentElement.dataset.theme, 'light');
  assert.equal(d.querySelector('#foot img').getAttribute('src'), '/static/brand/logo-be.svg');
  const links = [...d.querySelectorAll('.footer-links a')];
  assert.equal(links.length, 4);
  assert.ok(links.every((a) => a.href.startsWith('https://www.be.ch/')));
  assert.ok(links.some((a) => a.href.endsWith('/impressum.html')));
  assert.ok(links.some((a) => a.href.endsWith('/rechtliches.html')));
  assert.match(d.querySelector('#foot').textContent, /Hack Apertus prototype/);
});
test('pitch generation announces progress, preserves previous output on failure, and allows retry', async (t) => {
  const c = companyCase();
  let rejectPitch;
  const w = app(t, { hash: '/staff/case/a', fetcher: async (url) => {
    if (url === '/cases/a') return { ok: true, json: async () => c };
    if (url === '/cases/a/brief') return new Promise((resolve) => { rejectPitch = () => resolve({ ok: false, status: 503, json: async () => ({ detail: 'Please retry later' }) }); });
  } });
  const d = w.document;
  await until(() => d.querySelector('#prepBrief'));
  assert.match(d.querySelector('#pitchBox').textContent, /Original pitch/);
  d.querySelector('#prepBrief').click();
  assert.equal(d.querySelector('#prepBrief').disabled, true);
  assert.equal(d.querySelector('#pitchBox').getAttribute('aria-busy'), 'true');
  assert.match(d.querySelector('#pitchBox [role="status"]').textContent, /Preparing/);
  await until(() => rejectPitch);
  rejectPitch();
  await until(() => d.querySelector('#pitchBox [role="alert"]'));
  assert.match(d.querySelector('#pitchBox').textContent, /Original pitch/);
  assert.match(d.querySelector('#pitchBox [role="alert"]').textContent, /Please retry later/);
  assert.equal(d.querySelector('#prepBrief').disabled, false);
  assert.match(d.querySelector('[aria-current="step"]').textContent, /^3Pitch/);
});
test('discovery keeps uncertain values red and approves without registering a company', async (t) => {
  const calls = [];
  const candidate = {id:'candidate', decision:'draft', source_url:'https://example.org', fields: Object.fromEntries(['name','site','canton','sector','topics','description','contribution'].map(k=>[k,{value:k==='name'?'Example Company':'',status:'review_required',evidence:[],reason:'Check source'}]))};
  const w = app(t, {hash:'/staff/discovery', fetcher:async (url, opts) => {
    calls.push([url, opts]);
    const result = url==='/staff/session' ? {can_manage_knowledge:true,role:'representative'} : url==='/cases' ? requests : url.startsWith('/discovery/runs?') || url==='/discovery/runs' && opts?.method==='GET' ? [{id:'run',status:'completed',created_at:'2026'}] : url==='/discovery/runs/run' ? {status:'completed',candidates:[candidate]} : url.startsWith('/discovery/candidates/') ? {} : undefined;
    return result === undefined ? undefined : {ok:true,json:async()=>result};
  }});
  await until(()=>w.document.querySelector('[data-run]'));
  w.document.querySelector('[data-run]').click();
  await until(()=>w.document.querySelector('[data-candidate]'));
  assert.equal(w.document.querySelectorAll('.needs-review').length,7);
  assert.match(w.document.querySelector('.needs-review').textContent,/Review required/);
  const form=w.document.querySelector('[data-candidate]');
  form.querySelector('[data-confirm="name"]').checked=true;
  form.requestSubmit(form.querySelector('[data-decision="approved"]'));
  await until(()=>calls.some(([u])=>u.startsWith('/discovery/candidates/')));
  const patch=calls.find(([u])=>u.startsWith('/discovery/candidates/'));
  assert.equal(JSON.parse(patch[1].body).fields.name,'Example Company');
  assert.equal(calls.some(([u,o])=>u==='/kb/companies' && o?.method==='POST'),false);
});


for (const [lang, enter, title] of [['en','How does it work?','How the platform works'],['de','Wie funktioniert das?','So funktioniert die Plattform'],['fr','Comment cela fonctionne ?','Comment fonctionne la plateforme']]) {
  test(`technical presentation follows the introduction in ${lang} and returns to it`, async t => {
    const w=app(t,{lang}), d=w.document;
    await until(()=>d.querySelector('#helpBtn'));
    d.querySelector('#helpBtn').click();
    for(let i=0;i<6;i++) d.querySelector('#guideNext').click();
    assert.equal(d.querySelector('#guideNext').textContent,enter);
    d.querySelector('#guideNext').click();
    assert.equal(d.querySelector('#guideTitle').textContent,title);
    assert.equal(d.querySelector('#guideCount').textContent,'01 / 7');
    assert.match(d.querySelector('#guideText').textContent,/FastAPI/);
    d.querySelector('#guideBack').click();
    assert.equal(d.querySelector('#guideCount').textContent,'07 / 7');
    d.querySelector('#guideNext').click();
    for(let i=0;i<6;i++) d.querySelector('#guideNext').click();
    assert.match(d.querySelector('#guideText').textContent,/Piper/);
    d.querySelector('#guideNext').click();
    assert.equal(d.querySelector('#platformGuide'),null);
  });
}


test('saved KB-only pitch stays visible after reload and restores approvals for regeneration', async t=>{
  const c=companyCase();c.matches=[];
  const refs=[{id:'local',source_id:'abc',revision:'v1'}];
  c.outreach.brief.knowledge_sources=refs;
  let payload;
  const w=app(t,{hash:'/staff/case/a',fetcher:async(url,options)=>{
    if(url==='/cases/a')return {ok:true,json:async()=>c};
    if(url==='/cases/a/brief'){payload=JSON.parse(options.body);return {ok:true,json:async()=>({})};}
    return undefined;
  }});
  await until(()=>w.document.querySelector('#prepBrief'));
  assert.match(w.document.querySelector('#pitchBox').textContent,/Original pitch/);
  assert.ok(w.document.querySelector('#prepMail'));
  w.document.querySelector('#prepBrief').click();
  await until(()=>payload);
  assert.deepEqual(payload.knowledge_sources,refs);
  await until(()=>w.document.querySelector("#prepBrief") && !w.document.querySelector("#prepBrief").disabled);
});
