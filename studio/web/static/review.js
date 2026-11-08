// Send browser errors to the studio log so problems in your browser are visible to Claude.
window.addEventListener('error', (e) => {
  fetch('/api/clientlog', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page: location.pathname, msg: String(e.message), src: e.filename, line: e.lineno})}).catch(() => {});
});
window.addEventListener('unhandledrejection', (e) => {
  fetch('/api/clientlog', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page: location.pathname, msg: String(e.reason && e.reason.message || e.reason)})}).catch(() => {});
});
// Vibe Studio review screen: Frame.io-style review of rendered videos.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const api = async (url, opts = {}) => {
  const r = await fetch(url, opts.body ? {...opts, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(opts.body)} : opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
};
try { const t = localStorage.getItem('vs-theme'); if (t) document.documentElement.dataset.theme = t; } catch {}

const pid = decodeURIComponent(location.pathname.split('/').pop());
const params = new URLSearchParams(location.search);
const S = {assets: [], asset: null, version: null, comments: [], fps: 30, inPt: null, outPt: null,
  selected: null, tool: null, shapes: [], drawing: null, compare: false, replyTo: null};
const vA = $('#vA'), vB = $('#vB'), canvas = $('#draw'), ctx = canvas.getContext('2d');

// ------------------------------------------------------------ author identity (local)
let author = '';
try { author = localStorage.getItem('vs-author') || ''; } catch {}
// Inline name field (no pop-ups: browsers inside VS Code block prompt/confirm dialogs)
const setWho = () => {
  $('#who').innerHTML = `<label class="rv-name">Your name <input id="authorInput" value="${esc(author)}" placeholder="e.g. Jonathan" maxlength="40"></label>`;
  $('#authorInput').addEventListener('input', (e) => {
    author = e.target.value.trim();
    try { localStorage.setItem('vs-author', author); } catch {}
  });
};
setWho();
const COLORS = ['#e8a33d', '#4f8cf7', '#6fbf8e', '#c2564b', '#a774e8', '#3fb6c4', '#e86fb0'];
const colorFor = (name) => COLORS[[...String(name)].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORS.length];
const initial = (name) => String(name || '?').trim().charAt(0).toUpperCase();

// ------------------------------------------------------------ timecode
const tc = (t) => {
  t = Math.max(0, t || 0);
  const f = Math.floor((t % 1) * S.fps + 1e-6), s = Math.floor(t) % 60, m = Math.floor(t / 60) % 60, h = Math.floor(t / 3600);
  return [h, m, s, f].map((n) => String(n).padStart(2, '0')).join(':');
};
const ago = (stamp) => {
  const d = (Date.now() - new Date(stamp.replace(' ', 'T')).getTime()) / 1000;
  if (!isFinite(d)) return '';
  if (d < 60) return 'just now';
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return stamp.slice(0, 10);
};

// ------------------------------------------------------------ load
async function load() {
  S.assets = await api(`/api/projects/${encodeURIComponent(pid)}/assets`);
  $('#backLink').href = `/#${pid}`;
  if (!S.assets.length) {
    $('#assetName').textContent = 'Nothing rendered yet - make a preview first';
    return;
  }
  renderAssetList();
  const want = params.get('file');
  openAsset(S.assets.find((a) => a.file === want) || S.assets.find((a) => a.kind === 'main') || S.assets[0], params.get('v'));
}

function renderPicker() {
  const sel = $('#assetSel');
  sel.innerHTML = S.assets.map((a, i) => `<option value="${i}">${esc(a.name)}${a.open_comments ? ` (${a.open_comments} open)` : ''}</option>`).join('');
  sel.value = String(S.assets.findIndex((a) => S.asset && a.file === S.asset.file));
  $('#prevAsset').disabled = sel.value === '0';
  $('#nextAsset').disabled = sel.value === String(S.assets.length - 1);
}
const goAsset = (delta) => {
  const i = S.assets.findIndex((a) => a.file === S.asset.file) + delta;
  if (i >= 0 && i < S.assets.length) openAsset(S.assets[i]);
};
$('#assetSel').onchange = () => openAsset(S.assets[+$('#assetSel').value]);
$('#prevAsset').onclick = () => goAsset(-1);
$('#nextAsset').onclick = () => goAsset(1);

