// Vibe Studio dashboard. Plain JS, no pop-up dialogs (browsers inside VS Code block them).
// Every number shown comes from the API.
window.addEventListener('error', (e) => {
  fetch('/api/clientlog', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page: location.pathname, msg: String(e.message), src: e.filename, line: e.lineno})}).catch(() => {});
});
window.addEventListener('unhandledrejection', (e) => {
  fetch('/api/clientlog', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page: location.pathname, msg: String(e.reason && e.reason.message || e.reason)})}).catch(() => {});
});

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (t) => {
  if (t == null) return '-';
  t = Math.max(0, t);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = (t % 60).toFixed(1).padStart(4, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
};
const mins = (s) => (s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`);
const api = async (url, opts = {}) => {
  const init = opts.body && !(opts.body instanceof FormData)
    ? {...opts, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(opts.body)} : opts;
  const r = await fetch(url, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
};
const say = (el, text, kind = '') => { el.textContent = text; el.className = `msg ${kind}`; };
const store = {get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} }};

const S = {pid: null, data: null, words: [], comments: [], music: {music: [], sfx: []}, jobsTimer: null, active: new Set(), source: 'source'};

// ------------------------------------------------------------ theme
if (store.get('vs-theme') === 'dark') document.documentElement.dataset.theme = 'dark';
const syncTheme = () => { $('#themeBtn').textContent = document.documentElement.dataset.theme === 'dark' ? 'Light mode' : 'Dark mode'; };
$('#themeBtn').onclick = () => {
  const dark = document.documentElement.dataset.theme !== 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  store.set('vs-theme', dark ? 'dark' : 'light');
  syncTheme();
};
syncTheme();

// ------------------------------------------------------------ routing
window.addEventListener('hashchange', route);
async function route() {
  const pid = decodeURIComponent(location.hash.slice(1));
  if (pid) await openProject(pid); else await showHome();
}

// ------------------------------------------------------------ library
const statusInfo = (p) => ({
  imported: ['Imported', 'Create the plan'], transcribed: ['Transcribed', 'Create the plan'],
  planned: ['Plan ready', 'Make a preview'], previewed: ['Preview ready', 'Review and approve'],
  rendered: ['Finished', 'Download'],
}[p.status] || [p.status, 'Open']);

async function showHome() {
  S.pid = null;
  clearTimeout(S.jobsTimer);
  $('#project').hidden = true;
  $('#home').hidden = false;
  $('#crumbs').innerHTML = '';
  const list = await api('/api/projects');
  $('#library').innerHTML = list.map((p) => {
    const [label, next] = statusInfo(p);
    return `<button class="vcard" data-id="${esc(p.id)}">
      <div class="thumb" style="background-image:url('/api/projects/${encodeURIComponent(p.id)}/thumb.jpg')"></div>
      <div class="body">
        <span class="title">${esc(p.name)}</span>
        <span class="meta">${mins(p.source.duration)} recording${p.brand ? ` - ${esc(p.brand.replace(/-/g, ' '))}` : ''}</span>
        <span><span class="chip ${p.status === 'rendered' ? 'ok' : 'accent'}">${esc(label)}</span></span>
        <span class="nextstep">Next: ${esc(next)}</span>
      </div></button>`;
  }).join('') + `<button class="vcard add" id="addCard">+ Add a recording</button>`;
}
$('#library').onclick = (e) => {
  if (e.target.closest('#addCard')) return openNew();
  const c = e.target.closest('.vcard[data-id]');
  if (c) location.hash = c.dataset.id;
};

// ------------------------------------------------------------ project
async function openProject(pid) {
  if (S.pid !== pid) S.source = '';  // start on the latest edit, not the raw original
  S.pid = pid;
  $('#home').hidden = true;
  $('#project').hidden = false;
  window.scrollTo(0, 0);
  try { S.music = await api('/api/music'); } catch {}
  await refresh();
  pollJobs();
}

async function refresh() {
  const d = await api(`/api/projects/${encodeURIComponent(S.pid)}`);
  S.data = d;
  const {project: p, plan} = d;
  $('#crumbs').innerHTML = `<a href="#" id="toHome">All videos</a> / ${esc(p.name)}`;
  $('#toHome').onclick = (e) => { e.preventDefault(); location.hash = ''; };
  $('#projName').textContent = p.name;
  const st = plan?.stats;
  $('#projMeta').textContent = st
    ? `${mins(st.source_duration)} recording, about ${mins(st.edited_duration)} after the edit (${Math.round(st.removed_seconds)} s of mistakes and pauses removed).`
    : `${mins(p.source.duration)} recording. No editing plan yet.`;
  S.comments = await api(`/api/projects/${encodeURIComponent(S.pid)}/comments`).catch(() => []);
  renderSteps();
  renderSources();
  drawStrip();
  renderNext();
  renderEdit();
  renderStyle();
  renderShorts();
  renderFiles();
  renderNotes();
  if (plan) loadTranscript();
}

function progressState() {
  const {plan, exports} = S.data;
  const vids = exports.filter((x) => x.endsWith('.mp4'));
  const previews = vids.filter((x) => x.includes('_preview'));
  const finals = vids.filter((x) => !x.includes('_preview'));
  const approved = plan && ['approved', 'rendered'].includes(plan.status);
  return {plan: !!plan, preview: previews.length > 0, approved, final: finals.length > 0 && plan?.status === 'rendered', vids, finals};
}

function renderSteps() {
  const s = progressState();
  const steps = [['Import', true], ['Plan', s.plan], ['Preview', s.preview], ['Approve', s.approved], ['Final videos', s.final]];
  let nowSet = false;
  $('#steps').innerHTML = steps.map(([name, done]) => {
    let cls = done ? 'done' : '';
    if (!done && !nowSet) { cls = 'now'; nowSet = true; }
    return `<li class="${cls}">${name}</li>`;
  }).join('');
}

// player sources as chips
function sourceLabel(f) {
  if (f === 'source') return 'Original';
  const prev = f.includes('_preview') ? ' (preview)' : '';
  if (f.startsWith('shorts/')) {
    const m = f.match(/short(\d+)_/);
    return `Short ${m ? +m[1] : ''}${f.includes('_clean') ? ' no captions' : ''}${prev}`;
  }
  if (f.includes('_youtube')) return `YouTube 16:9${prev}`;
  if (f.includes('_shorts')) return `Vertical 9:16${prev}`;
  if (f.includes('_square')) return `Square${prev}`;
  return f;
}
function renderSources() {
  const vids = progressState().vids;
  const list = ['source', ...vids.sort((a, b) => a.startsWith('shorts/') - b.startsWith('shorts/') || a.localeCompare(b))];
  if (!list.includes(S.source)) S.source = list.find((f) => f.includes('_youtube') && !f.includes('_preview')) || list.find((f) => f.includes('_youtube')) || 'source';
  $('#sourceChips').innerHTML = list.map((f) => `<button type="button" role="tab" data-src="${esc(f)}" aria-selected="${f === S.source}">${esc(sourceLabel(f))}</button>`).join('');
  loadPlayer();
}
$('#sourceChips').onclick = (e) => {
  const b = e.target.closest('[data-src]');
  if (!b) return;
  S.source = b.dataset.src;
  $$('#sourceChips button').forEach((x) => x.setAttribute('aria-selected', x === b));
  loadPlayer();
};
function loadPlayer() {
  // the /play/ route serves a copy with Opus audio so sound works in every browser (incl. VS Code's)
  const url = S.source === 'source' ? `/media/${encodeURIComponent(S.pid)}/play/source`
    : `/media/${encodeURIComponent(S.pid)}/play/${S.source.split('/').map(encodeURIComponent).join('/')}`;
  const v = $('#player');
  if (v.dataset.src !== url) { v.src = url; v.dataset.src = url; }
}
const srcTime = () => (S.source === 'source' ? $('#player').currentTime : null);

function drawStrip() {
  const {project: p, segments, plan} = S.data;
  const dur = p.source.duration || 1;
  const segs = segments || [[0, dur]];
  $('#strip').innerHTML = segs.map(([a, b]) => `<div class="seg" style="left:${(a / dur) * 100}%;width:${((b - a) / dur) * 100}%" title="Kept ${fmt(a)} - ${fmt(b)}"></div>`).join('')
    + S.comments.filter((c) => c.source_at != null && c.status === 'open' && !c.parent).map((c) =>
      `<div class="mark" data-t="${c.source_at}" style="left:${(c.source_at / dur) * 100}%" title="${esc(c.text)}"></div>`).join('')
    + '<div class="head" id="head"></div>';
  $('#stripInfo').textContent = plan ? `${segs.length} kept parts of the original` : '';
}
$('#strip').onclick = (e) => {
  if (e.target.dataset.t) return seekSource(parseFloat(e.target.dataset.t));
  const r = e.currentTarget.getBoundingClientRect();
  seekSource(((e.clientX - r.left) / r.width) * S.data.project.source.duration);
};
function seekSource(t) {
  if (S.source !== 'source') { S.source = 'source'; renderSources(); }
  const v = $('#player');
  const go = () => { v.currentTime = t; v.play().catch(() => {}); };
  v.readyState >= 1 ? go() : v.addEventListener('loadedmetadata', go, {once: true});
}
$('#player').addEventListener('timeupdate', () => {
  const v = $('#player');
  $('#noteTime').textContent = fmt(v.currentTime);
  const t = srcTime(), head = $('#head');
  if (head) { head.style.display = t == null ? 'none' : 'block'; if (t != null) head.style.left = `${(t / S.data.project.source.duration) * 100}%`; }
  const now = $('.transcript span.now');
  if (now) now.classList.remove('now');
  if (t != null && S.words.length) {
    const i = S.words.findIndex((w) => w.start <= t && t <= w.end + 0.05);
    if (i >= 0) $(`.transcript span[data-i="${i}"]`)?.classList.add('now');
  }
});

// ------------------------------------------------------------ next step
function renderNext() {
  const s = progressState();
  const {plan} = S.data;
  const reviewUrl = `/review/${encodeURIComponent(S.pid)}`;
  const busy = $('#jobs').dataset.busy === '1';
  let html;
  if (!s.plan) {
    html = card('Step 2', 'Create the editing plan', 'I transcribe the recording on this computer, find mistakes, retakes and long pauses, and suggest cuts, captions and graphics for you to check.',
      `<button class="primary big" id="doPlan" ${busy ? 'disabled' : ''}>Create the editing plan</button>`);
  } else if (!s.preview) {
    html = card('Step 3', 'Make a preview', 'A quick, smaller version so you can watch the edit before anything is final.',
      `<button class="primary big" id="doPreview" ${busy ? 'disabled' : ''}>Make a preview</button>`);
  } else if (!s.approved) {
    html = card('Step 4', 'Review and approve', 'Watch the preview, leave notes or drawings in the review screen, then approve when you are happy.',
      `<a class="primary big" href="${reviewUrl}">Open review screen</a>
       <div class="alt"><button class="secondary" id="doApprove">Approve the plan</button><button class="secondary" id="doPreview" ${busy ? 'disabled' : ''}>New preview</button></div>`);
  } else if (!s.final) {
    html = card('Step 5', 'Make the final videos', 'Full quality 1080p versions of everything, checked automatically before they are marked ready.',
      `<button class="primary big" id="doFinal" ${busy ? 'disabled' : ''}>Render final videos</button>
       <div class="alt"><a class="secondary" href="${reviewUrl}">Open review screen</a></div>`);
  } else {
    html = card('Done', 'Your videos are ready', 'Download them below, or keep refining: any change makes a new version you can compare.',
      `<button class="primary big" id="goFiles">See downloads</button>
       <div class="alt"><a class="secondary" href="${reviewUrl}">Open review screen</a></div>`);
  }
  $('#nextCard').innerHTML = html;
  $('#doPlan')?.addEventListener('click', () => startPlan({mode: S.data.project.mode}));
  $('#doPreview')?.addEventListener('click', () => renderAll('preview'));
  $('#doFinal')?.addEventListener('click', () => renderAll('final'));
  $('#doApprove')?.addEventListener('click', async () => { await api(`/api/projects/${encodeURIComponent(S.pid)}/approve`, {method: 'POST'}); refresh(); });
  $('#goFiles')?.addEventListener('click', () => selectTab('files'));
  void plan;
}
const card = (label, title, text, actions) => `<div class="label">${label}</div><h2>${title}</h2><p>${text}</p>${actions}`;

async function startPlan(opts) {
  const job = await api(`/api/projects/${encodeURIComponent(S.pid)}/plan`, {method: 'POST', body: opts});
  S.active.add(job.id);
  pollJobs();
}
async function renderAll(quality) {
  const plan = S.data.plan;
  try {
    const j1 = await api(`/api/projects/${encodeURIComponent(S.pid)}/render`, {method: 'POST', body: {quality, what: 'main'}});
    S.active.add(j1.id);
    if (plan?.clips?.length) {
      const j2 = await api(`/api/projects/${encodeURIComponent(S.pid)}/render`, {method: 'POST', body: {quality, what: 'shorts'}});
      S.active.add(j2.id);
    }
  } catch (err) { say($('#askMsg'), err.message, 'err'); }
  pollJobs();
}

// ------------------------------------------------------------ jobs
async function pollJobs() {
  clearTimeout(S.jobsTimer);
  if (!S.pid) return;
  const list = (await api(`/api/jobs?project=${encodeURIComponent(S.data?.project?.id || S.pid)}`).catch(() => [])).slice(0, 3);
  const label = {plan: 'Transcribing and planning', 'render-main-preview': 'Preview of the full video', 'render-main-final': 'Final full video',
    'render-shorts-preview': 'Preview of the Shorts', 'render-shorts-final': 'Final Shorts'};
  const recent = list.filter((j) => ['running', 'queued'].includes(j.status) || S.active.has(j.id) || ['failed', 'interrupted'].includes(j.status) && (Date.now() / 1000 - j.created) < 3600);
  $('#jobs').innerHTML = recent.map((j) => `<div class="job" data-s="${esc(j.status)}">
      <div class="top"><span>${esc(label[j.kind] || j.kind)}${j.status === 'running' ? ` - ${esc(j.stage)} ${(j.progress * 100).toFixed(0)}%` : j.status === 'queued' ? ' - waiting' : ` - ${esc(j.status)}`}</span>
      ${['running', 'queued'].includes(j.status) ? `<button class="secondary" data-cancel="${esc(j.id)}">Cancel</button>` : ''}
      ${['failed', 'interrupted', 'cancelled'].includes(j.status) ? `<button class="secondary" data-retry="${esc(j.id)}">Try again</button>` : ''}</div>
      <div class="bar"><i style="width:${(j.status === 'done' ? 1 : j.progress) * 100}%"></i></div>
      ${j.error ? `<p class="err">${esc(j.error)}</p>` : ''}</div>`).join('');
  const busy = list.some((j) => ['running', 'queued'].includes(j.status));
  const wasBusy = $('#jobs').dataset.busy === '1';
  $('#jobs').dataset.busy = busy ? '1' : '';
  let changed = false;
  for (const j of list) if (S.active.has(j.id) && !['running', 'queued'].includes(j.status)) { S.active.delete(j.id); changed = true; }
  if (changed || wasBusy !== busy) await refresh();
  S.jobsTimer = setTimeout(pollJobs, busy ? 1200 : 6000);
}
$('#jobs').onclick = async (e) => {
  const c = e.target.dataset.cancel, r = e.target.dataset.retry;
  if (c) await api(`/api/jobs/${c}/cancel`, {method: 'POST'});
  if (r) { try { const j = await api(`/api/jobs/${r}/retry`, {method: 'POST'}); S.active.add(j.id); } catch (err) { say($('#askMsg'), err.message, 'err'); } }
  pollJobs();
};

// ------------------------------------------------------------ tabs
function selectTab(name) {
  $$('.tabs button').forEach((x) => x.setAttribute('aria-selected', x.dataset.tab === name));
  $$('.tabpanel').forEach((x) => (x.hidden = x.id !== `tab-${name}`));
}
$('.tabs').onclick = (e) => { const b = e.target.closest('button'); if (b) selectTab(b.dataset.tab); };
document.addEventListener('click', (e) => { const a = e.target.closest('[data-seek]'); if (a) { e.preventDefault(); seekSource(parseFloat(a.dataset.seek)); } });

// Edit: cuts + transcript
function renderEdit() {
  const {plan} = S.data;
  const el = $('#tab-edit');
  if (!plan) { el.innerHTML = '<p class="muted">The list of suggested cuts appears here once the plan is made.</p>'; return; }
  const s = plan.summary;
  const typeName = {pause: 'long pause', filler: 'filler word', restart: 'restart', repeat: 'repeated take', false_start: 'false start',
    noise: 'unclear sound', dead_air: 'silence', manual: 'your cut'};
  el.innerHTML = `
    ${s.suggested_hook ? `<p><b>Opening hook:</b> "${esc(s.suggested_hook.text)}" <a href="#" data-seek="${s.suggested_hook.start}">${fmt(s.suggested_hook.start)}</a></p>` : ''}
    <h3>What gets removed</h3>
    <p class="hint">Switch a cut off to keep that part. Click a time to watch it.</p>
    <ul class="cuts">${plan.cuts.map((c) => `<li class="${c.enabled === false ? 'off' : ''}">
      <input type="checkbox" class="switch" data-cut="${esc(c.id)}" ${c.enabled !== false ? 'checked' : ''} aria-label="Remove this part">
      <button type="button" class="t" data-seek="${c.start}">${fmt(c.start)}</button>
      <span class="what">${esc(c.text ? `"${c.text}"` : c.reason)}<span class="kind">${esc(typeName[c.type] || c.type)}, ${(c.end - c.start).toFixed(1)} s</span></span></li>`).join('')}</ul>
    <h3>Transcript</h3>
    <p class="hint">Click a word to jump there. Double-click a word to fix its spelling (timing stays the same).</p>
    <div class="transcript" id="transcript"><span class="muted">Loading...</span></div>`;
  el.onchange = async (e) => {
    if (!e.target.dataset.cut) return;
    await revise({ops: [{op: 'toggle', id: e.target.dataset.cut, enabled: e.target.checked}], request: `${e.target.checked ? 'Cut' : 'Keep'} ${e.target.dataset.cut}`});
  };
}
async function loadTranscript() {
  const t = await api(`/api/projects/${encodeURIComponent(S.pid)}/transcript`).catch(() => ({words: []}));
  S.words = t.words || [];
  const segs = S.data.segments || [];
  const kept = (w) => segs.some(([a, b]) => a <= (w.start + w.end) / 2 && (w.start + w.end) / 2 <= b);
  const el = $('#transcript');
  if (!el) return;
  el.innerHTML = S.words.map((w, i) => `<span data-i="${i}" class="${kept(w) ? '' : 'cut'}">${esc(w.word)}</span>`).join(' ');
  el.onclick = (e) => { const s = e.target.closest('span[data-i]'); if (s) seekSource(S.words[s.dataset.i].start); };
  el.ondblclick = (e) => {
    const s = e.target.closest('span[data-i]');
    if (!s) return;
    const i = +s.dataset.i;
    s.outerHTML = `<input class="inline-edit" data-fix="${i}" value="${esc(S.words[i].word)}">`;
    const inp = $(`[data-fix="${i}"]`);
    inp.focus(); inp.select();
    const done = async (save) => {
      const v = inp.value.trim();
      if (save && v && v !== S.words[i].word) {
        await api(`/api/projects/${encodeURIComponent(S.pid)}/correct`, {method: 'POST', body: {index: i, text: v}});
        S.words[i].word = v;
        say($('#askMsg'), 'Word fixed. It will show in the next preview.', 'ok');
      }
      loadTranscript();
    };
    inp.addEventListener('keydown', (k) => { if (k.key === 'Enter') done(true); if (k.key === 'Escape') done(false); });
    inp.addEventListener('blur', () => done(true), {once: true});
  };
}

// Style: captions, graphics, logo, music
const STYLE_CARDS = [
  ['premium', 'Premium', 'One clean line on a rounded brand panel', 'background:#0F1E4A;border-radius:6px;padding:4px 10px'],
  ['clean_shadow', 'Clean shadow', 'White text, soft shadow, no box', 'text-shadow:0 2px 6px rgba(0,0,0,.6)'],
  ['punch', 'Punch', 'Big 2-3 word captions, high energy', 'font-size:1rem;text-transform:uppercase;-webkit-text-stroke:1px #000'],
  ['minimal', 'Minimal', 'Small boxed captions', 'background:rgba(0,0,0,.55);padding:2px 8px;font-weight:600'],
];
function renderStyle() {
  const {plan} = S.data;
  const el = $('#tab-style');
  if (!plan) { el.innerHTML = '<p class="muted">Style options appear once the plan is made.</p>'; return; }
  const c = plan.captions, bug = plan.logo_bug || {}, music = plan.audio?.music;
  el.innerHTML = `
    <h3 style="margin-top:0">Captions</h3>
    <div class="styles">${STYLE_CARDS.map(([id, name, desc, css]) => `<button type="button" class="style-card" data-style="${id}" aria-pressed="${c.style === id}">
      <span class="demo"><span style="${css}">Book <span style="color:${esc(c.highlight || '#F97316')}">more</span> jobs</span></span>
      <span class="name">${name}</span><small>${desc}</small></button>`).join('')}</div>
    <div class="setting" style="margin-top:.8rem"><span>Show captions</span><input type="checkbox" class="switch" id="capOn" ${c.enabled ? 'checked' : ''}></div>
    <div class="setting"><span>Caption size</span><input type="range" id="capSize" min="0.6" max="1.6" step="0.05" value="${c.size_scale ?? 1}"></div>
    <div class="setting"><span>Position</span><select id="capPos"><option value="auto">Automatic</option><option value="bottom">Bottom</option><option value="top">Top</option></select></div>
    <div class="setting"><span>Highlight color</span><input type="color" id="capColor" value="${esc(c.highlight || '#F97316')}" style="width:3rem;height:2rem;padding:2px"></div>
    <h3>Brand</h3>
    <div class="setting"><span>Logo in the corner</span><input type="checkbox" class="switch" id="bugOn" ${bug.enabled ? 'checked' : ''}></div>
    <h3>Music</h3>
    <div class="setting"><span>Background music</span><select id="musicSel"><option value="">None</option>${(S.music.music || []).map((m) =>
      `<option value="${esc(m.path)}" ${music && music.path === m.path ? 'selected' : ''}>${esc(m.title || m.file)}</option>`).join('')}</select></div>
    ${(S.music.music || []).length ? '' : '<p class="hint">No licensed tracks downloaded yet.</p>'}
    <div class="setting"><span>Music level (quieter - louder)</span><input type="range" id="musicVol" min="-24" max="-8" step="1" value="${music?.bed_db ?? -16}" ${music ? '' : 'disabled'}></div>
    <div class="setting"><span>Sound effects on graphics</span><input type="checkbox" class="switch" id="sfxOn" ${plan.audio?.sfx?.enabled ? 'checked' : ''}></div>
    <p class="hint">Music and sound effects are from Mixkit (free for monetized YouTube and social, no credit needed). The music dips automatically while you talk.</p>
    <h3>Graphics</h3>
    ${plan.graphics.length ? plan.graphics.map((g) => `<div class="setting"><span>${esc(g.template.replace(/([a-z])([A-Z])/g, '$1 $2'))}
      <a href="#" data-seek="${g.start}">${fmt(g.start)}</a>${g.props.text || g.props.name ? ` <span class="muted">"${esc(g.props.text || g.props.name)}"</span>` : ''}</span>
      <input type="checkbox" class="switch" data-gfx="${esc(g.id)}" ${g.enabled !== false ? 'checked' : ''}></div>`).join('') : '<p class="hint">No graphics yet. Ask for one, e.g. "add a title behind me saying 25,000 doors".</p>'}
    <div class="setting"><span>Zooms (${plan.zooms.filter((z) => z.enabled !== false).length} of ${plan.zooms.length} on)</span>
      <input type="checkbox" class="switch" id="zoomAll" ${plan.zooms.some((z) => z.enabled !== false) ? 'checked' : ''} ${plan.zooms.length ? '' : 'disabled'}></div>`;
  $('#capPos').value = c.position || 'auto';
  const set = (path, value, label) => revise({ops: [{op: 'set', path, value}], request: label});
  el.querySelectorAll('[data-style]').forEach((b) => (b.onclick = () => revise({request: `${b.dataset.style.replace('_', ' ')} captions`})));
  $('#capOn').onchange = (e) => set('captions.enabled', e.target.checked, 'Captions on/off');
  $('#capSize').onchange = (e) => set('captions.size_scale', parseFloat(e.target.value), 'Caption size');
  $('#capPos').onchange = (e) => set('captions.position', e.target.value, 'Caption position');
  $('#capColor').onchange = (e) => set('captions.highlight', e.target.value.toUpperCase(), 'Caption highlight color');
  $('#bugOn').onchange = (e) => set('logo_bug', {...(plan.logo_bug || {}), enabled: e.target.checked, position: (plan.logo_bug || {}).position || 'bottom-right'}, 'Logo on/off');
  $('#musicSel').onchange = (e) => set('audio.music', e.target.value ? {path: e.target.value, bed_db: parseFloat($('#musicVol').value)} : null, 'Background music');
  $('#musicVol').onchange = (e) => music && set('audio.music', {...music, bed_db: parseFloat(e.target.value)}, 'Music level');
  $('#sfxOn').onchange = (e) => set('audio.sfx', {...(plan.audio?.sfx || {level_db: -18}), enabled: e.target.checked}, 'Sound effects');
  el.querySelectorAll('[data-gfx]').forEach((cb) => (cb.onchange = () => revise({ops: [{op: 'toggle', id: cb.dataset.gfx, enabled: cb.checked}], request: `Graphic ${cb.dataset.gfx}`})));
  $('#zoomAll').onchange = (e) => revise({ops: plan.zooms.map((z) => ({op: 'toggle', id: z.id, enabled: e.target.checked})), request: 'Zooms on/off'});
}

function renderShorts() {
  const {plan} = S.data;
  const el = $('#tab-shorts');
  if (!plan?.clips?.length) { el.innerHTML = '<p class="muted">No Shorts in this plan. Choose "Full video + Shorts" when adding a recording.</p>'; return; }
  const names = {hook: 'Hook', value: 'Value', clarity: 'Clarity', relevance: 'Fit', standalone: 'Alone', retention: 'Pace', cta: 'CTA'};
  el.innerHTML = `<p class="hint" style="margin-top:0">Scores are an editor's judgement, not a prediction of views.</p>` + plan.clips.map((c, i) => `<div class="clip">
      <div class="top"><span class="title">${i + 1}. ${esc(c.title)}</span><input type="checkbox" class="switch" data-clip="${esc(c.id)}" ${c.enabled !== false ? 'checked' : ''} aria-label="Include this Short"></div>
      <p class="hint"><a href="#" data-seek="${c.start}">${fmt(c.start)}</a> - ${fmt(c.end)} - "${esc(c.hook)}"</p>
      <div class="scores">${Object.entries(c.scores).map(([k, v]) => `<div><b>${v}</b>${names[k]}</div>`).join('')}</div></div>`).join('');
  el.querySelectorAll('[data-clip]').forEach((cb) => (cb.onchange = () => revise({ops: [{op: 'toggle', id: cb.dataset.clip, enabled: cb.checked}], request: `Short ${cb.dataset.clip}`})));
}

function renderFiles() {
  const {exports, plan} = S.data;
  const el = $('#tab-files');
  const files = exports.filter((f) => !f.startsWith('qa/'));
  if (!files.length) { el.innerHTML = '<p class="muted">Finished videos, caption files and chapter lists appear here.</p>'; return; }
  const results = [...(plan?.last_render?.results || []), ...(plan?.last_shorts_render?.results || [])];
  const ok = (f) => results.find((r) => r.path.replace(/\\/g, '/').endsWith(f));
  const kind = (f) => (f.endsWith('.mp4') ? 0 : f.endsWith('.md') || f.endsWith('.txt') ? 1 : 2);
  el.innerHTML = `<ul class="files">${files.sort((a, b) => kind(a) - kind(b) || a.localeCompare(b)).map((f) => {
    const r = ok(f);
    return `<li><a href="/media/${encodeURIComponent(S.pid)}/exports/${f.split('/').map(encodeURIComponent).join('/')}" download>${esc(f.endsWith('.mp4') ? sourceLabel(f) : f)}</a>
      ${r ? `<span class="chip ${r.ok ? 'ok' : ''}">${r.ok ? 'Checked' : 'Problem'}</span>` : `<span class="muted" style="font-size:.8rem">${esc(f.split('.').pop())}</span>`}</li>`;
  }).join('')}</ul><p class="hint">Nothing is ever published automatically.</p>`;
}

// ------------------------------------------------------------ change requests
async function revise(body) {
  try {
    const r = await api(`/api/projects/${encodeURIComponent(S.pid)}/revise`, {method: 'POST', body});
    say($('#askMsg'), r.understood ? 'Updated. Make a new preview to see it.' : 'I could not turn that into a change here. Ask Claude in VS Code, or try wording like "make the captions bigger".', r.understood ? 'ok' : 'err');
    await refresh();
  } catch (err) { say($('#askMsg'), err.message, 'err'); }
}
$('#askForm').onsubmit = (e) => {
  e.preventDefault();
  const text = $('#askText').value.trim();
  if (!text) { say($('#askMsg'), 'Type what you want changed first.', 'err'); return; }
  revise({request: text, at: srcTime()});
  $('#askText').value = '';
};

// ------------------------------------------------------------ notes (comments)
function renderNotes() {
  const tops = S.comments.filter((c) => !c.parent).sort((a, b) => (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1) || a.at - b.at);
  $('#noteList').innerHTML = tops.map((c) => `<li class="${c.status !== 'open' ? 'done' : ''}">
      <button type="button" class="t" data-nfile="${esc(c.file)}" data-nat="${c.at}">${fmt(c.at)}</button>
      <span>${esc(c.text)}<span class="where">${esc(c.author || 'you')} - ${esc(sourceLabel(c.file))}${c.status !== 'open' ? ` - ${esc(c.status)}` : ''}</span>
        ${c.resolution ? `<span class="res">${esc(c.resolution)}</span>` : ''}</span>
      <span class="acts">${c.status === 'open' ? `<button type="button" data-ndone="${esc(c.id)}">Done</button>` : `<button type="button" data-nopen="${esc(c.id)}">Reopen</button>`}
        <button type="button" data-ndel="${esc(c.id)}">Delete</button></span></li>`).join('')
    || '<li><span></span><span class="muted">No notes yet. Pause the video, type a note, press Enter. For drawings and threads, use the review screen.</span><span></span></li>';
}
$('#noteForm').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('#noteText').value.trim();
  if (!text) { say($('#noteMsg'), 'Type your note first.', 'err'); $('#noteText').focus(); return; }
  const at = $('#player').currentTime;
  try {
    await api(`/api/projects/${encodeURIComponent(S.pid)}/comments`, {method: 'POST', body: {text, at, file: S.source, author: store.get('vs-author') || 'you'}});
  } catch (err) { say($('#noteMsg'), `Could not save: ${err.message}`, 'err'); return; }
  $('#noteText').value = '';
  say($('#noteMsg'), `Note saved at ${fmt(at)}.`, 'ok');
  S.comments = await api(`/api/projects/${encodeURIComponent(S.pid)}/comments`);
  renderNotes();
  drawStrip();
};
$('#noteList').onclick = async (e) => {
  const t = e.target;
  const base = `/api/projects/${encodeURIComponent(S.pid)}/comments`;
  if (t.dataset.nat) {
    if (S.source !== t.dataset.nfile && (t.dataset.nfile === 'source' || progressState().vids.includes(t.dataset.nfile))) { S.source = t.dataset.nfile; renderSources(); }
    const v = $('#player');
    const go = () => { v.currentTime = parseFloat(t.dataset.nat); v.pause(); };
    v.readyState >= 1 ? go() : v.addEventListener('loadedmetadata', go, {once: true});
    return;
  }
  if (t.dataset.ndel) {
    if (t.dataset.armed !== '1') { t.dataset.armed = '1'; t.textContent = 'Sure?'; setTimeout(() => { t.dataset.armed = ''; t.textContent = 'Delete'; }, 3000); return; }
    await api(`${base}/${t.dataset.ndel}`, {method: 'POST', body: {action: 'delete'}});
  } else if (t.dataset.ndone) {
    await api(`${base}/${t.dataset.ndone}`, {method: 'POST', body: {status: 'resolved', resolution: 'Marked done'}});
  } else if (t.dataset.nopen) {
    await api(`${base}/${t.dataset.nopen}`, {method: 'POST', body: {status: 'open', resolution: null}});
  } else return;
  S.comments = await api(base);
  renderNotes();
  drawStrip();
};

// ------------------------------------------------------------ new recording
async function fillBrands(sel) {
  const bs = await api('/api/brands');
  sel.innerHTML = '<option value="">No brand</option>' + bs.map((b) => `<option value="${esc(b.slug)}">${esc(b.name)}</option>`).join('');
  if (bs.length === 1) sel.value = bs[0].slug;
}
async function openNew() { await fillBrands($('#brandInput')); say($('#newMsg'), ''); $('#newDialog').showModal(); }
$('#newBtn').onclick = openNew;
const drop = $('#drop');
['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', (e) => { $('#fileInput').files = e.dataTransfer.files; $('#dropText').innerHTML = `<b>${esc(e.dataTransfer.files[0]?.name || '')}</b>`; });
$('#fileInput').onchange = () => { $('#dropText').innerHTML = `<b>${esc($('#fileInput').files[0]?.name || '')}</b>`; };
$('#newForm').onsubmit = async (e) => {
  if (e.submitter?.value === 'cancel') return;
  e.preventDefault();
  const f = $('#fileInput').files[0];
  if (!f && !$('#pathInput').value.trim()) { say($('#newMsg'), 'Choose a video file or paste a path first.', 'err'); return; }
  const mode = $('input[name="mode"]:checked').value;
  const fd = new FormData();
  if (f) fd.append('file', f); else fd.append('path', $('#pathInput').value.trim());
  fd.append('mode', mode);
  fd.append('brand', $('#brandInput').value);
  $('#createBtn').disabled = true;
  say($('#newMsg'), f ? 'Copying the video into the studio...' : 'Importing...');
  try {
    const p = await api('/api/projects', {method: 'POST', body: fd});
    const [mn, mx] = $('#shortLen').value.split(',').map(Number);
    $('#newDialog').close();
    location.hash = p.id;
    await openProject(p.id);
    await startPlan({mode, shorts_count: +$('#shortsCount').value, short_min: mn, short_max: mx});
  } catch (err) { say($('#newMsg'), err.message, 'err'); }
  $('#createBtn').disabled = false;
};

// ------------------------------------------------------------ brands (one question at a time)
async function showBrands() {
  const bs = await api('/api/brands');
  $('#brandList').innerHTML = bs.length ? bs.map((b) => `<div class="brand-row"><a href="#" class="tlink" data-slug="${esc(b.slug)}">${esc(b.name)}</a>
    <span class="chip ${b.complete ? 'ok' : ''}">${b.complete ? 'Complete' : 'Setup in progress'}</span></div>`).join('') : '<p class="muted">No brands yet.</p>';
}
async function askNext(slug, next) {
  if (next === undefined) next = (await api(`/api/brands/${slug}`)).next;
  $('#brandQ').innerHTML = next ? `<label>${esc(next[1])}<div class="row"><input id="brandAns"><button type="button" class="secondary" id="brandSave">Save</button>
    <button type="button" class="ghost" id="brandSkip">Skip</button></div></label>` : '<p class="msg ok">This brand is set up.</p>';
  if (!next) return;
  const save = async (value) => {
    try { const r = await api(`/api/brands/${slug}/answer`, {method: 'POST', body: {key: next[0], value}}); askNext(slug, r.next); showBrands(); }
    catch (err) { $('#brandQ').insertAdjacentHTML('beforeend', `<p class="msg err">${esc(err.message)}</p>`); }
  };
  $('#brandSave').onclick = () => save($('#brandAns').value);
  $('#brandSkip').onclick = () => save('skip');
  $('#brandAns').focus();
}
$('#brandsBtn').onclick = () => { showBrands(); $('#brandQ').innerHTML = ''; $('#brandDialog').showModal(); };
$('#brandList').onclick = (e) => { const a = e.target.closest('[data-slug]'); if (a) { e.preventDefault(); askNext(a.dataset.slug); } };
$('#brandCreate').onclick = async () => {
  const name = $('#brandName').value.trim();
  if (!name) return;
  const r = await api('/api/brands', {method: 'POST', body: {name}});
  $('#brandName').value = '';
  showBrands();
  askNext(r.brand.slug, r.next);
};

route();
