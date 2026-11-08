// Vibe Studio dashboard. Plain JS; every number shown comes from the API.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (t) => {
  if (t == null) return '-';
  t = Math.max(0, t);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = (t % 60).toFixed(1).padStart(4, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
};
const api = async (url, opts = {}) => {
  const r = await fetch(url, opts.body && !(opts.body instanceof FormData)
    ? {...opts, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(opts.body)} : opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
};

const state = {pid: null, data: null, words: [], jobsTimer: null, activeJobs: new Set()};

// ---------------------------------------------------------------- theme
const savedTheme = (() => { try { return localStorage.getItem('vs-theme'); } catch { return null; } })();
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
const syncThemeBtn = () => { $('#themeBtn').textContent = document.documentElement.dataset.theme === 'light' ? 'Dark mode' : 'Light mode'; };
$('#themeBtn').onclick = () => {
  const t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('vs-theme', t); } catch {}
  syncThemeBtn();
};
syncThemeBtn();

// ---------------------------------------------------------------- projects
async function loadProjects() {
  const list = await api('/api/projects');
  $('#projectList').innerHTML = list.map((p) => `
    <a href="#${esc(p.id)}" data-id="${esc(p.id)}" ${p.id === state.pid ? 'aria-current="true"' : ''}>
      ${esc(p.name)}<small>${(p.source.duration / 60).toFixed(1)} min - ${esc(p.status)}</small></a>`).join('');
  $('#empty').hidden = !!state.pid;
  return list;
}
$('#projectList').onclick = (e) => {
  const a = e.target.closest('a');
  if (a) { e.preventDefault(); openProject(a.dataset.id); }
};

async function openProject(pid) {
  state.pid = pid;
  history.replaceState(null, '', `#${pid}`);
  $('#empty').hidden = true;
  $('#workspace').hidden = false;
  await refresh();
  await loadProjects();
  pollJobs();
}

async function refresh() {
  const d = await api(`/api/projects/${state.pid}`);
  state.data = d;
  const {project: p, plan} = d;
  $('#projName').textContent = p.name;
  const st = plan?.stats;
  $('#projMeta').textContent = st
    ? `${fmt(st.source_duration)} recording, about ${fmt(st.edited_duration)} after edits. ${plan.summary.video_type.replace('_', ' ')}, ${plan.mode === 'repurpose' ? 'full video + Shorts' : plan.mode}.`
    : `${fmt(p.source.duration)} recording, ${p.source.width}x${p.source.height}. No plan yet.`;
  $('#planStatus').textContent = plan ? `Plan ${plan.status}, v${plan.version}` : 'No plan';
  $('#planStatus').dataset.s = plan?.status || '';
  const approved = plan && ['approved', 'rendered'].includes(plan.status);
  $('#approveBtn').hidden = !plan || approved;
  $('#renderBtn').hidden = !approved;
  $('#previewBtn').disabled = !plan;
  const hasVideos = (state.data.exports || []).some((x) => x.endsWith('.mp4'));
  $('#reviewLink').href = `/review/${encodeURIComponent(state.pid)}`;
  $('#reviewLink').setAttribute('aria-disabled', !hasVideos);
  $('#reviewLink').title = hasVideos ? 'Frame.io-style review: comment, draw, compare versions, approve' : 'Make a preview first';
  setupPlayer();
  await loadComments();
  drawStrip();
  renderPlan();
  renderStyle();
  renderShorts();
  renderExports();
  if (plan) loadTranscript();
}

// ---------------------------------------------------------------- player + strip
function setupPlayer() {
  const {project: p, exports} = state.data;
  const sel = $('#playerSource');
  const vids = exports.filter((x) => x.endsWith('.mp4'));
  const cur = sel.value;
  sel.innerHTML = `<option value="source">Original recording</option>` +
    vids.map((v) => `<option value="${esc(v)}">${esc(v.replace(/_/g, ' ').replace('.mp4', ''))}</option>`).join('');
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
  loadPlayer();
}
function loadPlayer() {
  const v = $('#playerSource').value;
  const url = v === 'source' ? `/media/${state.pid}/source/file` : `/media/${state.pid}/exports/${encodeURI(v)}`;
  if ($('#player').dataset.src !== url) { $('#player').src = url; $('#player').dataset.src = url; }
}
$('#playerSource').onchange = loadPlayer;
const sourceTime = () => ($('#playerSource').value === 'source' ? $('#player').currentTime : null);