function renderAssetList() {
  renderPicker();
  const groups = [['Full videos', S.assets.filter((a) => a.kind === 'main')], ['Shorts', S.assets.filter((a) => a.kind === 'short')]];
  const label = {needs_review: 'Needs review', in_progress: 'In progress', changes_requested: 'Changes requested', approved: 'Approved'};
  $('#assetList').innerHTML = groups.filter(([, l]) => l.length).map(([g, list]) => `<h3>${g}</h3>` + list.map((a) => `
    <a href="?file=${encodeURIComponent(a.file)}" data-file="${esc(a.file)}" ${S.asset && a.file === S.asset.file ? 'aria-current="true"' : ''}>
      ${esc(a.name)}<small><span class="dot" data-s="${esc(a.status.status)}"></span>${label[a.status.status]}
      - v${a.versions.length}${a.open_comments ? ` - ${a.open_comments} open` : ''}</small></a>`).join('')).join('');
}
$('#assetList').onclick = (e) => {
  const a = e.target.closest('a[data-file]');
  if (!a) return;
  e.preventDefault();
  openAsset(S.assets.find((x) => x.file === a.dataset.file));
};

function openAsset(asset, v) {
  S.asset = asset;
  S.fps = Math.round(asset.fps || 30);
  $('#assetName').textContent = asset.name;
  const opts = asset.versions.slice().reverse().map((x) => `<option value="${x.v}">v${x.v}${x.current ? ' (latest)' : ''} - ${esc((x.created || '').slice(5, 16))}</option>`).join('');
  $('#versionSel').innerHTML = opts;
  $('#versionSelB').innerHTML = opts;
  $('#compareBtn').disabled = asset.versions.length < 2;
  $('#compareBtn').title = asset.versions.length < 2 ? 'Appears once this video has been rendered more than once' : '';
  const ver = asset.versions.find((x) => String(x.v) === String(v)) || asset.versions[asset.versions.length - 1];
  $('#versionSel').value = ver.v;
  if (asset.versions.length > 1) $('#versionSelB').value = asset.versions[asset.versions.length - 2].v;
  $('#statusSel').value = asset.status.status;
  $('#statusSel').dataset.s = asset.status.status;
  setVersion(ver);
  renderAssetList();
  history.replaceState(null, '', `?file=${encodeURIComponent(asset.file)}&v=${ver.v}`);
}

const mediaUrl = (file) => `/media/${encodeURIComponent(pid)}/exports/${file.split('/').map(encodeURIComponent).join('/')}`;
// playback uses a copy with Opus audio so sound works in every browser (incl. VS Code's); downloads keep the original
const playUrl = (file) => `/media/${encodeURIComponent(pid)}/play/${file.split('/').map(encodeURIComponent).join('/')}`;
function setVersion(ver) {
  S.version = ver;
  vA.src = playUrl(ver.file);
  $('#downloadLink').href = mediaUrl(ver.file);
  $('#capA').textContent = S.compare ? `v${ver.v}` : '';
  if (S.compare) setB();
  S.selected = null;
  S.shapes = [];
  loadComments();
}
$('#versionSel').onchange = () => setVersion(S.asset.versions.find((x) => String(x.v) === $('#versionSel').value));
function setB() {
  const ver = S.asset.versions.find((x) => String(x.v) === $('#versionSelB').value);
  vB.src = playUrl(ver.file);
  vB.currentTime = vA.currentTime;
}
$('#versionSelB').onchange = setB;
$('#compareBtn').onclick = () => {
  S.compare = !S.compare;
  $('#compareBtn').setAttribute('aria-pressed', S.compare);
  $('#pB').hidden = !S.compare;
  $('#capA').textContent = S.compare ? `v${S.version.v}` : '';
  if (S.compare) setB(); else vB.pause();
  resizeCanvas();
};
$('#statusSel').onchange = async () => {
  const s = $('#statusSel').value;
  await api(`/api/projects/${encodeURIComponent(pid)}/assets/status`, {method: 'POST', body: {file: S.asset.file, status: s, author}});
  S.asset.status = {status: s};
  $('#statusSel').dataset.s = s;
  renderAssetList();
};

