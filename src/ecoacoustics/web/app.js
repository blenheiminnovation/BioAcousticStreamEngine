/* Bioacoustic Stream Engine — single-page frontend */

const MAX_FEED_ITEMS = 60;
const POLL_INTERVAL = 8000;

const CLASSIFIERS = [
  { key: 'all',    label: 'All',      icon: '◈' },
  { key: 'bird',   label: 'Birds',    icon: '🐦' },
  { key: 'bat',    label: 'Bats',     icon: '🦇' },
  { key: 'bee',    label: 'Bees',     icon: '🐝' },
  { key: 'insect', label: 'Insects',  icon: '🦗' },
  { key: 'soil',   label: 'Soil',     icon: '🌱' },
];

const state = {
  page: 'dashboard',
  status: null,
  detections: [],
  classifierFilter: 'all',
  connected: true,
  gallery: {},  // key: species_common → { det, count, bestConf }
};

/* ── API ── */
const api = {
  async _request(path, opts = {}) {
    try {
      const r = await fetch(path, opts);
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || `Server error (${r.status})`);
      }
      return r.json();
    } catch (e) {
      if (e.name === 'TypeError') throw new Error('Cannot reach server — check that the web UI is still running.');
      throw e;
    }
  },
  get(path) { return this._request(path); },
  post(path, body = {}) {
    return this._request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },
  del(path) { return this._request(path, { method: 'DELETE' }); },
};

/* ── Toast ── */
function toast(msg, type = 'info', duration = 3500) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `show toast-${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = ''; }, duration);
}

/* ── Button loading ── */
function btnLoad(btn, label) { btn.dataset.loading = '1'; btn._orig = btn.textContent; btn.textContent = label; }
function btnDone(btn) { delete btn.dataset.loading; if (btn._orig) btn.textContent = btn._orig; }

/* ── Connection warning ── */
function setConnected(ok) {
  if (state.connected === ok) return;
  state.connected = ok;
  document.getElementById('conn-warning').classList.toggle('show', !ok);
}

/* ── Header ── */
function updateHeader(status) {
  if (!status) return;
  document.getElementById('version').textContent = `v${status.version}`;
  const pill = document.getElementById('status-pill');
  const lbl = document.getElementById('status-label');
  const running = Object.values(status.pipelines || {}).filter(p => p.state !== 'idle');
  if (running.length === 0) {
    pill.className = 'status-pill idle'; lbl.textContent = 'Idle';
  } else if (running.length === 1) {
    pill.className = `status-pill ${running[0].state}`;
    lbl.textContent = `${running[0].state === 'listening' ? 'Listening' : 'Scheduled'} — ${running[0].device_name}`;
  } else {
    pill.className = 'status-pill listening';
    lbl.textContent = `${running.length} devices active`;
  }
}

/* ── State banner ── */
function updateStateBanner(pipelines) {
  const banner = document.getElementById('state-banner');
  if (!banner) return;
  const running = Object.values(pipelines).filter(p => p.state !== 'idle');
  if (running.length === 0) {
    banner.className = 'state-banner';
    banner.querySelector('.banner-title').textContent = 'Ready to listen';
    banner.querySelector('.banner-sub').textContent = 'Select a device and start listening, or run the automated schedule.';
  } else if (running.length === 1) {
    const p = running[0];
    banner.className = `state-banner ${p.state}`;
    banner.querySelector('.banner-title').textContent = p.state === 'listening' ? '● Listening now' : '● Scheduled mode running';
    banner.querySelector('.banner-sub').textContent = `${p.device_name}  ·  Window: ${p.window || 'manual'}  ·  Started ${fmtTime(p.started_at)}`;
  } else {
    banner.className = 'state-banner listening';
    banner.querySelector('.banner-title').textContent = `● ${running.length} devices listening`;
    banner.querySelector('.banner-sub').textContent = running.map(p => p.device_name).join(', ');
  }
}

function fmtTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); } catch { return ''; }
}

/* ── Organism tabs ── */
function renderTabs(containerId) {
  const counts = {};
  CLASSIFIERS.forEach(c => counts[c.key] = 0);
  state.detections.forEach(d => {
    counts['all']++;
    if (counts[d.classifier] !== undefined) counts[d.classifier]++;
    else counts[d.classifier] = 1;
  });

  return `<div class="tabs" id="${containerId}">
    ${CLASSIFIERS.map(c => `
      <button class="tab ${state.classifierFilter === c.key ? 'active' : ''}"
              onclick="setFilter('${c.key}')">
        ${c.icon} ${c.label}
        <span class="tab-count">${counts[c.key] || 0}</span>
      </button>`).join('')}
  </div>`;
}

function setFilter(key) {
  state.classifierFilter = key;
  // Re-render tabs
  const tabsEl = document.getElementById('feed-tabs');
  if (tabsEl) tabsEl.outerHTML = renderTabs('feed-tabs');
  // Re-render feed
  const feed = document.getElementById('live-feed');
  if (feed) {
    const visible = state.classifierFilter === 'all'
      ? state.detections
      : state.detections.filter(d => d.classifier === state.classifierFilter);
    feed.innerHTML = visible.slice(0, MAX_FEED_ITEMS).map(detectionCard).join('');
  }
}

/* ── Router ── */
const router = {
  init() {
    window.addEventListener('hashchange', () => this.navigate(location.hash.slice(1) || 'dashboard'));
    document.querySelectorAll('nav a').forEach(a => {
      a.addEventListener('click', e => { e.preventDefault(); location.hash = a.getAttribute('href').slice(1); });
    });
    this.navigate(location.hash.slice(1) || 'dashboard');
  },
  navigate(page) {
    state.page = page;
    document.querySelectorAll('nav a').forEach(a =>
      a.classList.toggle('active', a.getAttribute('href') === `#${page}`)
    );
    ({ dashboard: renderDashboard, gallery: renderGallery, schedule: renderSchedule, clips: renderClips, reports: renderReports, settings: renderSettings }[page] || renderDashboard)();
  },
};

/* ── WebSocket ── */
const ws = {
  socket: null,
  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.socket = new WebSocket(`${proto}://${location.host}/ws`);
    this.socket.onmessage = e => { try { this.onMessage(JSON.parse(e.data)); } catch (_) {} };
    this.socket.onclose = () => setTimeout(() => this.connect(), 2000);
  },
  onMessage(data) {
    if (data.type === 'detection') {
      state.detections.unshift(data);
      if (state.detections.length > MAX_FEED_ITEMS) state.detections.pop();
      updateGallery(data);
      if (state.page === 'dashboard') prependDetection(data);
      const tabsEl = document.getElementById('feed-tabs');
      if (tabsEl) tabsEl.outerHTML = renderTabs('feed-tabs');
    } else if (data.type === 'audio_level') {
      updateVuMeter(data.db);
    } else if (data.type === 'pipeline_stopped') {
      resetVuMeter();
    }
  },
};

/* ── Status polling ── */
async function pollStatus() {
  try {
    state.status = await api.get('/api/status');
    setConnected(true);
    updateHeader(state.status);
    if (state.page === 'dashboard') {
      updateStateBanner(state.status.pipelines || {});
      // Update status-derived stat cards directly from what we already have
      const windowEl = document.getElementById('stat-window')?.querySelector('.value');
      if (windowEl) windowEl.textContent = state.status.schedule?.active_window || 'None';
      const diskEl = document.getElementById('stat-disk')?.querySelector('.value');
      if (diskEl) diskEl.textContent = state.status.disk_free_gb ?? '—';
      refreshDevicePanel();
      _refreshSummaryStats();
    }
  } catch (_) { setConnected(false); }
}

async function _refreshSummaryStats() {
  try {
    const summary = await api.get('/api/detections/summary');
    const speciesEl = document.getElementById('stat-species')?.querySelector('.value');
    const callsEl   = document.getElementById('stat-calls')?.querySelector('.value');
    if (speciesEl) speciesEl.textContent = summary.species_count ?? '—';
    if (callsEl)   callsEl.textContent   = summary.total_calls   ?? '—';
  } catch (_) {}
}

/* ─────────────────────────── DASHBOARD ─────────────────────────── */
function renderDashboard() {
  document.getElementById('main').innerHTML = `
    <div class="dashboard-layout">

      <div class="dashboard-main-col">
        <div class="grid-4">
          <div class="card stat" id="stat-species"><div class="value">—</div><div class="label">Species today</div></div>
          <div class="card stat" id="stat-calls"><div class="value">—</div><div class="label">Calls today</div></div>
          <div class="card stat" id="stat-window"><div class="value" style="font-size:1rem">—</div><div class="label">Active window</div></div>
          <div class="card stat" id="stat-disk"><div class="value">—</div><div class="label">Disk free (GB)</div></div>
        </div>

        <div class="card">
          <div class="card-title">Status</div>
          <div class="state-banner" id="state-banner">
            <div class="banner-dot"></div>
            <div class="banner-text">
              <div class="banner-title">Ready to listen</div>
              <div class="banner-sub">Select a device and start listening, or run the automated schedule.</div>
            </div>
          </div>
        </div>

        <div class="card">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div class="card-title" style="margin:0">Live Spectrogram ${helpBtn('spectrogram')}</div>
            <button class="btn btn-sm btn-outline" id="btn-spec-toggle" onclick="toggleSpectrogram()">■ Stop</button>
          </div>
          <div class="spec-panel show" id="spec-panel">
            <div class="spec-toolbar">
              <label>Mic</label>
              <select id="spec-device" onchange="changeSpecDevice()"><option value="">Default microphone</option></select>
              <label><input type="checkbox" id="spec-log" style="accent-color:var(--primary)"> Log scale</label>
            </div>
            <div class="spec-wrap">
              <canvas id="spec-canvas" width="1200" height="220"></canvas>
              <div class="spec-freq-axis" id="spec-axis"></div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Recording Devices</div>
          <div id="device-panel"><div class="empty">Loading devices...</div></div>
        </div>
      </div>

      <div class="dashboard-feed-col">
        <div class="card dashboard-feed-card">
          <div class="card-title">Live Detections ${helpBtn('live_detections')}</div>
          <div class="vu-meter" id="vu-meter">
            <span class="vu-label">🎙 Audio in ${helpBtn('vu_meter')}</span>
            <div class="vu-bar-wrap"><div class="vu-bar" id="vu-bar"></div></div>
            <span class="vu-db" id="vu-db"><span class="vu-no-signal">no signal</span></span>
          </div>
          ${renderTabs('feed-tabs')}
          <div class="feed" id="live-feed"></div>
        </div>
      </div>

    </div>

  `;

  refreshDashboard();
  _populateSpecDevices().then(() => _startSpectrogram());
}