function drawStrip() {
  const {project: p, segments, plan} = state.data;
  const dur = p.source.duration || 1;
  const strip = $('#strip');
  const segs = segments || [[0, dur]];
  strip.innerHTML = segs.map(([a, b]) =>
    `<div class="seg" style="left:${(a / dur) * 100}%;width:${((b - a) / dur) * 100}%" title="${fmt(a)} - ${fmt(b)} kept"></div>`).join('') +
    (plan?.chapters || []).map((c) => `<div class="mark" style="left:${(c.start / dur) * 100}%" title="${esc(c.title)}"></div>`).join('') +
    (state.comments || []).filter((c) => c.source_at != null && c.status === 'open').map((c) =>
      `<div class="cmark" data-t="${c.source_at}" style="left:${(c.source_at / dur) * 100}%" title="${esc(c.text)}"></div>`).join('') +
    '<div class="head" id="head"></div>';
  $('#stripTimes').textContent = plan ? `${segs.length} kept sections` : '';
}
$('#strip').onclick = (e) => {
  if (e.target.dataset.t) { seekSource(parseFloat(e.target.dataset.t)); return; }
  const r = e.currentTarget.getBoundingClientRect();
  seekSource(((e.clientX - r.left) / r.width) * state.data.project.source.duration);
};
function seekSource(t) {
  if ($('#playerSource').value !== 'source') { $('#playerSource').value = 'source'; loadPlayer(); }
  const pl = $('#player');
  const go = () => { pl.currentTime = t; pl.play().catch(() => {}); };
  pl.readyState >= 1 ? go() : pl.addEventListener('loadedmetadata', go, {once: true});
}
// ---------------------------------------------------------------- comments
async function loadComments() {
  state.comments = await api(`/api/projects/${state.pid}/comments`);
  const label = (c) => (c.file === 'source' ? 'Original' : c.file.replace(/_/g, ' ').replace('.mp4', ''));
  const list = [...state.comments].sort((a, b) => (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1) || a.at - b.at);
  $('#commentList').innerHTML = list.length ? list.map((c) => `<li data-s="${esc(c.status)}">
      <a class="tlink" data-cfile="${esc(c.file)}" data-cat="${c.at}">${fmt(c.at)}</a>
      <div>${esc(c.text)}<span class="where">${esc(label(c))}${c.status !== 'open' ? ` - ${esc(c.status)}` : ''}</span>
        ${c.resolution ? `<span class="res">${esc(c.resolution)}</span>` : ''}</div>
      <div class="acts">${c.status === 'open'
        ? `<button type="button" data-capply="${esc(c.id)}" title="Change the plan if this is a request like 'remove that zoom'">Apply</button>
           <button type="button" data-cdone="${esc(c.id)}">Resolve</button>`
        : `<button type="button" data-creopen="${esc(c.id)}">Reopen</button>`}
        <button type="button" data-cdel="${esc(c.id)}" aria-label="Delete comment">Delete</button></div></li>`).join('')
    : '<li><span></span><span class="meta">No comments yet. Claude reads open comments when you ask it to work through them.</span><span></span></li>';
}
const currentFile = () => $('#playerSource').value;
$('#commentForm').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('#commentText').value.trim();
  if (!text) { $('#reviseMsg').textContent = ''; $('#commentText').placeholder = 'Type your note here first'; $('#commentText').focus(); return; }
  const at = $('#player').currentTime;
  try {
    await api(`/api/projects/${state.pid}/comments`, {method: 'POST', body: {text, at, file: currentFile()}});
  } catch (err) { alert(`Couldn't save the comment: ${err.message}`); return; }
  $('#commentText').value = '';
  $('#commentText').placeholder = `Saved at ${fmt(at)}. Add another, or open Review videos for drawing and threads.`;
  await loadComments();
  drawStrip();
};
$('#commentList').onclick = async (e) => {
  const t = e.target;
  if (t.dataset.cat) {
    const f = t.dataset.cfile;
    if ($('#playerSource').value !== f && [...$('#playerSource').options].some((o) => o.value === f)) { $('#playerSource').value = f; loadPlayer(); }
    const pl = $('#player');
    const go = () => { pl.currentTime = parseFloat(t.dataset.cat); pl.pause(); };
    pl.readyState >= 1 ? go() : pl.addEventListener('loadedmetadata', go, {once: true});
    return;
  }
  const act = t.dataset.capply ? ['apply', t.dataset.capply] : t.dataset.cdone ? ['resolved', t.dataset.cdone]
    : t.dataset.creopen ? ['open', t.dataset.creopen] : t.dataset.cdel ? ['delete', t.dataset.cdel] : null;
  if (!act) return;
  const [what, id] = act;
  const body = what === 'apply' || what === 'delete' ? {action: what} : {status: what, resolution: what === 'resolved' ? 'Marked done' : null};
  const r = await api(`/api/projects/${state.pid}/comments/${id}`, {method: 'POST', body});
  if (what === 'apply') {
    $('#reviseMsg').textContent = r.status === 'applied' ? 'Comment applied to the plan. Make a preview to see it.'
      : 'That one needs Claude: ask "work through my comments" in VS Code.';
    await refresh();
  } else { await loadComments(); drawStrip(); }
};