// ------------------------------------------------------------ playback
const syncB = () => { if (S.compare && Math.abs(vB.currentTime - vA.currentTime) > 0.08) vB.currentTime = vA.currentTime; };
const play = () => { vA.play(); if (S.compare) { syncB(); vB.play(); } };
const pause = () => { vA.pause(); if (S.compare) { vB.pause(); syncB(); } };
const toggle = () => (vA.paused ? play() : pause());
const seek = (t) => { vA.currentTime = Math.max(0, Math.min(vA.duration || 0, t)); syncB(); };
const step = (frames) => { pause(); seek(vA.currentTime + frames / S.fps); };
$('#playBtn').onclick = toggle;
$('#backFrame').onclick = () => step(-1);
$('#fwdFrame').onclick = () => step(1);
$('#rate').onchange = () => { vA.playbackRate = vB.playbackRate = parseFloat($('#rate').value); };
$('#vol').oninput = () => { vA.volume = parseFloat($('#vol').value); };
$('#fsBtn').onclick = () => $('#players').requestFullscreen?.();
$('#keysBtn').onclick = () => { $('#keysHelp').hidden = !$('#keysHelp').hidden; };
vB.addEventListener('loadedmetadata', () => { vB.currentTime = vA.currentTime; vB.playbackRate = vA.playbackRate; if (!vA.paused) vB.play(); });
vA.addEventListener('seeked', syncB);
vA.addEventListener('play', () => { $('#playBtn').textContent = 'Pause'; clearDrawing(); });
vA.addEventListener('pause', () => { $('#playBtn').textContent = 'Play'; });
vA.addEventListener('loadedmetadata', () => { $('#dur').textContent = tc(vA.duration); renderMarkers(); resizeCanvas(); });
vA.addEventListener('progress', () => {
  if (vA.buffered.length && vA.duration) $('#buffer').style.width = `${(vA.buffered.end(vA.buffered.length - 1) / vA.duration) * 100}%`;
});
const tick = () => {
  const t = vA.currentTime;
  $('#tc').textContent = tc(t);
  if (vA.duration) $('#played').style.width = `${(t / vA.duration) * 100}%`;
  if (S.inPt == null && document.activeElement !== $('#cText')) $('#tcChip').textContent = tc(t);
  if (!S.tool && !S.selected) showAnnotationsAt(t);
  if (S.compare && !vA.paused) syncB();
  requestAnimationFrame(tick);
};
requestAnimationFrame(tick);

// scrub bar with markers
const scrubTime = (e) => { const r = $('#scrub').getBoundingClientRect(); return ((e.clientX - r.left) / r.width) * (vA.duration || 0); };
let scrubbing = false;
$('#scrub').addEventListener('pointerdown', (e) => {
  if (e.target.closest('.rv-mark')) return;
  scrubbing = true; $('#scrub').setPointerCapture(e.pointerId); seek(scrubTime(e));
});
$('#scrub').addEventListener('pointermove', (e) => {
  if (scrubbing) seek(scrubTime(e));
  const tip = $('#hoverTip'), m = e.target.closest('.rv-mark');
  tip.hidden = false;
  tip.style.left = `${e.clientX - $('#scrub').getBoundingClientRect().left}px`;
  tip.textContent = m ? m.title : tc(scrubTime(e));
});
$('#scrub').addEventListener('pointerup', () => { scrubbing = false; });
$('#scrub').addEventListener('pointerleave', () => { $('#hoverTip').hidden = true; });
$('#scrub').addEventListener('click', (e) => { const m = e.target.closest('.rv-mark'); if (m) selectComment(m.dataset.id); });

function renderMarkers() {
  const d = vA.duration || 1;
  const tops = S.comments.filter((c) => !c.parent);
  $('#markers').innerHTML = tops.map((c) => {
    const col = colorFor(c.author);
    const range = c.end ? `<div class="rv-mark-range" style="left:${(c.at / d) * 100}%;width:${((c.end - c.at) / d) * 100}%;background:${col}"></div>` : '';
    return `${range}<div class="rv-mark ${c.status !== 'open' ? 'done' : ''}" data-id="${esc(c.id)}" title="${esc(c.author)}: ${esc(c.text)}"
      style="left:${(c.at / d) * 100}%;background:${col}">${esc(initial(c.author))}</div>`;
  }).join('');
}