async function refreshDashboard() {
  if (state.page !== 'dashboard') return;
  await pollStatus();
}

async function refreshDevicePanel() {
  const panel = document.getElementById('device-panel');
  if (!panel) return;
  try {
    const [devData, statusData] = await Promise.all([
      api.get('/api/devices'),
      state.status ? Promise.resolve(state.status) : api.get('/api/status'),
    ]);
    const pipelines = statusData.pipelines || {};

    if (!devData.devices.length) {
      panel.innerHTML = '<div class="empty">No audio input devices found. Check that a microphone is connected.</div>';
      return;
    }

    panel.innerHTML = `<div class="device-grid">${devData.devices.map(d => {
      // Use the source name as the pipeline key so each physical mic gets its own slot
      const key = d.is_default ? 'default' : `src_${d.index}`;
      const pip = pipelines[key];
      const isRunning = pip && pip.state !== 'idle';
      const safeLabel = (d.label || d.name).replace(/'/g, '');
      const hz = (d.sample_rate / 1000).toFixed(1);
      const stateTag = d.state === 'RUNNING' ? '<span style="color:var(--primary)">● active</span>'
                     : d.state === 'SUSPENDED' ? '<span style="color:var(--muted)">○ suspended</span>'
                     : '';
      return `
        <div class="device-row ${isRunning ? 'running' : ''}">
          <div class="device-info">
            <div class="device-name">${d.is_default ? '★ ' : ''}${d.label || d.name}</div>
            <div class="device-meta">${d.channels}ch · ${hz}kHz · ${stateTag}</div>
          </div>
          <div class="device-status ${isRunning ? 'running' : 'idle'}">
            ${isRunning ? `● ${pip.state} — ${pip.window || ''}` : '○ Idle'}
          </div>
          <div class="device-actions">
            ${isRunning
              ? `<button class="btn btn-sm btn-danger" onclick="stopDevice('${key}', this)">■ Stop</button>`
              : `<select id="mode-${d.index}">
                   <option value="wake">Listen now</option>
                   <option value="schedule">Schedule</option>
                 </select>
                 <input type="number" placeholder="∞ min" min="1" max="1440"
                   style="width:70px;padding:5px 8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:0.78rem"
                   id="dur-${d.index}">
                 <button class="btn btn-sm btn-primary"
                   onclick="startDevice('${key}','${safeLabel}',${d.index},this)">▶ Start</button>`
            }
          </div>
        </div>`;
    }).join('')}</div>`;
  } catch (err) {
    panel.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`;
  }
}

async function startDevice(deviceKey, deviceName, deviceIndex, btn) {
  const modeEl = document.getElementById(`mode-${deviceIndex}`);
  const durEl = document.getElementById(`dur-${deviceIndex}`);
  const mode = modeEl ? modeEl.value : 'wake';
  const dur = durEl ? parseInt(durEl.value) || null : null;
  btnLoad(btn, '⟳');
  try {
    // device_index null = use system default (correct routing via PipeWire)
    const params = new URLSearchParams({ device_key: deviceKey, device_name: deviceName });
    if (deviceIndex !== null) params.set('device_index', deviceIndex);
    if (mode === 'wake') {
      if (dur) params.set('duration_minutes', dur);
      await api.post(`/api/pipeline/wake?${params}`);
    } else {
      await api.post(`/api/pipeline/schedule?${params}`);
    }
    toast(`Started — ${deviceName}`, 'success', 5000);
    await pollStatus();
    _syncSpecToRunningDevice();
  } catch (err) {
    toast(err.message, 'error', 6000);
    btnDone(btn);
  }
}

async function stopDevice(deviceKey, btn) {
  btnLoad(btn, '⟳');
  try {
    await api.post(`/api/pipeline/stop?device_key=${deviceKey}`);
    toast('Device stopped', 'warn', 5000);
    await pollStatus();
  } catch (err) {
    toast(err.message, 'error', 6000);
    btnDone(btn);
  }
}

let _vuResetTimer = null;

function updateVuMeter(db) {
  const bar = document.getElementById('vu-bar');
  const label = document.getElementById('vu-db');
  if (!bar || !label) return;
  // Map -60dB→0% to 0dB→100%
  const pct = Math.max(0, Math.min(100, (db + 60) / 60 * 100));
  bar.style.width = pct + '%';
  bar.className = 'vu-bar' + (pct > 85 ? ' high' : pct > 65 ? ' mid' : '');
  label.textContent = db.toFixed(1) + ' dB';
  // Reset to "no signal" if no update arrives within 3 seconds
  if (_vuResetTimer) clearTimeout(_vuResetTimer);
  _vuResetTimer = setTimeout(resetVuMeter, 3000);
}

function resetVuMeter() {
  if (_vuResetTimer) { clearTimeout(_vuResetTimer); _vuResetTimer = null; }
  const bar = document.getElementById('vu-bar');
  const label = document.getElementById('vu-db');
  if (!bar || !label) return;
  bar.style.width = '0%';
  bar.className = 'vu-bar';
  label.innerHTML = '<span class="vu-no-signal">no signal</span>';
}

function prependDetection(det) {
  const feed = document.getElementById('live-feed');
  if (!feed) return;
  if (state.classifierFilter !== 'all' && det.classifier !== state.classifierFilter) return;
  feed.insertAdjacentHTML('afterbegin', detectionCard(det));
  while (feed.children.length > MAX_FEED_ITEMS) feed.lastChild.remove();
}

function confClass(c) { return c >= 0.75 ? 'conf-high' : c >= 0.5 ? 'conf-mid' : 'conf-low'; }

/* ── Species gallery ── */

// Credits cache: filename → { author, license, license_url, source_url }
let _galleryCredits = {};
let _galleryMinConf = 0;   // 0–1 fraction; persists across live updates and re-renders

function _galleryFilterLabel(pct) {
  return pct === 0 ? 'Any' : `${pct}%+`;
}

async function _loadGalleryCredits() {
  try {
    const data = await api.get('/api/gallery');
    _galleryCredits = {};
    for (const img of data.images) _galleryCredits[img.filename] = img;
  } catch (_) {}
}

function _galleryItemId(species) {
  return 'gi_' + species.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '');
}

function _speciesKey(name) {
  // Matches the Python normalize() and JS must stay in sync.
  // Apostrophes are stripped so "Roesel's" → "roesels" not "roesel_s".
  return name.toLowerCase().replace(/'/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '');
}

function _speciesImageUrl(name) {
  return `/species_images/${_speciesKey(name)}.jpg`;
}

function _creditLine(name) {
  const key  = _speciesKey(name);
  const info = _galleryCredits[key + '.jpg'] || _galleryCredits[key + '.png'] || null;
  if (!info || !info.author || info.author === 'Unknown') return '';
  const text = info.license ? `© ${info.author} / ${info.license}` : `© ${info.author}`;
  return info.source_url
    ? `<a class="gallery-credit" href="${info.source_url}" target="_blank" rel="noopener">${text}</a>`
    : `<span class="gallery-credit">${text}</span>`;
}

function galleryCard(entry) {
  const { det, count, bestConf } = entry;
  const pct = Math.round(bestConf * 100);
  const clf = CLASSIFIERS.find(c => c.key === det.classifier);
  const icon = clf ? clf.icon : '◈';
  const key = _speciesKey(det.species_common);
  const hasImage = !!(
    _galleryCredits[key + '.jpg'] ||
    _galleryCredits[key + '.png'] ||
    _galleryCredits[key + '.webp']
  );
  const uploadBtn = hasImage ? '' : `
    <label class="gallery-upload-btn" title="Upload a photo for ${det.species_common}">
      + Add photo
      <input type="file" accept="image/jpeg,image/png,image/webp" style="display:none"
             onchange="_uploadFromCard('${key}', this)">
    </label>`;
  return `
    <div class="gallery-item" id="${_galleryItemId(det.species_common)}">
      <div class="gallery-img-wrap">
        <img src="${_speciesImageUrl(det.species_common)}"
             onerror="this.onerror=null;this.src='/species_images/_placeholder.svg';this.classList.add('gallery-placeholder')"
             loading="lazy" alt="${det.species_common}">
        <span class="gallery-count">×${count}</span>
        ${uploadBtn}
        ${_creditLine(det.species_common)}
      </div>
      <div class="gallery-info">
        <div class="gallery-name">${det.species_common}</div>
        <div class="gallery-sci">${det.species_scientific || ''}</div>
        <div class="gallery-meta">
          <span class="classifier-badge">${icon} ${det.classifier}</span>
          <span class="conf ${confClass(bestConf)}">${pct}%</span>
        </div>
      </div>
    </div>`;
}

async function _uploadFromCard(key, input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const r = await fetch(`/api/gallery/${key}/image`, { method: 'POST', body: formData });
    if (!r.ok) { const b = await r.json().catch(() => ({})); throw new Error(b.detail || `Upload failed (${r.status})`); }
    await _loadGalleryCredits();
    _populateGalleryGrid();
    toast('Photo added', 'success', 4000);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function renderGallery() {
  const confPct = Math.round(_galleryMinConf * 100);
  document.getElementById('main').innerHTML = `
    <div class="card">
      <div class="gallery-header">
        <div class="card-title" style="margin:0">Species Gallery</div>
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <span class="gallery-hint" id="gallery-count"></span>
          <div class="gallery-filter">
            <span class="gallery-filter-label">Min confidence: <strong id="gallery-conf-label">${_galleryFilterLabel(confPct)}</strong></span>
            <input type="range" class="gallery-conf-slider" id="gallery-conf-slider"
              min="0" max="95" step="5" value="${confPct}"
              oninput="
                _galleryMinConf = this.value / 100;
                document.getElementById('gallery-conf-label').textContent = _galleryFilterLabel(+this.value);
                _populateGalleryGrid();
              ">
          </div>
          <button class="btn btn-sm btn-outline" onclick="renderGalleryManage()">⚙ Manage Images</button>
        </div>
      </div>
      <div class="gallery-grid" id="gallery-grid"></div>
    </div>
  `;
  await _loadGalleryCredits();
  _populateGalleryGrid();
}

function _populateGalleryGrid() {
  const grid = document.getElementById('gallery-grid');
  if (!grid) return;
  const all = Object.values(state.gallery);
  const entries = all
    .filter(e => e.bestConf >= _galleryMinConf)
    .sort((a, b) => a.det.species_common.localeCompare(b.det.species_common));

  const countEl = document.getElementById('gallery-count');
  if (countEl) {
    if (!all.length) {
      countEl.textContent = 'No species detected yet';
    } else if (entries.length === all.length) {
      countEl.textContent = `${all.length} species this session`;
    } else {
      countEl.textContent = `${entries.length} of ${all.length} species`;
    }
  }

  if (!entries.length) {
    grid.innerHTML = all.length
      ? '<div class="empty" style="padding:24px 0">No species above the confidence threshold — try lowering the filter.</div>'
      : '<div class="empty" style="padding:24px 0">No species detected yet this session — start a recording to see species appear here.</div>';
    return;
  }
  grid.innerHTML = entries.map(e => galleryCard(e)).join('');
}

function updateGallery(det) {
  const key = det.species_common;
  const existing = state.gallery[key];
  if (!existing) {
    state.gallery[key] = { det, count: 1, bestConf: det.confidence };
    _populateGalleryGrid();
  } else {
    existing.count++;
    if (det.confidence > existing.bestConf) existing.bestConf = det.confidence;
    const el = document.getElementById(_galleryItemId(key));
    if (el) {
      const countBadge = el.querySelector('.gallery-count');
      if (countBadge) countBadge.textContent = `×${existing.count}`;
      const confEl = el.querySelector('.conf');
      if (confEl) {
        confEl.textContent = Math.round(existing.bestConf * 100) + '%';
        confEl.className = `conf ${confClass(existing.bestConf)}`;
      }
    }
  }
}

/* ── Gallery image management ── */
async function renderGalleryManage() {
  document.getElementById('main').innerHTML = `
    <div class="card">
      <div class="gallery-header">
        <div class="card-title" style="margin:0">Manage Gallery Images</div>
        <button class="btn btn-sm btn-outline" onclick="renderGallery()">← Back to Gallery</button>
      </div>
      <p style="font-size:0.82rem;color:var(--muted);margin-bottom:16px">
        Upload your own photos to personalise the gallery for your monitoring location.
        Edit author and licence fields to reflect the correct attribution for each image.
        Stock images are sourced from Wikimedia Commons under Creative Commons licences.
      </p>
      <div id="manage-table"><div class="empty">Loading...</div></div>
    </div>
  `;
  await _loadGalleryCredits();
  await _renderManageTable();
}

async function _renderManageTable() {
  const container = document.getElementById('manage-table');
  if (!container) return;
  let data;
  try {
    data = await api.get('/api/gallery');
  } catch (err) {
    container.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`;
    return;
  }
  if (!data.images.length) {
    container.innerHTML = '<div class="empty">No images installed yet.</div>';
    return;
  }
  container.innerHTML = `
    <table class="manage-table">
      <thead>
        <tr>
          <th style="width:72px">Photo</th>
          <th>Species</th>
          <th>Author / Photographer</th>
          <th>Licence</th>
          <th style="width:140px">Actions</th>
        </tr>
      </thead>
      <tbody>
        ${data.images.map(img => _manageRow(img)).join('')}
      </tbody>
    </table>`;
}