$('#player').ontimeupdate = () => {
  $('#commentBtn').textContent = `Add at ${fmt($('#player').currentTime)}`;
  const t = sourceTime();
  const head = $('#head');
  if (head) head.style.display = t == null ? 'none' : 'block';
  if (t != null && head) head.style.left = `${(t / state.data.project.source.duration) * 100}%`;
  const now = document.querySelector('.transcript span.now');
  if (now) now.classList.remove('now');
  if (t != null && state.words.length) {
    const i = state.words.findIndex((w) => w.start <= t && t <= w.end + 0.05);
    if (i >= 0) document.querySelector(`.transcript span[data-i="${i}"]`)?.classList.add('now');
  }
};

// ---------------------------------------------------------------- tabs
document.querySelector('.tabs').onclick = (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  document.querySelectorAll('.tabs button').forEach((x) => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('.tabpanel').forEach((x) => (x.hidden = x.id !== `tab-${b.dataset.tab}`));
};

// ---------------------------------------------------------------- plan tab
function renderPlan() {
  const {plan} = state.data;
  const el = $('#tab-plan');
  if (!plan) {
    el.innerHTML = `<p>No editing plan yet.</p><button class="primary" id="planNow">Create the editing plan</button>
      <p class="hint">Transcribes the recording on this computer, finds mistakes and long pauses, and proposes cuts for you to review.</p>`;
    $('#planNow').onclick = () => startPlan({mode: state.data.project.mode});
    return;
  }
  const s = plan.summary;
  const hook = s.suggested_hook;
  el.innerHTML = `
    <p><strong>Topic:</strong> ${esc(s.topic)}</p>
    ${hook ? `<p><strong>Suggested hook</strong> <a class="tlink" data-t="${hook.start}">${fmt(hook.start)}</a>: "${esc(hook.text)}"</p>` : ''}
    ${s.intro_suggestions.map((t) => `<p class="meta">${esc(t)}</p>`).join('')}
    <h3>Cuts</h3>
    <p class="meta">Untick a cut to keep that part. Click a time to watch it.</p>
    <table><thead><tr><th>Cut</th><th>From</th><th>To</th><th>Why</th></tr></thead><tbody>
    ${plan.cuts.map((c) => `<tr class="${c.enabled === false ? 'off' : ''}">
      <td><input type="checkbox" class="toggle" data-id="${esc(c.id)}" ${c.enabled !== false ? 'checked' : ''} aria-label="Cut ${esc(c.id)}"></td>
      <td class="t"><a data-t="${c.start}">${fmt(c.start)}</a></td><td class="t">${fmt(c.end)}</td>
      <td>${esc(c.text ? `${c.type.replace('_', ' ')}: "${c.text}"` : c.reason)}</td></tr>`).join('')}
    </tbody></table>
    ${plan.mode !== 'shorts' && plan.chapters?.length ? `<h3>Chapters</h3>${plan.chapters.map((c) =>
      `<p><a class="tlink" data-t="${c.start}">${fmt(c.start)}</a> ${esc(c.title)}</p>`).join('')}` : ''}
    <h3>Re-plan</h3>
    <div class="row"><select id="replanMode">
      <option value="longform">Full edited video</option><option value="repurpose">Full video + Shorts</option><option value="shorts">One short video</option>
    </select><button id="replanBtn">Rebuild plan</button></div>
    <p class="hint">Rebuilding replaces manual changes. Use "Ask for a change" for small edits.</p>`;
  $('#replanMode').value = plan.mode;
  $('#replanBtn').onclick = () => startPlan({mode: $('#replanMode').value});
  el.onclick = (e) => { const a = e.target.closest('[data-t]'); if (a) seekSource(parseFloat(a.dataset.t)); };
  el.onchange = async (e) => {
    if (!e.target.classList.contains('toggle')) return;
    await revise({ops: [{op: 'toggle', id: e.target.dataset.id, enabled: e.target.checked}],
      request: `${e.target.checked ? 'Cut' : 'Keep'} ${e.target.dataset.id}`});
  };
}

async function startPlan(opts) {
  const job = await api(`/api/projects/${state.pid}/plan`, {method: 'POST', body: opts});
  state.activeJobs.add(job.id);
  pollJobs();
}

// ---------------------------------------------------------------- transcript
async function loadTranscript() {
  const t = await api(`/api/projects/${state.pid}/transcript`);
  state.words = t.words || [];
  const segs = state.data.segments || [];
  const kept = (w) => segs.some(([a, b]) => a <= (w.start + w.end) / 2 && (w.start + w.end) / 2 <= b);
  $('#tab-transcript').innerHTML = state.words.length ? `
    <p class="meta">Click a word to jump there. Double-click to fix a mis-heard word (timing stays the same). Crossed-out words are cut; dotted words were unclear to the transcriber.</p>
    <div class="transcript">${state.words.map((w, i) =>
      `<span data-i="${i}" class="${kept(w) ? '' : 'cut'} ${w.prob < 0.5 ? 'low' : ''}">${esc(w.word)}</span>`).join(' ')}</div>`
    : '<p>The transcript appears here once the plan is created.</p>';
  const tr = $('.transcript');
  if (!tr) return;
  tr.onclick = (e) => { const s = e.target.closest('span'); if (s) seekSource(state.words[s.dataset.i].start); };
  tr.ondblclick = async (e) => {
    const s = e.target.closest('span');
    if (!s) return;
    const fixed = prompt('Correct this word:', state.words[s.dataset.i].word);
    if (fixed == null || !fixed.trim()) return;
    await api(`/api/projects/${state.pid}/correct`, {method: 'POST', body: {index: +s.dataset.i, text: fixed.trim()}});
    s.textContent = fixed.trim();
    $('#reviseMsg').textContent = 'Word corrected. It will appear in the next preview.';
  };
}

// ---------------------------------------------------------------- captions & graphics
function renderStyle() {
  const {plan} = state.data;
  const el = $('#tab-style');
  if (!plan) { el.innerHTML = '<p>Available once the plan exists.</p>'; return; }
  const c = plan.captions;
  el.innerHTML = `<div class="settings">
    <label><span><input type="checkbox" class="toggle" id="capOn" ${c.enabled ? 'checked' : ''}> Burn captions into the video</span></label>
    <label>Caption style<select id="capStyle">
      <option value="premium">Premium - one line on a rounded brand panel</option>
      <option value="clean_shadow">Clean shadow - white text, soft shadow, no box</option>
      <option value="punch">Punch - big 2-3 word captions (Hormozi style)</option>
      <option value="clean">Clean - sentence captions for teaching</option>
      <option value="minimal">Minimal - small boxed text</option>
      <option value="karaoke">Highlight - current word lights up</option>
      <option value="bold">Bold - big punchy words for Shorts</option></select></label>
    <label>Size <input type="range" id="capSize" min="0.5" max="1.8" step="0.05" value="${c.size_scale}"></label>
    <label>Position<select id="capPos"><option value="auto">Automatic (avoids faces and app buttons)</option>
      <option value="bottom">Bottom</option><option value="lower">Lower third</option><option value="middle">Middle</option><option value="top">Top</option></select></label>
    <label>Highlight color <input type="color" id="capColor" value="${c.highlight || '#FFD400'}"></label>
    <h3>Motion graphics</h3>
    ${plan.graphics.length ? plan.graphics.map((g) => `<label><span><input type="checkbox" class="toggle gfx" data-id="${esc(g.id)}" ${g.enabled !== false ? 'checked' : ''}>
      ${esc(g.template.replace(/([a-z])([A-Z])/g, '$1 $2'))} at <a class="tlink" data-t="${g.start}">${fmt(g.start)}</a>
      ${g.props.text || g.props.title || g.props.name ? `- "${esc(g.props.text || g.props.title || g.props.name)}"` : ''}${g.placement === 'behind' ? ' (behind you)' : ''}</span></label>`).join('')
      : '<p class="meta">No graphics planned. Ask for one, e.g. "Add a title behind me saying THE BOOKED SOLID SYSTEM".</p>'}
    <h3>Zooms</h3>
    ${plan.zooms.length ? plan.zooms.map((z) => `<label><span><input type="checkbox" class="toggle zm" data-id="${esc(z.id)}" ${z.enabled !== false ? 'checked' : ''}>
      ${z.kind === 'ease' ? 'Slow push' : 'Punch-in'} ${Math.round((z.scale - 1) * 100)}% at <a class="tlink" data-t="${z.start}">${fmt(z.start)}</a></span></label>`).join('')
      : '<p class="meta">No zooms (screen recordings stay unzoomed so text is readable).</p>'}
    <h3>Audio</h3>
    <label>Noise reduction<select id="denoise"><option value="off">Off</option><option value="light">Light</option><option value="medium">Medium</option><option value="strong">Strong</option></select></label>
    <label><span><input type="checkbox" class="toggle" id="normOn" ${plan.audio.normalize ? 'checked' : ''}> Even out loudness (${plan.audio.target_lufs} LUFS, YouTube standard)</span></label>
    <h3>Exports</h3>
    ${['youtube', 'youtube_4k', 'shorts', 'square'].map((o) => `<label><span><input type="checkbox" class="toggle outp" value="${o}" ${plan.outputs.some((x) => x.name === o) ? 'checked' : ''}>
      ${{youtube: 'YouTube 1080p (16:9)', youtube_4k: 'YouTube 4K (16:9)', shorts: 'Vertical 1080x1920 (9:16)', square: 'Square 1080 (1:1)'}[o]}</span></label>`).join('')}
  </div>`;
  $('#capStyle').value = c.style;
  $('#capPos').value = c.position;
  $('#denoise').value = plan.audio.denoise;
  const set = (path, value, label) => revise({ops: [{op: 'set', path, value}], request: label});
  $('#capOn').onchange = (e) => set('captions.enabled', e.target.checked, 'Captions on/off');
  $('#capStyle').onchange = (e) => revise({request: `${e.target.value} captions`});
  $('#capSize').onchange = (e) => set('captions.size_scale', parseFloat(e.target.value), 'Caption size');
  $('#capPos').onchange = (e) => set('captions.position', e.target.value, 'Caption position');
  $('#capColor').onchange = (e) => set('captions.highlight', e.target.value.toUpperCase(), 'Caption highlight color');
  $('#denoise').onchange = (e) => set('audio.denoise', e.target.value, 'Noise reduction');
  $('#normOn').onchange = (e) => set('audio.normalize', e.target.checked, 'Loudness');
  el.querySelectorAll('.gfx, .zm').forEach((cb) => (cb.onchange = () =>
    revise({ops: [{op: 'toggle', id: cb.dataset.id, enabled: cb.checked}], request: `Toggle ${cb.dataset.id}`})));
  el.querySelectorAll('.outp').forEach((cb) => (cb.onchange = () => {
    const sizes = {youtube: [1920, 1080, '16:9'], youtube_4k: [3840, 2160, '16:9'], shorts: [1080, 1920, '9:16'], square: [1080, 1080, '1:1']};
    const outs = [...el.querySelectorAll('.outp:checked')].map((x) => ({name: x.value, width: sizes[x.value][0], height: sizes[x.value][1], aspect: sizes[x.value][2]}));
    if (outs.length) set('outputs', outs, 'Export formats');
  }));
  el.onclick = (e) => { const a = e.target.closest('[data-t]'); if (a) { e.preventDefault(); seekSource(parseFloat(a.dataset.t)); } };
}

// ---------------------------------------------------------------- shorts
function renderShorts() {
  const {plan} = state.data;
  const el = $('#tab-shorts');
  if (!plan?.clips?.length) {
    el.innerHTML = `<p>No Shorts in this plan.</p><p class="meta">Rebuild the plan as "Full video + Shorts" to find the strongest stand-alone moments.</p>`;
    return;
  }
  const names = {hook: 'Hook', value: 'Value', clarity: 'Clarity', relevance: 'Relevance', standalone: 'Stands alone', retention: 'Pacing', cta: 'CTA'};
  el.innerHTML = `<p class="meta">Scores are editorial judgements, not predictions of views. Each Short starts and ends on full sentences.</p>
    ${plan.clips.map((c, i) => `<div class="clip"><div class="top">
      <label><input type="checkbox" class="toggle clipon" data-id="${esc(c.id)}" ${c.enabled !== false ? 'checked' : ''}> <strong>${i + 1}. ${esc(c.title)}</strong></label>
      <span class="meta">${c.total.toFixed(1)} / 10</span></div>
      <p class="meta"><a class="tlink" data-t="${c.start}">${fmt(c.start)}</a> - ${fmt(c.end)}, about ${Math.round(c.est_duration)} s</p>
      <div class="scores">${Object.entries(c.scores).map(([k, v]) => `<div><b>${v}</b>${names[k]}</div>`).join('')}</div></div>`).join('')}
    <div class="row" style="margin-top:1rem"><button id="shortPrev">Preview Shorts</button>
      <button class="primary" id="shortFinal" ${['approved', 'rendered'].includes(plan.status) ? '' : 'disabled title="Approve the plan first"'}>Render Shorts</button></div>`;
  el.onclick = (e) => { const a = e.target.closest('[data-t]'); if (a) seekSource(parseFloat(a.dataset.t)); };
  el.querySelectorAll('.clipon').forEach((cb) => (cb.onchange = () =>
    revise({ops: [{op: 'toggle', id: cb.dataset.id, enabled: cb.checked}], request: `Toggle short ${cb.dataset.id}`})));
  $('#shortPrev').onclick = () => render('preview', 'shorts');
  $('#shortFinal').onclick = () => render('final', 'shorts');
}

// ---------------------------------------------------------------- exports
function renderExports() {
  const {exports, plan} = state.data;
  const el = $('#tab-exports');
  const results = [...(plan?.last_render?.results || []), ...(plan?.last_shorts_render?.results || [])];
  const check = (f) => results.find((r) => r.path.replace(/\\/g, '/').endsWith(f));
  el.innerHTML = exports.length ? `<table><thead><tr><th>File</th><th>Check</th></tr></thead><tbody>
    ${exports.map((f) => { const r = check(f); return `<tr><td><a href="/media/${state.pid}/exports/${encodeURI(f)}" target="_blank" rel="noopener">${esc(f)}</a></td>
      <td>${r ? (r.ok ? `passed (${r.width}x${r.height}, ${r.video_duration.toFixed(1)} s)` : `failed: ${esc(Object.entries(r.checks).filter(([, v]) => !v).map(([k]) => k).join(', '))}`) : ''}</td></tr>`; }).join('')}
    </tbody></table>
    ${plan?.repurpose ? `<h3>Publishing drafts</h3><p class="meta">${esc(plan.repurpose.note)}</p>
      <h3>Titles</h3>${plan.repurpose.titles.map((t) => `<p>${esc(t)}</p>`).join('')}
      <h3>Description</h3><p style="white-space:pre-wrap">${esc(plan.repurpose.description)}</p>
      <h3>Thumbnail ideas</h3>${plan.repurpose.thumbnail_concepts.map((t) => `<p>${esc(t)}</p>`).join('')}` : ''}
    <p class="hint">Nothing is ever published automatically.</p>`
    : '<p>Rendered videos, caption files and chapter lists appear here.</p>';
}

// ---------------------------------------------------------------- actions
async function revise(body) {
  try {
    const r = await api(`/api/projects/${state.pid}/revise`, {method: 'POST', body});
    $('#reviseMsg').textContent = r.understood
      ? `Updated the plan (v${r.version}). Make a preview to see it.`
      : "I couldn't turn that into a change here. Ask Claude in VS Code, or try wording like \"make the captions bigger\".";
    await refresh();
  } catch (e) { $('#reviseMsg').textContent = e.message; }
}
$('#reviseForm').onsubmit = (e) => {
  e.preventDefault();
  const text = $('#reviseText').value.trim();
  if (!text) return;
  revise({request: text, at: sourceTime()});
  $('#reviseText').value = '';
};
$('#approveBtn').onclick = async () => { await api(`/api/projects/${state.pid}/approve`, {method: 'POST'}); refresh(); };
$('#previewBtn').onclick = () => render('preview', state.data.plan?.mode === 'shorts' && state.data.plan?.clips?.length ? 'shorts' : 'main');
$('#renderBtn').onclick = () => render('final', 'main');
async function render(quality, what) {
  try {
    const job = await api(`/api/projects/${state.pid}/render`, {method: 'POST', body: {quality, what}});
    state.activeJobs.add(job.id);
    pollJobs();
  } catch (e) { $('#reviseMsg').textContent = e.message; }
}

// ---------------------------------------------------------------- jobs (real progress)
async function pollJobs() {
  clearTimeout(state.jobsTimer);
  if (!state.pid) return;
  const list = (await api(`/api/jobs?project=${encodeURIComponent(state.data?.project?.id || state.pid)}`)).slice(0, 4);
  const label = {plan: 'Transcribing and planning', 'render-main-preview': 'Preview', 'render-main-final': 'Final render',
    'render-shorts-preview': 'Shorts preview', 'render-shorts-final': 'Shorts render'};
  $('#jobs').innerHTML = list.map((j) => `<div class="job" data-s="${esc(j.status)}"><div class="top">
      <span>${esc(label[j.kind] || j.kind)}: ${esc(j.status === 'running' ? `${j.stage} ${(j.progress * 100).toFixed(0)}%` : j.message)}</span>
      ${j.status === 'running' || j.status === 'queued' ? `<button data-cancel="${esc(j.id)}">Cancel</button>` : ''}
      ${['failed', 'interrupted', 'cancelled'].includes(j.status) ? `<button data-retry="${esc(j.id)}">Retry</button>` : ''}</div>
      <div class="bar"><i style="width:${(j.status === 'done' ? 1 : j.progress) * 100}%"></i></div>
      ${j.error ? `<p class="err">${esc(j.error)}</p>` : ''}</div>`).join('');
  let changed = false;
  for (const j of list) {
    if (state.activeJobs.has(j.id) && !['running', 'queued'].includes(j.status)) { state.activeJobs.delete(j.id); changed = true; }
  }
  if (changed) await refresh();
  const busy = list.some((j) => ['running', 'queued'].includes(j.status));
  state.jobsTimer = setTimeout(pollJobs, busy ? 1200 : 5000);
}
$('#jobs').onclick = async (e) => {
  const c = e.target.dataset.cancel, r = e.target.dataset.retry;
  if (c) await api(`/api/jobs/${c}/cancel`, {method: 'POST'});
  if (r) { try { const j = await api(`/api/jobs/${r}/retry`, {method: 'POST'}); state.activeJobs.add(j.id); } catch (err) { $('#reviseMsg').textContent = err.message; } }
  pollJobs();
};

// ---------------------------------------------------------------- new video
async function fillBrands(sel) {
  const bs = await api('/api/brands');
  sel.innerHTML = '<option value="">No brand yet</option>' + bs.map((b) => `<option value="${esc(b.slug)}">${esc(b.name)}</option>`).join('');
}
const openNew = async () => { await fillBrands($('#brandInput')); $('#newMsg').textContent = ''; $('#newDialog').showModal(); };
$('#newBtn').onclick = openNew;
$('#emptyNew').onclick = openNew;
const drop = $('#drop');
['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', (e) => { $('#fileInput').files = e.dataTransfer.files; $('#dropText').textContent = e.dataTransfer.files[0]?.name || ''; });
$('#fileInput').onchange = () => { $('#dropText').textContent = $('#fileInput').files[0]?.name || ''; };
$('#newForm').onsubmit = async (e) => {
  if (e.submitter?.value === 'cancel') return;
  e.preventDefault();
  const fd = new FormData();
  const f = $('#fileInput').files[0];
  if (f) fd.append('file', f); else fd.append('path', $('#pathInput').value);
  fd.append('mode', $('#modeInput').value);
  fd.append('brand', $('#brandInput').value);
  $('#createBtn').disabled = true;
  $('#newMsg').textContent = f ? 'Copying the video into the studio...' : 'Importing...';
  try {
    const p = await api('/api/projects', {method: 'POST', body: fd});
    const [mn, mx] = $('#shortLen').value.split(',').map(Number);
    $('#newDialog').close();
    await openProject(p.id);
    await startPlan({mode: $('#modeInput').value, shorts_count: +$('#shortsCount').value, short_min: mn, short_max: mx});
  } catch (err) { $('#newMsg').textContent = err.message; }
  $('#createBtn').disabled = false;
};

// ---------------------------------------------------------------- brands (one question at a time)
async function showBrands(active) {
  const bs = await api('/api/brands');
  $('#brandList').innerHTML = bs.length ? bs.map((b) => `<p><a class="tlink" data-slug="${esc(b.slug)}">${esc(b.name)}</a>
    <span class="meta">${b.complete ? 'complete' : 'setup in progress'}</span></p>`).join('') : '<p class="meta">No brands yet.</p>';
  if (active) askNext(active);
}
async function askNext(slug, next) {
  if (!next) next = (await api(`/api/brands/${slug}`)).next;
  $('#brandQ').innerHTML = next ? `<label>${esc(next[1])}<div class="row"><input id="brandAns"><button type="button" id="brandSave">Save</button>
    <button type="button" id="brandSkip">Skip</button></div></label>` : '<p>This brand profile is complete.</p>';
  if (!next) return;
  const save = async (value) => {
    try {
      const r = await api(`/api/brands/${slug}/answer`, {method: 'POST', body: {key: next[0], value}});
      askNext(slug, r.next);
      showBrands();
    } catch (e) { $('#brandQ').insertAdjacentHTML('beforeend', `<p class="err">${esc(e.message)}</p>`); }
  };
  $('#brandSave').onclick = () => save($('#brandAns').value);
  $('#brandSkip').onclick = () => save('skip');
  $('#brandAns').focus();
}
$('#brandsBtn').onclick = () => { showBrands(); $('#brandQ').innerHTML = ''; $('#brandDialog').showModal(); };
$('#brandList').onclick = (e) => { const a = e.target.closest('[data-slug]'); if (a) askNext(a.dataset.slug); };
$('#brandCreate').onclick = async () => {
  const name = $('#brandName').value.trim();
  if (!name) return;
  const r = await api('/api/brands', {method: 'POST', body: {name}});
  $('#brandName').value = '';
  showBrands();
  askNext(r.brand.slug, r.next);
};

// ---------------------------------------------------------------- start
loadProjects().then((list) => {
  const want = location.hash.slice(1);
  if (want && list.some((p) => p.id === want)) openProject(want);
});