// ------------------------------------------------------------ comments
async function loadComments() {
  const all = await api(`/api/projects/${encodeURIComponent(pid)}/comments`);
  S.comments = all.filter((c) => c.file === S.version.file);
  renderComments();
  renderMarkers();
}
function renderComments() {
  const f = $('#cFilter').value;
  const tops = S.comments.filter((c) => !c.parent).sort((a, b) => a.at - b.at);
  const shown = tops.filter((c) => f === 'all' || (f === 'open' ? c.status === 'open' : c.status !== 'open'));
  $('#cCount').textContent = `${tops.filter((c) => c.status === 'open').length} open`;
  const replies = (id) => S.comments.filter((c) => c.parent === id).sort((a, b) => a.created.localeCompare(b.created));
  $('#cList').innerHTML = shown.length ? shown.map((c) => `
    <li class="rv-c ${c.status !== 'open' ? 'done' : ''} ${S.selected === c.id ? 'sel' : ''}" data-id="${esc(c.id)}">
      <div class="rv-chead"><span class="avatar" style="background:${colorFor(c.author)}">${esc(initial(c.author))}</span>
        <b>${esc(c.author)}</b><span class="when">${tc(c.at)}${c.end ? ` - ${tc(c.end)}` : ''}</span>
        ${c.annotation ? '<span class="rv-tag">drawing</span>' : ''}<span class="ago">${esc(ago(c.created))}</span></div>
      <p class="rv-ctext">${esc(c.text)}</p>
      ${c.resolution ? `<p class="rv-res">${esc(c.resolution)}</p>` : ''}
      ${replies(c.id).length ? `<ul class="rv-replies">${replies(c.id).map((r) => `<li>
        <div class="rv-chead"><span class="avatar" style="background:${colorFor(r.author)}">${esc(initial(r.author))}</span>
        <b>${esc(r.author)}</b><span class="ago">${esc(ago(r.created))}</span></div><p class="rv-ctext">${esc(r.text)}</p></li>`).join('')}</ul>` : ''}
      <div class="rv-cfoot">
        <label><input type="checkbox" class="toggle" data-done="${esc(c.id)}" ${c.status !== 'open' ? 'checked' : ''}> Done</label>
        <button type="button" data-reply="${esc(c.id)}">Reply</button>
        <button type="button" data-del="${esc(c.id)}">Delete</button>
      </div>
      ${S.replyTo === c.id ? `<div class="rv-reply-box"><input id="replyText" placeholder="Reply"><button type="button" class="primary" data-sendreply="${esc(c.id)}">Send</button></div>` : ''}
    </li>`).join('') : `<li class="meta" style="padding:1rem .5rem">${f === 'open' ? 'No open comments. Pause anywhere and write one below.' : 'Nothing here.'}</li>`;
  if (S.replyTo) $('#replyText')?.focus();
}
$('#cFilter').onchange = renderComments;
function selectComment(id) {
  const c = S.comments.find((x) => x.id === id);
  if (!c) return;
  S.selected = id;
  pause();
  seek(c.at);
  drawShapes(c.annotation || []);
  renderComments();
  document.querySelector(`.rv-c[data-id="${id}"]`)?.scrollIntoView({block: 'nearest'});
}
$('#cList').onclick = async (e) => {
  const t = e.target;
  const base = `/api/projects/${encodeURIComponent(pid)}/comments`;
  if (t.dataset.reply) { S.replyTo = S.replyTo === t.dataset.reply ? null : t.dataset.reply; renderComments(); return; }
  if (t.dataset.sendreply) {
    const text = $('#replyText').value.trim();
    if (!text) return;
    const c = S.comments.find((x) => x.id === t.dataset.sendreply);
    await api(base, {method: 'POST', body: {text, at: c.at, file: S.version.file, author, parent: c.id}});
    S.replyTo = null; await loadComments(); return;
  }
  if (t.dataset.del) {
    if (t.dataset.armed !== '1') {  // two-step delete instead of a confirm() pop-up
      t.dataset.armed = '1'; t.textContent = 'Click again to delete';
      setTimeout(() => { t.dataset.armed = ''; t.textContent = 'Delete'; }, 3000);
      return;
    }
    await api(`${base}/${t.dataset.del}`, {method: 'POST', body: {action: 'delete'}}); await loadComments(); return;
  }
  if (t.dataset.done !== undefined && t.matches('input')) {
    await api(`${base}/${t.dataset.done}`, {method: 'POST', body: {status: t.checked ? 'resolved' : 'open', resolution: t.checked ? `Marked done by ${author || 'you'}` : null}});
    await loadComments(); return;
  }
  if (t.closest('button, input, label')) return;
  const li = t.closest('.rv-c');
  if (li) selectComment(li.dataset.id);
};
$('#cList').addEventListener('keydown', (e) => {
  if (e.target.id === 'replyText' && e.key === 'Enter') { e.preventDefault(); document.querySelector('[data-sendreply]')?.click(); }
});