function _manageRow(img) {
  const key = img.key;
  const author  = (img.author      || '').replace(/"/g, '&quot;');
  const license = (img.license     || '').replace(/"/g, '&quot;');
  const licUrl  = (img.license_url || '').replace(/"/g, '&quot;');
  const srcUrl  = (img.source_url  || '').replace(/"/g, '&quot;');
  const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return `
    <tr id="mrow-${key}">
      <td>
        <img src="${img.url}" class="manage-thumb"
             onerror="this.src='/species_images/_placeholder.svg';this.style.opacity='0.4'"
             id="mthumb-${key}">
      </td>
      <td>
        <div style="font-weight:600;font-size:0.85rem">${displayName}</div>
        <div style="font-size:0.72rem;color:var(--muted);font-family:var(--mono)">${img.filename}</div>
        ${srcUrl ? `<a href="${srcUrl}" target="_blank" rel="noopener" style="font-size:0.7rem;color:var(--primary)">View source ↗</a>` : ''}
      </td>
      <td>
        <input class="manage-input" type="text" id="author-${key}"
               value="${author}" placeholder="Photographer name">
      </td>
      <td>
        <input class="manage-input" type="text" id="license-${key}"
               value="${license}" placeholder="e.g. CC BY-SA 4.0" style="width:120px">
        <input class="manage-input" type="text" id="licurl-${key}"
               value="${licUrl}" placeholder="Licence URL" style="width:100%;margin-top:4px">
      </td>
      <td>
        <div style="display:flex;flex-direction:column;gap:6px">
          <button class="btn btn-sm btn-primary" onclick="_saveCredit('${key}', this)">Save</button>
          <label class="btn btn-sm btn-outline" style="cursor:pointer;text-align:center">
            Upload photo
            <input type="file" accept="image/jpeg,image/png,image/webp" style="display:none"
                   onchange="_uploadImage('${key}', this)">
          </label>
        </div>
      </td>
    </tr>`;
}

async function _saveCredit(key, btn) {
  btnLoad(btn, '⟳');
  const author      = document.getElementById(`author-${key}`)?.value  || '';
  const license     = document.getElementById(`license-${key}`)?.value || '';
  const license_url = document.getElementById(`licurl-${key}`)?.value  || '';
  const source_url  = _galleryCredits[key + '.jpg']?.source_url || _galleryCredits[key + '.png']?.source_url || '';
  try {
    await api._request(`/api/gallery/${key}/credits`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author, license, license_url, source_url }),
    });
    _galleryCredits[key + '.jpg'] = { author, license, license_url, source_url };
    toast('Credit saved', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
  btnDone(btn);
}

async function _uploadImage(key, input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const r = await fetch(`/api/gallery/${key}/image`, { method: 'POST', body: formData });
    if (!r.ok) { const b = await r.json().catch(() => ({})); throw new Error(b.detail || `Upload failed (${r.status})`); }
    const result = await r.json();
    // Refresh thumbnail with cache-busting
    const thumb = document.getElementById(`mthumb-${key}`);
    if (thumb) thumb.src = result.url + '?t=' + Date.now();
    toast('Image uploaded — credits updated to reflect your own photograph', 'success', 5000);
    // Pre-fill author with location name if credits are empty
    const authorEl = document.getElementById(`author-${key}`);
    if (authorEl && !authorEl.value) authorEl.value = 'Own photograph';
    const licenseEl = document.getElementById(`license-${key}`);
    if (licenseEl && !licenseEl.value) licenseEl.value = 'All rights reserved';
  } catch (err) {
    toast(err.message, 'error');
  }
}

function ukDate(iso) {
  // Convert YYYY-MM-DD → DD/MM/YYYY
  if (!iso || iso.length < 10) return iso || '';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}

function detectionCard(det) {
  const pct = Math.round(det.confidence * 100);
  const classifierInfo = CLASSIFIERS.find(c => c.key === det.classifier);
  const icon = classifierInfo ? classifierInfo.icon : '◈';
  const deviceTag = det.device_name && det.device_name !== 'Default'
    ? `<span class="classifier-badge" style="color:var(--accent)">${det.device_name}</span>` : '';
  return `
    <div class="detection-card">
      <span class="classifier-badge">${icon} ${det.classifier}</span>
      <div class="det-body">
        <div class="det-top">
          <span class="species">${det.species_common}</span>
          ${deviceTag}
        </div>
        <div class="det-bottom">
          <span class="scientific">${det.species_scientific || ''}</span>
          <span class="det-meta">
            <span class="conf ${confClass(det.confidence)}">${pct}%</span>
            <span class="time">${det.time}</span>
          </span>
        </div>
      </div>
    </div>`;
}

/* ─────────────────────────── SCHEDULE ─────────────────────────── */
async function renderSchedule() {
  document.getElementById('main').innerHTML = `
    <div class="card">
      <div class="card-title">Today's Listening Windows ${helpBtn('schedule')}</div>
      <div id="schedule-table"><div class="empty">Loading...</div></div>
    </div>
    <div class="card">
      <div class="card-title">Add Custom Window</div>
      <div class="form-row">
        <div class="form-group"><label>Name</label><input type="text" id="w-name" placeholder="my_window"></div>
        <div class="form-group"><label>Anchor</label>
          <select id="w-anchor">
            <option value="sunrise">Sunrise</option><option value="sunset">Sunset</option>
            <option value="noon">Noon</option><option value="fixed">Fixed time</option>
          </select>
        </div>
        <div class="form-group"><label>Offset (min)</label><input type="number" id="w-offset" value="0" style="width:90px"></div>
        <div class="form-group"><label>Duration (min)</label><input type="number" id="w-duration" value="60" style="width:90px"></div>
        <div class="form-group" id="fixed-time-group" style="display:none"><label>Fixed time (HH:MM)</label><input type="text" id="w-fixed" placeholder="23:00"></div>
        <div class="form-group" style="justify-content:flex-end"><button class="btn btn-primary" id="btn-add-window">Add Window</button></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Classifiers & Microphones ${helpBtn('classifiers')}</div>
      <p style="font-size:0.82rem;color:var(--muted);margin-bottom:14px">
        Select which classifiers are active and which microphone each one uses.
        Changes apply when the next listening session starts.
      </p>
      <div id="classifier-device-panel"><div class="empty">Loading...</div></div>
      <div style="margin-top:14px">
        <button class="btn btn-primary" id="btn-save-classifiers">Save</button>
      </div>
    </div>
  `;
  document.getElementById('w-anchor').addEventListener('change', e =>
    document.getElementById('fixed-time-group').style.display = e.target.value === 'fixed' ? '' : 'none'
  );
  document.getElementById('btn-add-window').addEventListener('click', addWindow);
  document.getElementById('btn-save-classifiers').addEventListener('click', saveClassifiers);
  await Promise.all([loadSchedule(), loadClassifierDevices()]);
}

const _CLF_META = {
  bird:   { icon: '🐦', label: 'Birds',    note: 'Standard microphone (48kHz)' },
  bat:    { icon: '🦇', label: 'Bats',     note: 'Requires ultrasonic mic (≥192kHz)' },
  bee:    { icon: '🐝', label: 'Bees',     note: 'Standard microphone (16kHz) — BuzzDetect v1.0.1' },
  insect: { icon: '🦗', label: 'Insects',  note: 'Standard microphone (44.1kHz) — grasshoppers, bush crickets' },
  soil:   { icon: '🌱', label: 'Soil',     note: 'Surface / contact microphone (22kHz) — Soil Acoustic Index (beta)' },
};

async function loadClassifierDevices() {
  const panel = document.getElementById('classifier-device-panel');
  if (!panel) return;
  try {
    const [clfData, devData] = await Promise.all([
      api.get('/api/settings/classifiers'),
      api.get('/api/devices'),
    ]);

    const deviceOptions = (selected) => {
      const none = `<option value="" ${!selected ? 'selected' : ''}>System default</option>`;
      const opts = devData.devices.map(d =>
        `<option value="${d.name}" ${selected === d.name ? 'selected' : ''}>${d.label || d.name}</option>`
      ).join('');
      return none + opts;
    };

    panel.innerHTML = ['bird', 'bat', 'bee', 'insect', 'soil'].map(key => {
      const meta = _CLF_META[key];
      const isActive = clfData.active.includes(key);
      const assignedDevice = clfData.devices[key];
      return `
        <div class="device-row" style="margin-bottom:6px" id="clf-row-${key}">
          <div class="device-info">
            <div class="device-name">${meta.icon} ${meta.label}</div>
            <div class="device-meta">${meta.note}</div>
          </div>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;color:var(--muted);cursor:pointer">
            <input type="checkbox" id="clf-active-${key}" ${isActive ? 'checked' : ''}
              style="accent-color:var(--primary);width:16px;height:16px">
            Active
          </label>
          <div class="form-group" style="margin:0">
            <label style="font-size:0.72rem">Microphone</label>
            <select id="clf-device-${key}" style="min-width:200px">
              ${deviceOptions(assignedDevice)}
            </select>
          </div>
        </div>`;
    }).join('');

    // Auto-save on any change so the YAML always matches the UI — otherwise
    // users uncheck a classifier, never click Save, and the next Listen Now
    // re-spins up the unwanted classifier from stale config.
    panel.querySelectorAll('input[id^="clf-active-"], select[id^="clf-device-"]')
      .forEach(el => el.addEventListener('change', saveClassifiers));
  } catch (err) {
    panel.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`;
  }
}

async function saveClassifiers() {
  const btn = document.getElementById('btn-save-classifiers');
  if (btn) btnLoad(btn, '⟳ Saving...');
  const active = ['bird', 'bat', 'bee', 'insect', 'soil'].filter(k =>
    document.getElementById(`clf-active-${k}`)?.checked
  );
  const devices = {};
  for (const key of ['bird', 'bat', 'bee', 'insect', 'soil']) {
    const val = document.getElementById(`clf-device-${key}`)?.value;
    devices[key] = val === '' ? null : val;
  }
  try {
    await api.post('/api/settings/classifiers', { active, devices });
    toast('Classifier settings saved — applies on next Listen Now', 'success', 4000);
  } catch (err) {
    toast(err.message, 'error', 6000);
  } finally { if (btn) btnDone(btn); }
}

async function loadSchedule() {
  const el = document.getElementById('schedule-table');
  if (!el) return;
  try {
    const data = await api.get('/api/schedule');
    if (!data.windows.length) { el.innerHTML = '<div class="empty">No windows configured.</div>'; return; }
    el.innerHTML = `
      <table>
        <thead><tr><th>Window</th><th>Start</th><th>End</th><th>Duration</th><th>Status</th><th></th></tr></thead>
        <tbody>${data.windows.map(w => `
          <tr class="${w.active ? 'active-row' : ''}">
            <td>${w.name}</td><td class="window-time">${w.start}</td>
            <td class="window-time">${w.end}</td><td>${w.duration_mins} min</td>
            <td>${w.active ? '<span class="badge-active">● ACTIVE</span>' : ''}</td>
            <td>${w.editable ? `<button class="btn btn-sm btn-danger" onclick="deleteWindow('${w.name}')">Remove</button>` : ''}</td>
          </tr>`).join('')}
        </tbody>
      </table>`;
  } catch (err) { el.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`; }
}

async function addWindow() {
  const btn = document.getElementById('btn-add-window');
  const name = document.getElementById('w-name').value.trim();
  const anchor = document.getElementById('w-anchor').value;
  const offset_mins = parseInt(document.getElementById('w-offset').value) || 0;
  const duration_mins = parseInt(document.getElementById('w-duration').value);
  const fixed_time = anchor === 'fixed' ? document.getElementById('w-fixed').value.trim() : null;
  if (!name) { toast('Window name is required', 'warn'); return; }
  if (!duration_mins) { toast('Duration is required', 'warn'); return; }
  btnLoad(btn, '⟳ Adding...');
  try {
    await api.post('/api/schedule/windows', { name, anchor, offset_mins, duration_mins, fixed_time });
    toast(`Window '${name}' added`, 'success');
    document.getElementById('w-name').value = '';
    await loadSchedule();
  } catch (err) { toast(err.message, 'error', 6000); } finally { btnDone(btn); }
}

async function deleteWindow(name) {
  try {
    await api.del(`/api/schedule/windows/${name}`);
    toast(`Window '${name}' removed`, 'warn');
    await loadSchedule();
  } catch (err) { toast(err.message, 'error', 6000); }
}

/* ─────────────────────────── CLIPS ─────────────────────────── */
async function renderClips() {
  document.getElementById('main').innerHTML = `
    <div class="card" style="flex:1">
      <div class="card-title">Audio Clip Library ${helpBtn('clips')}</div>
      <div class="tabs" id="clips-tabs">
        ${CLASSIFIERS.map(c => `<button class="tab ${c.key === 'all' ? 'active' : ''}"
          onclick="filterClips('${c.key}', this)">${c.icon} ${c.label}</button>`).join('')}
      </div>
      <div class="clips-layout">
        <div>
          <div class="card-title">Species</div>
          <div class="species-list" id="species-list"><div class="empty">Loading...</div></div>
        </div>
        <div>
          <div class="card-title" id="clips-title">Select a species</div>
          <div class="clips-grid" id="clips-grid"><div class="empty">Select a species to browse clips.</div></div>
        </div>
      </div>
    </div>
  `;
  await loadSpeciesList('all');
}

async function loadSpeciesList(classifierFilter = 'all') {
  const el = document.getElementById('species-list');
  if (!el) return;
  el.innerHTML = '<div class="empty">Loading...</div>';
  try {
    const data = await api.get('/api/clips');   // always fetch all; group client-side
    if (!data.species.length) {
      el.innerHTML = '<div class="empty">No clips recorded yet.</div>';
      return;
    }

    if (classifierFilter !== 'all') {
      // Filtered view — flat list for selected type
      const filtered = data.species.filter(s => s.classifier === classifierFilter);
      if (!filtered.length) {
        el.innerHTML = `<div class="empty">No ${classifierFilter} clips recorded yet.</div>`;
        return;
      }
      el.innerHTML = filtered.map(s => speciesItem(s)).join('');
      return;
    }

    // All view — group by classifier type with headers
    const groups = {};
    CLASSIFIERS.filter(c => c.key !== 'all').forEach(c => { groups[c.key] = []; });
    data.species.forEach(s => {
      const key = s.classifier || 'bird';
      if (!groups[key]) groups[key] = [];
      groups[key].push(s);
    });

    let html = '';
    CLASSIFIERS.filter(c => c.key !== 'all').forEach(c => {
      const items = groups[c.key] || [];
      if (!items.length) return;
      html += `<div class="species-group-header">${c.icon} ${c.label}</div>`;
      html += items.map(s => speciesItem(s)).join('');
    });
    el.innerHTML = html || '<div class="empty">No clips recorded yet.</div>';
  } catch (err) { el.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`; }
}

function speciesItem(s) {
  return `<div class="species-item" data-dir="${s.dir}" onclick="loadClips('${s.dir}','${s.name}')">
    <span>${s.name}</span><span class="count">${s.clip_count}</span>
  </div>`;
}

function filterClips(key, btn) {
  document.querySelectorAll('#clips-tabs .tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  loadSpeciesList(key);
}

async function loadClips(dir, name) {
  document.querySelectorAll('.species-item').forEach(el =>
    el.classList.toggle('active', el.dataset.dir === dir)
  );
  document.getElementById('clips-title').textContent = name;
  const grid = document.getElementById('clips-grid');
  grid.innerHTML = '<div class="empty">Loading...</div>';
  try {
    const data = await api.get(`/api/clips/${dir}`);
    if (!data.clips.length) { grid.innerHTML = '<div class="empty">No clips for this species.</div>'; return; }
    grid.innerHTML = data.clips.map(c => `
      <div class="clip-row">
        <div class="clip-meta">${ukDate(c.date)} ${c.time}<br><span class="conf ${confClass(c.confidence)}">${Math.round(c.confidence * 100)}% conf</span></div>
        <audio controls src="${c.url}" preload="none"></audio>
        <button class="btn btn-sm btn-danger" onclick="deleteClip('${dir}','${c.filename}',this)">✕</button>
      </div>`).join('');
  } catch (err) { grid.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`; }
}

async function deleteClip(dir, filename, btn) {
  btnLoad(btn, '...');
  try {
    await api.del(`/api/clips/${dir}/${filename}`);
    btn.closest('.clip-row').remove();
    toast('Clip deleted', 'warn');
  } catch (err) { toast(err.message, 'error', 6000); btnDone(btn); }
}

/* ─────────────────────────── REPORTS ─────────────────────────── */
async function renderReports() {
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);

  const typeOptions = CLASSIFIERS.map(c =>
    `<option value="${c.key}">${c.icon} ${c.label}</option>`
  ).join('');

  document.getElementById('main').innerHTML = `
    <div class="card">
      <div class="card-title">Filters</div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group">
          <label>From</label>
          <input type="date" id="r-from" lang="en-GB" value="${weekAgo}">
        </div>
        <div class="form-group">
          <label>To</label>
          <input type="date" id="r-to" lang="en-GB" value="${today}">
        </div>
        <div class="form-group">
          <label>Type</label>
          <select id="r-type">${typeOptions}</select>
        </div>
        <div class="form-group">
          <label>Species</label>
          <select id="r-species" style="min-width:180px"><option value="">All species</option></select>
        </div>
        <div class="form-group" style="justify-content:flex-end">
          <button class="btn btn-primary" id="btn-load-report">Load Report</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Summary ${helpBtn('reports')}</div>
      <div id="report-content"><div class="empty">Select filters and click Load Report.</div></div>
    </div>

    <div class="card">
      <div class="card-title">Download</div>
      <div class="download-row">
        <button class="btn btn-outline" id="btn-dl-detections">⬇ Detections CSV</button>
        <button class="btn btn-outline" id="btn-dl-sessions">⬇ Sessions CSV</button>
      </div>
      <p style="font-size:0.75rem;color:var(--muted);margin-top:10px">
        Downloads respect the date range and species filter selected above.
      </p>
    </div>

    <div class="card">
      <div class="card-title">Activity Heatmaps ${helpBtn('heatmap')}</div>
      <div id="heatmap-section"><div class="heatmap-empty">Load a report above to generate heatmaps.</div></div>
    </div>

    <div class="card">
      <div class="card-title">Download</div>
      <div class="download-row">
        <button class="btn btn-outline" id="btn-dl-detections">⬇ Detections CSV</button>
        <button class="btn btn-outline" id="btn-dl-sessions">⬇ Sessions CSV</button>
      </div>
      <p style="font-size:0.75rem;color:var(--muted);margin-top:10px">
        Downloads respect the date range and species filter selected above.
      </p>
    </div>

    <div class="card">
      <div class="card-title" style="color:var(--danger)">Danger Zone</div>
      <p style="font-size:0.82rem;color:var(--muted);margin-bottom:12px">
        Permanently deletes all detection and session log files. This cannot be undone.
      </p>
      <button class="btn btn-danger" id="btn-clear-logs">🗑 Clear All Logs</button>
    </div>
  `;

  document.getElementById('btn-load-report').addEventListener('click', loadReport);
  document.getElementById('btn-dl-detections').addEventListener('click', () => downloadReport('detections'));
  document.getElementById('btn-dl-sessions').addEventListener('click', () => downloadReport('sessions'));
  document.getElementById('btn-clear-logs').addEventListener('click', confirmClearLogs);
  document.getElementById('r-type').addEventListener('change', refreshReportSpecies);

  // Populate species dropdown for initial "all" selection
  await refreshReportSpecies();
}

async function refreshReportSpecies() {
  const typeEl = document.getElementById('r-type');
  const speciesEl = document.getElementById('r-species');
  if (!typeEl || !speciesEl) return;
  const classifier = typeEl.value === 'all' ? '' : typeEl.value;
  const url = classifier ? `/api/reports/species?classifier=${classifier}` : '/api/reports/species';
  try {
    const data = await api.get(url);
    speciesEl.innerHTML = '<option value="">All species</option>' +
      data.species.map(s => `<option value="${s}">${s}</option>`).join('');
  } catch (_) {}
}

async function loadReport() {
  const btn = document.getElementById('btn-load-report');
  const from = document.getElementById('r-from').value;
  const to = document.getElementById('r-to').value;
  const classifier = document.getElementById('r-type')?.value || 'all';
  const species = document.getElementById('r-species')?.value || '';
  const el = document.getElementById('report-content');
  el.innerHTML = '<div class="empty">Loading...</div>';
  btnLoad(btn, '⟳ Loading...');
  const classifierParam = classifier && classifier !== 'all' ? `&classifier=${classifier}` : '';
  const speciesParam = species ? `&species=${encodeURIComponent(species)}` : '';
  try {
    const data = await api.get(`/api/reports/summary?date_from=${from}&date_to=${to}${classifierParam}${speciesParam}`);
    const filterLabel = data.species ? ` — ${data.species}` : '';
    if (!data.days.length) { el.innerHTML = `<div class="empty">No data for this period${filterLabel}.</div>`; return; }
    el.innerHTML = `
      ${data.species ? `<p style="font-size:0.82rem;color:var(--accent);margin-bottom:12px">Filtered: ${data.species}</p>` : ''}
      <div class="grid-2" style="margin-bottom:16px">
        <div class="stat"><div class="value">${data.totals.sessions}</div><div class="label">Sessions</div></div>
        <div class="stat"><div class="value">${data.totals.total_calls}</div><div class="label">Total calls</div></div>
      </div>
      <table>
        <thead><tr><th>Date</th><th>Sessions</th>${data.species ? '' : '<th>Species</th>'}<th>Total Calls</th></tr></thead>
        <tbody>${data.days.map(d => `
          <tr><td class="window-time">${ukDate(d.date)}</td><td>${d.sessions}</td>${data.species ? '' : `<td>${d.species_count}</td>`}<td>${d.total_calls}</td></tr>`).join('')}
        </tbody>
      </table>`;
    // Load heatmaps in parallel
    loadHeatmaps(from, to, classifierParam.replace('&classifier=',''));
  } catch (err) {
    el.innerHTML = `<div class="empty" style="color:var(--danger)">${err.message}</div>`;
    toast(err.message, 'error', 6000);
  } finally { btnDone(btn); }
}

async function loadHeatmaps(from, to, classifier) {
  const el = document.getElementById('heatmap-section');
  if (!el) return;
  el.innerHTML = '<div class="heatmap-empty">Loading heatmaps…</div>';
  try {
    let url = `/api/reports/heatmap?date_from=${from}&date_to=${to}`;
    if (classifier) url += `&classifier=${classifier}`;
    const data = await api.get(url);
    const species = Object.keys(data.by_hour);
    if (!species.length) { el.innerHTML = '<div class="heatmap-empty">No data to display.</div>'; return; }

    el.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;flex-wrap:wrap">
        <div>
          <div class="heatmap-title">Time of Day</div>
          <div class="heatmap-wrap" id="hm-hour"></div>
        </div>
        <div>
          <div class="heatmap-title">Month of Year</div>
          <div class="heatmap-wrap" id="hm-month"></div>
        </div>
      </div>
      <div class="heatmap-legend">
        <span>Fewer</span><div class="heatmap-legend-bar"></div><span>More detections</span>
      </div>`;

    renderHeatmap('hm-hour', species, data.by_hour,
      Array.from({length:24}, (_,i) => `${String(i).padStart(2,'0')}:00`));

    const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    renderHeatmap('hm-month', species, data.by_month, MONTHS);
  } catch (err) {
    el.innerHTML = `<div class="heatmap-empty" style="color:var(--danger)">${err.message}</div>`;
  }
}

function renderHeatmap(containerId, species, data, colLabels) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const nCols = colLabels.length;

  // Compute global max for colour scaling
  let maxVal = 1;
  species.forEach(s => { data[s].forEach(v => { if (v > maxVal) maxVal = v; }); });

  const cellToColor = (v) => {
    if (!v) return 'var(--surface2)';
    const intensity = v / maxVal;
    const l = Math.round(50 - intensity * 30);  // 50% → 20% lightness
    return `hsl(150, 60%, ${l}%)`;
  };

  // Build grid: label col + nCols data cols
  const gridCols = `120px repeat(${nCols}, 22px)`;
  let html = `<div class="heatmap-grid" style="display:grid;grid-template-columns:${gridCols};gap:1px">`;

  // Header row
  html += `<div></div>`;
  colLabels.forEach((lbl, i) => {
    const show = nCols <= 12 || i % 3 === 0;
    html += `<div class="heatmap-col-header">${show ? lbl : ''}</div>`;
  });

  // Data rows
  species.forEach(s => {
    const label = s.length > 18 ? s.slice(0, 17) + '…' : s;
    html += `<div class="heatmap-label" title="${s}">${label}</div>`;
    data[s].forEach((v, i) => {
      html += `<div class="heatmap-cell" style="background:${cellToColor(v)}"
        title="${s} · ${colLabels[i]}: ${v} detection${v !== 1 ? 's' : ''}"></div>`;
    });
  });

  html += '</div>';
  el.innerHTML = html;
}

function downloadReport(type) {
  const from = document.getElementById('r-from')?.value || '';
  const to = document.getElementById('r-to')?.value || '';
  const classifier = document.getElementById('r-type')?.value || 'all';
  const species = document.getElementById('r-species')?.value || '';
  let url = `/api/reports/download/${type}?date_from=${from}&date_to=${to}`;
  if (classifier && classifier !== 'all') url += `&classifier=${classifier}`;
  if (species) url += `&species=${encodeURIComponent(species)}`;
  const a = document.createElement('a');
  a.href = url; a.download = ''; a.click();
}

async function confirmClearLogs() {
  const confirmed = window.confirm(
    'Are you sure you want to delete ALL detection and session logs?\n\nThis cannot be undone.'
  );
  if (!confirmed) return;
  const btn = document.getElementById('btn-clear-logs');
  btnLoad(btn, '⟳ Clearing...');
  try {
    const result = await api.del('/api/reports/logs');
    toast(`Logs cleared: ${result.cleared.join(', ') || 'nothing to delete'}`, 'warn', 6000);
  } catch (err) {
    toast(err.message, 'error', 6000);
  } finally { btnDone(btn); }
}

/* ─────────────────────────── SETTINGS ─────────────────────────── */
async function renderSettings() {
  document.getElementById('main').innerHTML = `
    <div class="card">
      <div class="card-title">Recording Location ${helpBtn('location')}</div>
      <p style="font-size:0.82rem;color:var(--muted);margin-bottom:16px">
        Used for BirdNET species filtering, CSV logs, and MQTT detection messages.
      </p>
      <div class="form-row">
        <div class="form-group" style="flex:2">
          <label>Location Name</label>
          <input type="text" id="loc-name" placeholder="e.g. Blenheim Palace" style="min-width:220px">
        </div>
        <div class="form-group">
          <label>Latitude</label>
          <input type="number" id="loc-lat" step="0.0001" placeholder="51.8403" style="width:120px">
        </div>
        <div class="form-group">
          <label>Longitude</label>
          <input type="number" id="loc-lon" step="0.0001" placeholder="-1.3625" style="width:120px">
        </div>
        <div class="form-group" style="justify-content:flex-end">
          <button class="btn btn-primary" id="btn-save-location">Save</button>
        </div>
      </div>
      <div id="location-status"></div>
    </div>

    <div class="card">
      <div class="card-title">MQTT Live Feed ${helpBtn('mqtt')}</div>
      <p style="font-size:0.82rem;color:var(--muted);margin-bottom:16px">
        Publish every detection as JSON to an MQTT broker in real time.
        Credentials are stored locally and never committed to git.
      </p>

      <div class="form-row" style="margin-bottom:16px;align-items:center;gap:20px">
        <label style="display:flex;align-items:center;gap:8px;font-size:0.88rem;cursor:pointer">
          <input type="checkbox" id="mqtt-enabled" style="accent-color:var(--primary);width:16px;height:16px">
          <span>Enable MQTT publishing</span>
        </label>
      </div>

      <div class="form-row" style="margin-bottom:16px">
        <div class="form-group">
          <label>Connection mode</label>
          <select id="mqtt-mode">
            <option value="direct">Direct — Python connects to broker (cloud/remote, with credentials)</option>
            <option value="bridge">Bridge — Python connects to local Mosquitto, which forwards upstream</option>
          </select>
        </div>
        <div class="form-group" style="flex:1">
          <label>Topic Prefix</label>
          <input type="text" id="mqtt-prefix" placeholder="bioacoustics">
        </div>
      </div>

      <div id="mqtt-direct-fields">
        <div class="form-row" style="margin-bottom:10px">
          <div class="form-group" style="flex:2">
            <label>Broker Host</label>
            <input type="text" id="mqtt-host" placeholder="hostname or IP">
          </div>
          <div class="form-group" style="width:110px">
            <label>Port</label>
            <input type="number" id="mqtt-port" placeholder="1883" style="width:90px">
          </div>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;color:var(--muted);cursor:pointer;align-self:flex-end;padding-bottom:10px">
            <input type="checkbox" id="mqtt-tls" style="accent-color:var(--primary);width:14px;height:14px">
            TLS / SSL
          </label>
        </div>
        <div class="form-row">
          <div class="form-group" style="flex:1">
            <label>Username</label>
            <input type="text" id="mqtt-user" placeholder="optional" autocomplete="off">
          </div>
          <div class="form-group" style="flex:1">
            <label>Password</label>
            <input type="password" id="mqtt-pass" placeholder="leave blank to keep existing" autocomplete="new-password">
          </div>
          <div id="mqtt-pass-note" style="align-self:flex-end;padding-bottom:10px;font-size:0.73rem;color:var(--muted);white-space:nowrap"></div>
        </div>
      </div>

      <div id="mqtt-bridge-fields" style="display:none">
        <div class="form-row" style="margin-bottom:10px">
          <div class="form-group" style="flex:2">
            <label>Local Mosquitto Host</label>
            <input type="text" id="mqtt-bridge-host" value="localhost" placeholder="localhost">
          </div>
          <div class="form-group" style="width:110px">
            <label>Port</label>
            <input type="number" id="mqtt-bridge-port" value="1883" style="width:90px">
          </div>
        </div>
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-size:0.78rem;color:var(--muted);line-height:1.6">
          <strong style="color:var(--text)">Mosquitto bridge setup</strong><br>
          Python connects to local Mosquitto — add a bridge config on the host machine to forward to your remote broker:<br>
          <code style="display:block;margin-top:6px;color:var(--accent);font-family:var(--mono)">/etc/mosquitto/conf.d/bridge.conf</code>
          Credentials for the remote broker go in that file only — not here.
          Run <code style="color:var(--accent);font-family:var(--mono)">sudo systemctl restart mosquitto</code> after editing.
        </div>
      </div>

      <div class="btn-group" style="margin-top:16px">
        <button class="btn btn-primary" id="btn-save-mqtt">Save</button>
        <button class="btn btn-outline" id="btn-test-mqtt">Test Connection</button>
      </div>
      <div id="mqtt-test-result" style="margin-top:10px;font-size:0.82rem"></div>
    </div>
  `;

  // Load location
  try {
    const loc = await api.get('/api/settings/location');
    document.getElementById('loc-name').value = loc.name || '';
    document.getElementById('loc-lat').value = loc.latitude || '';
    document.getElementById('loc-lon').value = loc.longitude || '';
  } catch (err) { toast(err.message, 'error'); }

  // Load MQTT
  try {
    const m = await api.get('/api/settings/mqtt');
    document.getElementById('mqtt-enabled').checked = m.enabled;
    document.getElementById('mqtt-mode').value = m.mode || 'direct';
    document.getElementById('mqtt-prefix').value = m.topic_prefix || 'bioacoustics';
    document.getElementById('mqtt-host').value = m.host || '';
    document.getElementById('mqtt-port').value = m.port || 1883;
    document.getElementById('mqtt-tls').checked = m.tls || false;
    document.getElementById('mqtt-user').value = m.username || '';
    if (m.has_password) document.getElementById('mqtt-pass-note').textContent = '● password set';
    _mqttModeChanged(m.mode || 'direct');
  } catch (err) { toast(err.message, 'error'); }

  document.getElementById('mqtt-mode').addEventListener('change', e => _mqttModeChanged(e.target.value));
  document.getElementById('btn-save-location').addEventListener('click', saveLocation);
  document.getElementById('btn-save-mqtt').addEventListener('click', saveMqtt);
  document.getElementById('btn-test-mqtt').addEventListener('click', testMqtt);
}

function _mqttModeChanged(mode) {
  const isDirect = mode === 'direct';
  document.getElementById('mqtt-direct-fields').style.display = isDirect ? '' : 'none';
  document.getElementById('mqtt-bridge-fields').style.display = isDirect ? 'none' : '';
}

async function saveMqtt() {
  const btn = document.getElementById('btn-save-mqtt');
  const password = document.getElementById('mqtt-pass').value;
  btnLoad(btn, '⟳ Saving...');
  const mode = document.getElementById('mqtt-mode').value;
  const isBridge = mode === 'bridge';
  try {
    await api.post('/api/settings/mqtt', {
      enabled: document.getElementById('mqtt-enabled').checked,
      mode,
      host: isBridge
        ? (document.getElementById('mqtt-bridge-host').value.trim() || 'localhost')
        : document.getElementById('mqtt-host').value.trim(),
      port: isBridge
        ? (parseInt(document.getElementById('mqtt-bridge-port').value) || 1883)
        : (parseInt(document.getElementById('mqtt-port').value) || 1883),
      tls: isBridge ? false : document.getElementById('mqtt-tls').checked,
      topic_prefix: document.getElementById('mqtt-prefix').value.trim() || 'bioacoustics',
      username: isBridge ? null : (document.getElementById('mqtt-user').value.trim() || null),
      password: isBridge ? null : (password || null),
    });
    if (password) {
      document.getElementById('mqtt-pass').value = '';
      document.getElementById('mqtt-pass-note').textContent = '● password set';
    }
    toast('MQTT settings saved — restart pipeline to apply', 'success', 5000);
  } catch (err) {
    toast(err.message, 'error', 6000);
  } finally { btnDone(btn); }
}

async function testMqtt() {
  const btn = document.getElementById('btn-test-mqtt');
  const result = document.getElementById('mqtt-test-result');
  btnLoad(btn, '⟳ Testing...');
  result.textContent = '';
  try {
    const data = await api.post('/api/settings/mqtt/test', {});
    if (data.connected) {
      result.style.color = 'var(--primary)';
      result.textContent = '✓ Connected successfully';
    } else {
      result.style.color = 'var(--danger)';
      result.textContent = `✗ ${data.error || 'Connection failed'}`;
    }
  } catch (err) {
    result.style.color = 'var(--danger)';
    result.textContent = `✗ ${err.message}`;
  } finally { btnDone(btn); }
}

async function saveLocation() {
  const btn = document.getElementById('btn-save-location');
  const name = document.getElementById('loc-name').value.trim();
  const latitude = parseFloat(document.getElementById('loc-lat').value);
  const longitude = parseFloat(document.getElementById('loc-lon').value);
  if (!name) { toast('Location name is required', 'warn'); return; }
  if (isNaN(latitude) || isNaN(longitude)) { toast('Valid latitude and longitude required', 'warn'); return; }
  btnLoad(btn, '⟳ Saving...');
  try {
    await api.post('/api/settings/location', { name, latitude, longitude });
    toast(`Location saved — ${name}`, 'success', 5000);
    document.getElementById('location-status').innerHTML =
      `<p style="font-size:0.78rem;color:var(--muted);margin-top:10px">Restart the pipeline to apply changes to the active session.</p>`;
  } catch (err) {
    toast(err.message, 'error', 6000);
  } finally { btnDone(btn); }
}

/* ── Help system ── */
const HELP = {
  spectrogram: {
    icon: '🔬', title: 'Live Spectrogram',
    body: `<p>A spectrogram is a visual representation of sound — it shows <strong>which frequencies are present</strong> in the audio at each moment in time.</p>
    <p><strong>How to read it:</strong></p>
    <ul style="padding-left:16px;margin:8px 0">
      <li>The <strong>horizontal axis</strong> is time, scrolling left as new audio arrives on the right.</li>
      <li>The <strong>vertical axis</strong> is frequency — low sounds (bass, worms, wind) at the bottom, high sounds (birdsong, insects) at the top.</li>
      <li><strong>Colour</strong> indicates loudness: dark = quiet, bright green/yellow/red = loud.</li>
    </ul>
    <p>Bird calls appear as bright horizontal streaks in the 2–8 kHz band. The dawn chorus produces a spectacular burst of overlapping streaks. Bee buzzes appear as a diffuse band around 200–400 Hz. Soil activity appears as faint low-frequency texture near the bottom.</p>
    <p><em>Log scale</em> compresses the upper frequencies and expands the lower ones — useful for seeing soil and low-frequency signals that would otherwise be squeezed into a thin strip.</p>`
  },
  vu_meter: {
    icon: '🎙', title: 'Audio Level (VU Meter)',
    body: `<p>The bar shows the <strong>current volume level</strong> from the microphone in decibels (dB). It updates every second while the pipeline is listening.</p>
    <p><strong>What the numbers mean:</strong></p>
    <ul style="padding-left:16px;margin:8px 0">
      <li><strong>–60 dB or lower</strong> — near silence; the microphone is picking up very little.</li>
      <li><strong>–40 to –20 dB</strong> — typical ambient outdoor level; good for detection.</li>
      <li><strong>–10 dB or higher</strong> — loud sound nearby (close bird call, wind gust, handling noise).</li>
    </ul>
    <p>If the bar never moves, the microphone may not be capturing audio — check the device selection in Recording Devices.</p>`
  },
  live_detections: {
    icon: '◈', title: 'Live Detection Feed',
    body: `<p>Every time an AI classifier identifies a species with sufficient confidence, a detection card appears here in real time.</p>
    <p>Each card shows the <strong>species name</strong>, <strong>confidence score</strong> (how certain the model is), the <strong>classifier</strong> that made the identification (bird, bat, bee, etc.), and the <strong>time</strong> of the detection.</p>
    <p><strong>Confidence scores</strong> range from 0% to 100%. A score above ~70% is generally reliable; scores of 35–50% are possible matches worth noting but treated as lower confidence. The minimum threshold is set in Settings.</p>
    <p>Use the <strong>tabs</strong> (Birds, Bats, Bees…) to filter the feed by organism group.</p>`
  },
  schedule: {
    icon: '🕐', title: 'Listening Schedule',
    body: `<p>The schedule defines <strong>when BASE listens</strong>. Windows are defined relative to solar events at your location — sunrise, sunset, or noon — so the timing shifts automatically with the seasons without manual adjustment.</p>
    <p><strong>Default windows:</strong></p>
    <ul style="padding-left:16px;margin:8px 0">
      <li><strong>Dawn chorus</strong> — 30 minutes before sunrise. The most productive window for bird song; songbirds begin calling before light to establish territory.</li>
      <li><strong>Morning song</strong> — 90 minutes after sunrise. A secondary activity peak as birds resume feeding.</li>
      <li><strong>Dusk</strong> — 60 minutes before sunset. Evening song, roost calls, and bat emergence.</li>
    </ul>
    <p>You can add custom windows (e.g. a fixed midnight bat survey) using the form below. Adaptive windows are added automatically — for example, if an owl is detected, a night window is enabled.</p>`
  },
  classifiers: {
    icon: '🐦', title: 'Classifiers & Microphones',
    body: `<p>A <strong>classifier</strong> is an AI model trained to identify a specific group of organisms from audio. BASE runs multiple classifiers simultaneously, each tuned to a different frequency range and organism type.</p>
    <ul style="padding-left:16px;margin:8px 0">
      <li><strong>🐦 Birds</strong> — BirdNET (Cornell Lab). 6,000+ species, 48 kHz. Standard microphone.</li>
      <li><strong>🦇 Bats</strong> — BatDetect2 (Univ. Edinburgh). 17 UK species, 192+ kHz. Requires an <em>ultrasonic</em> microphone.</li>
      <li><strong>🐝 Bees</strong> — BuzzDetect v1.0.1 (OSU Bee Lab). Detects insect flight buzz at 16 kHz. Standard microphone.</li>
      <li><strong>🦗 Insects</strong> — OrthopterOSS (coming). Grasshoppers and bush crickets, 2–20 kHz.</li>
      <li><strong>🌱 Soil</strong> — Blenheim Innovation. Soil Acoustic Index (beta) — worm movement, root activity, 50–2000 Hz. Best with a contact/geophone microphone.</li>
    </ul>
    <p>Each classifier can be assigned a <strong>different microphone</strong>. This means a bat ultrasonic mic and a standard bird mic can record simultaneously from different devices.</p>`
  },
  clips: {
    icon: '🎵', title: 'Audio Clip Library',
    body: `<p>BASE saves short WAV audio clips for each detected species, organised by type and species. These are the raw audio segments that triggered a detection.</p>
    <p>Clips let you <strong>verify detections by ear</strong> — listen to confirm that the model identified the sound correctly. This is especially useful for rare or unexpected species.</p>
    <p>The library applies smart retention: new species are always saved; common species clips are only kept if their confidence score exceeds a threshold, and the lowest-confidence clip is replaced when the per-species limit is reached. This prevents the disk filling with low-quality recordings of abundant species.</p>
    <p>Use the <strong>type tabs</strong> to browse by organism group, then click a species to see its clips.</p>`
  },
  reports: {
    icon: '📊', title: 'Reports',
    body: `<p>The Reports page lets you summarise, filter, and export detection data across any date range.</p>
    <p><strong>Filters:</strong> Narrow results by date range, organism type (Birds, Bats, Bees…), and individual species. Changing the type filter automatically refreshes the species dropdown to show only species of that type.</p>
    <p><strong>Downloads</strong> export filtered data as CSV files compatible with Excel, R, Python, and most ecological analysis software. <em>Detections CSV</em> has one row per individual detection; <em>Sessions CSV</em> has one row per species per listening window, with aggregate statistics.</p>
    <p><strong>Clear All Logs</strong> permanently deletes all detection and session data. This cannot be undone — download your data first.</p>`
  },
  heatmap: {
    icon: '🌡', title: 'Activity Heatmaps',
    body: `<p>Heatmaps reveal <strong>patterns in when species are active</strong> across time — something that is impossible to see in a list of individual detections.</p>
    <p><strong>Time of Day heatmap:</strong> Each row is a species; each column is an hour (00:00–23:00). Darker green indicates more detections in that hour. Dawn chorus species like Robin and Blackbird will show a clear early-morning peak. Nocturnal species like owls and bats will show activity after dusk.</p>
    <p><strong>Month of Year heatmap:</strong> Same species rows, but columns represent January through December. As data accumulates across seasons, this reveals whether a species is a summer migrant, a winter visitor, or resident year-round.</p>
    <p>These heatmaps are generated fresh from your detection data each time — the longer BASE runs, the richer the patterns become.</p>`
  },
  sai: {
    icon: '🌱', title: 'Soil Acoustic Index (SAI)',
    body: `<p>The Soil Acoustic Index (SAI) is a <strong>beta measure of biological activity in the soil</strong>, derived from audio captured by a contact microphone or geophone placed on or in the soil.</p>
    <p>After the audio is bandpass-filtered (50–2000 Hz) to remove wind, traffic, and high-frequency noise, three acoustic indices are combined:</p>
    <ul style="padding-left:16px;margin:8px 0">
      <li><strong>RMS energy</strong> — raw signal strength; scales with the intensity of activity.</li>
      <li><strong>Acoustic Complexity Index (ACI)</strong> — measures how varied the sound is across time. Biological signals (worm movement, root growth) produce irregular, complex patterns; mechanical interference (vibration, rain) produces regular, repeating patterns.</li>
      <li><strong>Spectral entropy</strong> — biological broadband activity spreads energy across many frequencies (high entropy); monotone mechanical noise concentrates it (low entropy).</li>
    </ul>
    <p><em>This is a beta feature.</em> The thresholds have not been calibrated against labelled soil recordings from Blenheim — treat SAI values as indicative and useful for relative comparison across time, not as absolute measurements.</p>`
  },
  mqtt: {
    icon: '📡', title: 'MQTT Live Feed',
    body: `<p>MQTT (Message Queuing Telemetry Transport) is a lightweight messaging protocol designed for low-bandwidth, real-time data — originally developed for satellite telemetry and now widely used in IoT and ecological monitoring.</p>
    <p>When enabled, BASE publishes every detection as a JSON message to an MQTT broker within milliseconds of the species being identified. Any connected subscriber — a dashboard, alerting system, database, or custom application — receives the data instantly.</p>
    <p><strong>Connection modes:</strong></p>
    <ul style="padding-left:16px;margin:8px 0">
      <li><strong>Direct</strong> — BASE connects straight to a broker (e.g. EMQX Cloud). Good when the machine has internet access.</li>
      <li><strong>Bridge</strong> — BASE connects to a local Mosquitto broker, which forwards to a cloud broker. Good when using a fixed local IP on a private network.</li>
    </ul>
    <p>Use the <strong>Test Connection</strong> button to verify your broker credentials before starting a session.</p>`
  },
  location: {
    icon: '📍', title: 'Recording Location',
    body: `<p>The location name, latitude, and longitude are included in every detection record — in the CSV exports, the MQTT payload, and the detection log.</p>
    <p><strong>Why it matters:</strong></p>
    <ul style="padding-left:16px;margin:8px 0">
      <li>BirdNET uses the coordinates to apply a <strong>regional species filter</strong> — it prioritises species known to occur at your location and season, improving accuracy.</li>
      <li>Location data makes exported CSVs <strong>directly importable into ecological databases</strong> (NBN Atlas, iRecord, GBIF) without manual annotation.</li>
      <li>If you run BASE at multiple sites, each deployment gets its own name, making it easy to compare data across locations.</li>
    </ul>`
  }
};

function showHelp(topic) {
  const h = HELP[topic];
  if (!h) return;
  document.getElementById('help-icon').textContent = h.icon;
  document.getElementById('help-title').textContent = h.title;
  document.getElementById('help-body').innerHTML = h.body;
  document.getElementById('help-overlay').classList.add('show');
}
function hideHelp() {
  document.getElementById('help-overlay').classList.remove('show');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') { hideHelp(); hideAbout(); } });
window.showHelp = showHelp;
window.hideHelp = hideHelp;

function helpBtn(topic) {
  return `<span class="help-icon" onclick="showHelp('${topic}')" title="Help">?</span>`;
}

/* ── About modal ── */
function showAbout() {
  const v = document.getElementById('about-version');
  const hv = document.getElementById('version');
  if (v && hv) v.textContent = hv.textContent;
  document.getElementById('about-overlay').classList.add('show');
}
function hideAbout() {
  document.getElementById('about-overlay').classList.remove('show');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideAbout(); });
window.showAbout = showAbout;
window.hideAbout = hideAbout;

/* ── Live Spectrogram ── */
const _spec = {
  running: false,
  animFrame: null,
  audioCtx: null,
  analyser: null,
  stream: null,
  imageData: null,
};

// Viridis-inspired colormap scaled to BASE's green theme
function _specColor(v) {
  // v: 0–255
  if (v < 12)  return [13, 26, 16];          // background (silent)
  if (v < 50)  return [15, 45, 80];          // dark blue
  if (v < 100) return [20, 100, 120];         // teal
  if (v < 150) return [40, 160, 100];         // green
  if (v < 200) return [130, 210, 60];         // yellow-green
  if (v < 230) return [230, 180, 30];         // amber
  return            [255, 80,  30];           // hot red-orange
}

function _buildFreqAxis(sampleRate, logScale) {
  const el = document.getElementById('spec-axis');
  if (!el) return;
  const nyquist = sampleRate / 2;
  const labels = logScale
    ? [nyquist, 16000, 8000, 4000, 2000, 1000, 500, 200, 50]
    : [nyquist, Math.round(nyquist*0.75), Math.round(nyquist*0.5), Math.round(nyquist*0.25), 0];
  el.innerHTML = labels
    .map(f => `<span>${f >= 1000 ? (f/1000).toFixed(f%1000?1:0)+'k' : f}</span>`)
    .join('');
}

// Populate the spectrogram mic dropdown from pactl (server) + browser device APIs.
// Merges both sources so Linux/PipeWire users see all physical inputs.
async function _populateSpecDevices() {
  try {
    const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
    tmp.getTracks().forEach(t => t.stop());

    const [browserDevices, serverData] = await Promise.all([
      navigator.mediaDevices.enumerateDevices(),
      api.get('/api/devices').catch(() => ({ devices: [] })),
    ]);

    const sel = document.getElementById('spec-device');
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">System default</option>';

    serverData.devices.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.name;
      opt.textContent = `${d.is_default ? '★ ' : ''}${d.label || d.name} (${(d.sample_rate/1000).toFixed(0)}kHz)`;
      sel.appendChild(opt);
    });

    const serverNames = new Set(serverData.devices.map(d => d.label || d.name));
    browserDevices
      .filter(d => d.kind === 'audioinput' && d.deviceId !== 'default' && d.deviceId !== '')
      .forEach(d => {
        if (!serverNames.has(d.label)) {
          const opt = document.createElement('option');
          opt.value = d.deviceId;
          opt.textContent = d.label || `Microphone (${d.deviceId.slice(0, 8)})`;
          sel.appendChild(opt);
        }
      });

    // Restore previous selection if still available
    if (prev && sel.querySelector(`option[value="${CSS.escape(prev)}"]`)) sel.value = prev;
  } catch (_) {}
}

// Sync the spectrogram mic to whichever pipeline is currently running,
// so the visual and the detector always show the same source.
function _syncSpecToRunningDevice() {
  const sel = document.getElementById('spec-device');
  if (!sel || !state.status) return;
  const running = Object.values(state.status.pipelines || {}).find(p => p.state !== 'idle');
  if (!running || !running.device_name) return;
  for (const opt of sel.options) {
    if (opt.value && opt.textContent.includes(running.device_name)) {
      if (sel.value === opt.value) return;
      sel.value = opt.value;
      if (_spec.running) { _stopSpectrogram(); _startSpectrogram(); }
      return;
    }
  }
}

async function changeSpecDevice() {
  if (!_spec.running) return;
  _stopSpectrogram();
  await _startSpectrogram();
}

async function toggleSpectrogram() {
  const panel = document.getElementById('spec-panel');
  const btn   = document.getElementById('btn-spec-toggle');
  if (_spec.running) {
    _stopSpectrogram();
    panel.classList.remove('show');
    btn.textContent = '▶ Start';
    return;
  }
  panel.classList.add('show');
  btn.textContent = '⟳ Starting…';
  await _populateSpecDevices();
  await _startSpectrogram();
  btn.textContent = '■ Stop';
}

async function _startSpectrogram() {
  const deviceId = document.getElementById('spec-device')?.value || null;
  // Use 'ideal' rather than 'exact' — PipeWire/pactl source names work with ideal
  // but may fail with exact if the browser maps them differently
  const constraints = { audio: deviceId ? { deviceId: { ideal: deviceId } } : true, video: false };
  try {
    _spec.stream = await navigator.mediaDevices.getUserMedia(constraints);
    _spec.audioCtx = new AudioContext();
    _spec.analyser = _spec.audioCtx.createAnalyser();
    _spec.analyser.fftSize = 4096;          // 2048 bins → good freq resolution
    _spec.analyser.smoothingTimeConstant = 0.4;
    _spec.audioCtx.createMediaStreamSource(_spec.stream).connect(_spec.analyser);

    const canvas = document.getElementById('spec-canvas');
    canvas.width = canvas.offsetWidth || 1200;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#0d1a10';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    _buildFreqAxis(_spec.audioCtx.sampleRate,
      document.getElementById('spec-log')?.checked || false);

    _spec.running = true;
    _specDraw();
  } catch (err) {
    toast(`Spectrogram: ${err.message}`, 'error', 5000);
    document.getElementById('btn-spec-toggle').textContent = '▶ Start';
  }
}

function _stopSpectrogram() {
  _spec.running = false;
  if (_spec.animFrame) cancelAnimationFrame(_spec.animFrame);
  if (_spec.stream) _spec.stream.getTracks().forEach(t => t.stop());
  if (_spec.audioCtx) _spec.audioCtx.close();
  _spec.analyser = _spec.audioCtx = _spec.stream = null;
}

function _specDraw() {
  if (!_spec.running) return;
  const canvas = document.getElementById('spec-canvas');
  if (!canvas) { _spec.running = false; return; }
  const ctx = canvas.getContext('2d');
  const analyser = _spec.analyser;
  const logScale = document.getElementById('spec-log')?.checked || false;

  const bins = analyser.frequencyBinCount;   // 2048
  const data = new Uint8Array(bins);
  analyser.getByteFrequencyData(data);

  const w = canvas.width;
  const h = canvas.height;

  // Scroll left by 2px for readable speed
  const scroll = 2;
  const img = ctx.getImageData(scroll, 0, w - scroll, h);
  ctx.putImageData(img, 0, 0);

  // Draw new columns on the right
  const col = ctx.createImageData(scroll, h);
  const px  = col.data;

  for (let y = 0; y < h; y++) {
    let binIndex;
    if (logScale) {
      // Logarithmic mapping: maps low frequencies to more vertical space
      const t = 1 - y / h;
      binIndex = Math.floor(Math.pow(bins, t));
      binIndex = Math.min(binIndex, bins - 1);
    } else {
      binIndex = Math.floor((1 - y / h) * (bins - 1));
    }
    const value = data[binIndex];
    const [r, g, b] = _specColor(value);
    for (let xi = 0; xi < scroll; xi++) {
      const i = (y * scroll + xi) * 4;
      px[i] = r; px[i+1] = g; px[i+2] = b; px[i+3] = 255;
    }
  }
  ctx.putImageData(col, w - scroll, 0);

  _spec.animFrame = requestAnimationFrame(_specDraw);
}

window.toggleSpectrogram = toggleSpectrogram;

/* ── Boot ── */
router.init();
ws.connect();
pollStatus();
setInterval(pollStatus, POLL_INTERVAL);

window.deleteWindow = deleteWindow;
window.loadClips = loadClips;
window.filterClips = filterClips;
window.deleteClip = deleteClip;
window.startDevice = startDevice;
window.stopDevice = stopDevice;
window.setFilter = setFilter;
window.changeSpecDevice = changeSpecDevice;