// composer
$('#cText').addEventListener('focus', () => { pause(); if (S.inPt == null) $('#tcChip').textContent = tc(vA.currentTime); });
$('#cText').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#composer').requestSubmit(); }
  if (e.key === 'Escape') { e.target.blur(); }
});
const say = (msg, ok = false) => { const m = $('#cMsg'); m.textContent = msg; m.classList.toggle('ok', ok); if (ok) setTimeout(() => { if (m.textContent === msg) m.textContent = ''; }, 3000); };
$('#composer').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('#cText').value.trim();
  if (!text) { say('Type your comment first, then press Comment.'); $('#cText').focus(); return; }
  if (!author) author = 'you';
  const at = S.inPt ?? vA.currentTime;
  const end = S.outPt != null && S.outPt > at ? S.outPt : null;
  try {
    await api(`/api/projects/${encodeURIComponent(pid)}/comments`, {method: 'POST',
      body: {text, at, end, file: S.version.file, author, annotation: S.shapes.length ? S.shapes : null}});
  } catch (err) { say(`Couldn't save: ${err.message}`); return; }
  say(`Comment saved at ${tc(at)}.`, true);
  $('#cText').value = '';
  clearRange(); clearDrawing(); setTool(null);
  await loadComments();
  S.assets = await api(`/api/projects/${encodeURIComponent(pid)}/assets`);
  renderAssetList();
};
$('#tcChip').onclick = () => { if (S.inPt != null) clearRange(); else seek(vA.currentTime); };

// ranges (I / O)
function showRange() {
  const d = vA.duration || 1, r = $('#rangeSel');
  if (S.inPt == null) { r.hidden = true; return; }
  const end = S.outPt ?? S.inPt;
  r.hidden = false;
  r.style.left = `${(S.inPt / d) * 100}%`;
  r.style.width = `${Math.max(0.3, ((end - S.inPt) / d) * 100)}%`;
  $('#tcChip').textContent = `${tc(S.inPt)}${S.outPt != null ? ` - ${tc(S.outPt)}` : ''}`;
}
function clearRange() { S.inPt = S.outPt = null; showRange(); $('#tcChip').textContent = tc(vA.currentTime); }

// ------------------------------------------------------------ drawing
function videoBox() {
  // the video's visible picture inside the letterboxed frame
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const vw = vA.videoWidth || 16, vh = vA.videoHeight || 9;
  const s = Math.min(W / vw, H / vh);
  return {x: (W - vw * s) / 2, y: (H - vh * s) / 2, w: vw * s, h: vh * s};
}
function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (S.selected) drawShapes(S.comments.find((c) => c.id === S.selected)?.annotation || []);
  else drawShapes(S.shapes);
}
window.addEventListener('resize', resizeCanvas);
function drawShapes(shapes) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const b = videoBox();
  for (const sh of shapes) {
    const pts = sh.points.map(([x, y]) => [b.x + x * b.w, b.y + y * b.h]);
    ctx.strokeStyle = sh.color; ctx.lineWidth = Math.max(3, b.w / 300); ctx.lineCap = ctx.lineJoin = 'round';
    ctx.shadowColor = 'rgba(0,0,0,.5)'; ctx.shadowBlur = 4;
    ctx.beginPath();
    if (sh.type === 'rect') {
      const [a, z] = [pts[0], pts[pts.length - 1]];
      ctx.strokeRect(a[0], a[1], z[0] - a[0], z[1] - a[1]);
    } else {
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.stroke();
      if (sh.type === 'arrow' && pts.length > 1) {
        const [x1, y1] = pts[0], [x2, y2] = pts[pts.length - 1], ang = Math.atan2(y2 - y1, x2 - x1), L = ctx.lineWidth * 5;
        ctx.beginPath();
        ctx.moveTo(x2, y2); ctx.lineTo(x2 - L * Math.cos(ang - 0.45), y2 - L * Math.sin(ang - 0.45));
        ctx.moveTo(x2, y2); ctx.lineTo(x2 - L * Math.cos(ang + 0.45), y2 - L * Math.sin(ang + 0.45));
        ctx.stroke();
      }
    }
  }
}
function showAnnotationsAt(t) {
  if (!vA.paused) { if (S._shown) { ctx.clearRect(0, 0, canvas.width, canvas.height); S._shown = false; } return; }
  const hit = S.comments.find((c) => c.annotation && Math.abs(c.at - t) < 0.5 / S.fps + 0.02);
  const key = hit ? hit.id : null;
  if (key !== S._shownKey) { drawShapes(hit ? hit.annotation : S.shapes); S._shownKey = key; S._shown = !!hit; }
}
function clearDrawing() { S.shapes = []; S.selected = null; S._shownKey = undefined; ctx.clearRect(0, 0, canvas.width, canvas.height); }
function setTool(tool) {
  S.tool = S.tool === tool ? null : tool;
  document.querySelectorAll('[data-tool]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.tool === S.tool));
  canvas.classList.toggle('active', !!S.tool);
  if (S.tool) { pause(); S.selected = null; drawShapes(S.shapes); }
}
document.querySelectorAll('[data-tool]').forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
$('#clearDraw').onclick = () => { S.shapes = []; drawShapes([]); };
const norm = (e) => {
  const r = canvas.getBoundingClientRect(), b = videoBox();
  return [Math.min(1, Math.max(0, (e.clientX - r.left - b.x) / b.w)), Math.min(1, Math.max(0, (e.clientY - r.top - b.y) / b.h))];
};
canvas.addEventListener('pointerdown', (e) => {
  if (!S.tool) return;
  canvas.setPointerCapture(e.pointerId);
  S.drawing = {type: S.tool, color: $('#penColor').value, points: [norm(e)]};
  S.shapes.push(S.drawing);
});
canvas.addEventListener('pointermove', (e) => {
  if (!S.drawing) return;
  const p = norm(e);
  if (S.drawing.type === 'pen') S.drawing.points.push(p); else S.drawing.points[1] = p;
  drawShapes(S.shapes);
});
canvas.addEventListener('pointerup', () => {
  if (S.drawing && S.drawing.points.length < 2) S.shapes.pop();
  S.drawing = null;
  $('#cText').focus();
});

// ------------------------------------------------------------ keyboard
document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea, select')) return;
  const k = e.key.toLowerCase();
  if (k === ' ' || k === 'k') { e.preventDefault(); toggle(); }
  else if (k === 'j') seek(vA.currentTime - 1);
  else if (k === 'l') seek(vA.currentTime + 1);
  else if (k === 'arrowleft') { e.preventDefault(); e.shiftKey ? seek(vA.currentTime - 1) : step(-1); }
  else if (k === 'arrowright') { e.preventDefault(); e.shiftKey ? seek(vA.currentTime + 1) : step(1); }
  else if (k === 'i') { S.inPt = vA.currentTime; if (S.outPt != null && S.outPt <= S.inPt) S.outPt = null; showRange(); }
  else if (k === 'o') { if (S.inPt == null) S.inPt = 0; S.outPt = vA.currentTime > S.inPt ? vA.currentTime : null; showRange(); }
  else if (k === 'c') { e.preventDefault(); $('#cText').focus(); }
  else if (k === 'd') setTool(S.tool ? null : 'pen');
  else if (k === '[') goAsset(-1);
  else if (k === ']') goAsset(1);
  else if (k === 'escape') { clearRange(); setTool(null); clearDrawing(); renderComments(); }
});

load().catch((err) => { $('#assetName').textContent = err.message; });
