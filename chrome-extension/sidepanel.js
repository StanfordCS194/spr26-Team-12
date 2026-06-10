/**
 * Veritas Chrome Extension — sidepanel.js
 *
 * Live fact-check side panel. Captures audio from the current tab using
 * chrome.tabCapture, records a configurable window (30/60/90s), then feeds
 * the audio through the same Veritas pipeline as the popup:
 *   /api/process/audio → /api/claims/extract → review → /api/clip-report
 *
 * State machine:
 *   live_idle → recording → processing → review → checking → report | error
 *
 * Important: chrome.tabCapture.capture() must be called directly from a
 * user-gesture handler (the "Start recording" button click). It cannot be
 * proxied through the service worker.
 */

// ── Constants ──────────────────────────────────────────────────────────────
const DURATIONS = [30, 60, 90];
const RING_RADIUS = 46;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS; // ≈ 289

// ── State ──────────────────────────────────────────────────────────────────
let state       = 'live_idle';
let duration    = 60;        // selected recording duration in seconds
let creatorName = '';
let transcript  = '';
let claims      = [];
let report      = null;
let errorMsg    = '';

let mediaRecorder   = null;
let audioChunks     = [];
let captureStream   = null;
let countdownTimer  = null;
let secondsLeft     = 0;
let abortController = null;

// Snapshot of GET /api/health from the most recent poll. Used to gate the
// Start-recording button when transcription is unavailable (demo mode, no
// Whisper key). null means we haven't checked yet.
let healthInfo = null;

// ── DOM ────────────────────────────────────────────────────────────────────
const app = document.getElementById('app');

document.getElementById('settingsBtn').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

// ── Settings ───────────────────────────────────────────────────────────────
async function getBase() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ backendUrl: 'http://localhost:8000' }, ({ backendUrl }) => {
      resolve((backendUrl || 'http://localhost:8000').replace(/\/$/, ''));
    });
  });
}

// ── API helpers ─────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const base = await getBase();
  const res = await fetch(`${base}${path}`, {
    ...options,
    signal: abortController ? abortController.signal : undefined,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Backend error ${res.status}`);
  }
  return res.json();
}

async function apiFetchForm(path, formData) {
  const base = await getBase();
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    body: formData,
    signal: abortController ? abortController.signal : undefined,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Backend error ${res.status}`);
  }
  return res.json();
}

// ── Utilities ───────────────────────────────────────────────────────────────
function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

const DIR_LABELS = {
  supports: 'Supported',
  partially_supports: 'Partly supported',
  mixed: 'Mixed',
  weak: 'Weak evidence',
  contradicts: 'Contradicted',
  insufficient: 'No verdict',
};
function dirLabel(d) { return DIR_LABELS[d] || d.replace(/_/g, ' '); }

function scoreColor(score) {
  if (score >= 70) return 'var(--green)';
  if (score >= 45) return 'var(--yellow)';
  return 'var(--red)';
}

// ── Render dispatcher ────────────────────────────────────────────────────────
function render() {
  app.innerHTML = '';
  if      (state === 'live_idle')  renderIdle();
  else if (state === 'recording')  renderRecording();
  else if (state === 'processing'
        || state === 'checking')   renderLoading();
  else if (state === 'review')     renderReview();
  else if (state === 'report')     renderReport();
  else if (state === 'error')      renderError();
}

// ── live_idle ────────────────────────────────────────────────────────────────
function renderIdle() {
  // Prefer the explicit transcription_configured flag (set when either Groq
  // or OpenAI keys exist). Fall back to openai_configured for older backends.
  const providers = (healthInfo && healthInfo.providers) || {};
  const transcriptionDown =
    healthInfo &&
    (providers.transcription_configured === false ||
      (providers.transcription_configured === undefined &&
        providers.openai_configured === false));
  const demoBanner = transcriptionDown
    ? `
      <div class="info-banner" style="border-color:#f59e0b;background:rgba(245,158,11,0.08);">
        <strong>Audio transcription is unavailable.</strong> Add a free
        <code>GROQ_API_KEY</code> (or <code>OPENAI_API_KEY</code>) to
        <code>backend/.env</code> and restart the server. Without it the
        side panel can't turn captured audio into text — use the popup
        with pasted text instead.
        <br><br>
        <button class="btn-ghost" id="openOptsBtn">Open settings</button>
      </div>
    `
    : '';

  app.innerHTML = `
    ${demoBanner}
    <div class="info-banner">
      <strong>How it works:</strong> Hit "Start recording", then watch the video normally.
      Veritas captures the tab's audio for the chosen window, transcribes it, and
      fact-checks any fitness claims it finds.
      <br><br>
      <strong>Expect ~60–120 s</strong> from pressing Stop to seeing results.
    </div>

    <div class="section-label">Recording window</div>
    <div class="duration-row" id="durRow">
      ${DURATIONS.map(d => `
        <button class="dur-btn ${d === duration ? 'selected' : ''}" data-dur="${d}">
          ${d}s
        </button>
      `).join('')}
    </div>

    <input type="text" id="creatorInput"
      placeholder="Creator handle (optional, e.g. @jeffnippard)" />

    <div class="btn-row">
      <button class="btn-rec" id="startBtn" ${transcriptionDown ? 'disabled' : ''}>
        ⏺ Start recording${transcriptionDown ? ' (transcription off)' : ''}
      </button>
    </div>
  `;
  const optsBtn = document.getElementById('openOptsBtn');
  if (optsBtn) optsBtn.addEventListener('click', () => chrome.runtime.openOptionsPage());

  document.querySelectorAll('.dur-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      duration = parseInt(btn.dataset.dur);
      document.querySelectorAll('.dur-btn').forEach(b => b.classList.toggle('selected', b === btn));
    });
  });

  document.getElementById('creatorInput').addEventListener('input', e => {
    creatorName = e.target.value.trim();
  });
  if (creatorName) document.getElementById('creatorInput').value = creatorName;

  // START RECORDING — must run from this user-gesture click handler.
  document.getElementById('startBtn').addEventListener('click', async () => {
    try {
      captureStream = await acquireTabAudioStream();
    } catch (err) {
      errorMsg = `Could not capture tab audio: ${err.message || err}. Make sure the tab is playing audio on a regular http(s) page (chrome:// pages are blocked).`;
      state = 'error';
      render();
      return;
    }

    if (!captureStream) {
      errorMsg = 'Tab audio capture was denied or the tab has no audio. Start video playback first.';
      state = 'error';
      render();
      return;
    }

    startRecording(captureStream);
  });
}

// chrome.tabCapture.capture() is callback-only (no promise overload), and on
// recent Chrome versions it sometimes fails when invoked from the side panel
// context. We try the legacy callback API first, then fall back to the modern
// MV3 streamId flow: getMediaStreamId() → getUserMedia({ chromeMediaSource }).
async function acquireTabAudioStream() {
  let stream = await tryLegacyTabCapture();
  if (!stream) stream = await tryStreamIdCapture();
  if (stream) pipePlaybackToSpeakers(stream);
  return stream;
}

function tryLegacyTabCapture() {
  return new Promise((resolve) => {
    try {
      chrome.tabCapture.capture({ audio: true, video: false }, (stream) => {
        if (chrome.runtime.lastError || !stream) {
          resolve(null);
        } else {
          resolve(stream);
        }
      });
    } catch {
      resolve(null);
    }
  });
}

async function tryStreamIdCapture() {
  const [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!activeTab || !activeTab.id) {
    throw new Error('No active tab to capture');
  }
  const streamId = await new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: activeTab.id }, (id) => {
      if (chrome.runtime.lastError || !id) {
        reject(new Error(chrome.runtime.lastError?.message || 'No stream id'));
      } else {
        resolve(id);
      }
    });
  });
  return await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId },
    },
    video: false,
  });
}

// Both tabCapture paths in current Chrome route audio AWAY from the speakers
// while we record (the user hears silence). Wire the captured stream into an
// AudioContext destination so playback continues uninterrupted. We keep the
// context on the stream so it isn't garbage-collected mid-recording.
let _playbackCtx = null;
function pipePlaybackToSpeakers(stream) {
  try {
    if (_playbackCtx) { try { _playbackCtx.close(); } catch {} }
    _playbackCtx = new AudioContext();
    _playbackCtx.createMediaStreamSource(stream).connect(_playbackCtx.destination);
  } catch {}
}

// ── recording ────────────────────────────────────────────────────────────────
function startRecording(stream) {
  audioChunks = [];
  secondsLeft = duration;

  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm';

  mediaRecorder = new MediaRecorder(stream, { mimeType });
  mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
  mediaRecorder.onstop = () => {
    stopStreamTracks(stream);
    const blob = new Blob(audioChunks, { type: mimeType });
    processAudio(blob, mimeType);
  };

  mediaRecorder.start(1000); // collect chunks every second
  state = 'recording';
  render();
  startCountdown();
}

function startCountdown() {
  updateRing(secondsLeft, duration);

  countdownTimer = setInterval(() => {
    secondsLeft -= 1;
    updateRing(secondsLeft, duration);

    if (secondsLeft <= 0) {
      clearInterval(countdownTimer);
      countdownTimer = null;
      stopRecordingAndProcess();
    }
  }, 1000);
}

function updateRing(left, total) {
  const fill = document.getElementById('ringFill');
  const secsEl = document.getElementById('countdownSecs');
  if (!fill || !secsEl) return;
  const progress = left / total;
  fill.style.strokeDashoffset = RING_CIRCUMFERENCE * (1 - progress);
  secsEl.textContent = left;
}

function renderRecording() {
  app.innerHTML = `
    <div class="recording-hero">
      <div class="rec-label-row">
        <div class="rec-dot"></div>
        <span>Recording tab audio…</span>
      </div>

      <div class="countdown-ring-wrap">
        <svg viewBox="0 0 110 110">
          <circle class="ring-track" cx="55" cy="55" r="${RING_RADIUS}" />
          <circle
            class="ring-fill"
            id="ringFill"
            cx="55" cy="55" r="${RING_RADIUS}"
            stroke-dasharray="${RING_CIRCUMFERENCE}"
            stroke-dashoffset="0"
          />
        </svg>
        <div class="countdown-text">
          <div class="countdown-secs" id="countdownSecs">${secondsLeft}</div>
          <div class="countdown-unit">sec left</div>
        </div>
      </div>

      <div class="rec-hint">Keep this panel open. The video will keep playing.</div>

      <div class="btn-row">
        <button class="btn-primary" id="stopBtn">Stop &amp; fact-check now</button>
        <button class="btn-ghost"   id="cancelRecBtn">Cancel</button>
      </div>
    </div>
  `;

  // Initialize ring to current progress (needed when render() is called mid-recording)
  updateRing(secondsLeft, duration);

  document.getElementById('stopBtn').addEventListener('click', () => {
    clearInterval(countdownTimer);
    countdownTimer = null;
    stopRecordingAndProcess();
  });

  document.getElementById('cancelRecBtn').addEventListener('click', () => {
    clearInterval(countdownTimer);
    countdownTimer = null;
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.onstop = null; // prevent processing
      mediaRecorder.stop();
    }
    stopStreamTracks(captureStream);
    captureStream = null;
    state = 'live_idle';
    render();
  });
}

function stopRecordingAndProcess() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop(); // triggers onstop → processAudio
  }
}

function stopStreamTracks(stream) {
  if (stream) stream.getTracks().forEach(t => t.stop());
  if (_playbackCtx) {
    try { _playbackCtx.close(); } catch {}
    _playbackCtx = null;
  }
}

// ── Audio processing pipeline ─────────────────────────────────────────────
async function processAudio(blob, mimeType) {
  abortController = new AbortController();
  state = 'processing';
  render();

  try {
    // 1. Transcribe
    const ext = mimeType.includes('ogg') ? 'ogg' : 'webm';
    const form = new FormData();
    form.append('audio', blob, `live_capture.${ext}`);
    const processed = await apiFetchForm('/api/process/audio', form);
    transcript = processed.text || '';

    if (!transcript.trim()) {
      errorMsg = 'No speech detected in the recording. Make sure the video is playing and the volume is up.';
      state = 'error';
      render();
      return;
    }

    // 2. Extract claims
    const extracted = await apiFetch('/api/claims/extract', {
      method: 'POST',
      body: JSON.stringify({ transcript, source: 'audio' }),
    });
    claims = extracted.claims || [];

    if (claims.length === 0) {
      errorMsg = 'No checkable fitness claims found in this window. Try a longer recording or a different segment.';
      state = 'error';
      render();
      return;
    }

    state = 'review';
  } catch (err) {
    if (err.name === 'AbortError') { state = 'live_idle'; render(); return; }
    const raw = err.message || String(err);
    if (/GROQ_API_KEY|OPENAI_API_KEY|transcription requires/i.test(raw)) {
      errorMsg =
        'Audio transcription is not configured on the backend. Add a free ' +
        'GROQ_API_KEY (or OPENAI_API_KEY) to backend/.env and restart the server, ' +
        'or use the popup with pasted text instead.';
    } else {
      errorMsg = raw;
    }
    state = 'error';
  }
  render();
}

// ── processing / checking ────────────────────────────────────────────────────
function renderLoading() {
  const isChecking = state === 'checking';
  app.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <div class="loading-msg">
        ${isChecking ? 'Fact-checking with two AI agents…' : 'Transcribing and extracting claims…'}
      </div>
      <div class="loading-sub">
        ${isChecking ? 'This takes 30–90 seconds' : 'Usually under 30 seconds'}
      </div>
      <div class="btn-row" style="justify-content:center;margin-top:16px;">
        <button class="btn-ghost" id="cancelBtn">Cancel</button>
      </div>
    </div>
  `;
  document.getElementById('cancelBtn').addEventListener('click', () => {
    abortController && abortController.abort();
    state = isChecking ? 'review' : 'live_idle';
    render();
  });
}

// ── review ────────────────────────────────────────────────────────────────────
function renderReview() {
  const sel = () => claims.filter(c => c.selected !== false && c.normalized_claim.trim());

  const itemsHtml = claims.map((claim, i) => `
    <li class="claim-item">
      <input type="checkbox" id="ck_${i}" data-index="${i}"
        ${claim.selected !== false ? 'checked' : ''} />
      <label class="claim-label" for="ck_${i}">
        <div class="claim-text">${esc(claim.normalized_claim)}</div>
        <div class="claim-tags">
          <span class="tag">${esc(claim.category.replace(/_/g, ' '))}</span>
          ${claim.risk_level === 'high' ? '<span class="tag tag-high">high risk</span>' : ''}
        </div>
      </label>
    </li>
  `).join('');

  app.innerHTML = `
    <div class="review-banner">
      <strong>${claims.length} claim${claims.length !== 1 ? 's' : ''}</strong> extracted — uncheck any to skip
    </div>

    <details class="transcript-preview" style="cursor:pointer">
      <summary style="font-weight:600;color:var(--muted);font-size:11px;list-style:none;margin-bottom:4px">
        Transcript ▾
      </summary>
      ${esc(transcript)}
    </details>

    <ul class="claims-list">${itemsHtml}</ul>

    <div class="btn-row">
      <button class="btn-primary" id="checkBtn" ${sel().length === 0 ? 'disabled' : ''}>
        Fact-check ${sel().length} claim${sel().length !== 1 ? 's' : ''}
      </button>
      <button class="btn-ghost" id="backBtn">Record again</button>
    </div>
  `;

  function refreshBtn() {
    const n = sel().length;
    const btn = document.getElementById('checkBtn');
    btn.disabled = n === 0;
    btn.textContent = `Fact-check ${n} claim${n !== 1 ? 's' : ''}`;
  }

  document.querySelectorAll('.claim-item input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      claims[parseInt(cb.dataset.index)].selected = cb.checked;
      refreshBtn();
    });
  });

  document.getElementById('checkBtn').addEventListener('click', runReport);
  document.getElementById('backBtn').addEventListener('click', () => {
    state = 'live_idle'; transcript = ''; claims = [];
    render();
  });
}

// ── checking → report ────────────────────────────────────────────────────────
async function runReport() {
  abortController = new AbortController();
  state = 'checking';
  render();
  try {
    report = await apiFetch('/api/clip-report', {
      method: 'POST',
      body: JSON.stringify({
        transcript,
        claims,
        source: 'audio',
        creator_name: creatorName || null,
        brand_name: null,
      }),
    });
    state = 'report';
  } catch (err) {
    if (err.name === 'AbortError') { state = 'review'; render(); return; }
    errorMsg = err.message || String(err);
    state = 'error';
  }
  render();
}

// ── report ────────────────────────────────────────────────────────────────────
function renderReport() {
  const score = report.clip_credibility_score;

  const claimsHtml = report.claims.map(item => {
    const dir = item.agreement.final_direction;
    const sourcesHtml = item.sources.slice(0, 3).map(s => `
      <li>
        <a class="source-link" href="${esc(s.url)}" target="_blank" rel="noreferrer"
           title="${esc(s.title)}">${esc(s.title)}</a>
      </li>
    `).join('');
    return `
      <div class="claim-result">
        <div class="claim-result-head">
          <div class="claim-result-text">${esc(item.claim.normalized_claim)}</div>
          <span class="dir-badge dir-${dir}">${dirLabel(dir)}</span>
        </div>
        <div class="claim-summary">${esc(item.agreement.summary || '')}</div>
        ${item.sources.length > 0 ? `<ul class="sources-list">${sourcesHtml}</ul>` : ''}
      </div>
    `;
  }).join('');

  app.innerHTML = `
    <div class="report-hero">
      <div class="score-block">
        <div class="score-num" style="color:${scoreColor(score)}">${score}</div>
        <div class="score-label">/ 100</div>
      </div>
      <div class="overall-summary">${esc(report.overall_summary)}</div>
    </div>
    ${claimsHtml}
    <div class="footer-actions">
      <button class="btn-ghost"   id="againBtn">Record another window</button>
      <button class="btn-primary" id="openAppBtn">Open full app ↗</button>
    </div>
  `;

  document.getElementById('againBtn').addEventListener('click', () => {
    state = 'live_idle'; transcript = ''; claims = []; report = null;
    render();
  });

  document.getElementById('openAppBtn').addEventListener('click', () => {
    chrome.storage.sync.get({ frontendUrl: 'https://veritas-ruby.vercel.app' }, ({ frontendUrl }) => {
      const base = (frontendUrl || 'https://veritas-ruby.vercel.app').replace(/\/$/, '');
      const params = new URLSearchParams();
      const handoffText = (transcript || '').trim();
      if (handoffText) params.set('text', handoffText.slice(0, 12000));
      if (creatorName) params.set('creator', creatorName.slice(0, 120));
      params.set('source', 'extension');
      const query = params.toString();
      chrome.tabs.create({ url: query ? `${base}/?${query}` : base });
    });
  });
}

// ── error ─────────────────────────────────────────────────────────────────────
function renderError() {
  app.innerHTML = `
    <div class="error-box">${esc(errorMsg)}</div>
    <div class="btn-row">
      <button class="btn-ghost" id="retryBtn">Try again</button>
    </div>
  `;
  document.getElementById('retryBtn').addEventListener('click', () => {
    state = 'live_idle'; errorMsg = '';
    render();
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const base = await getBase();
    const res = await fetch(`${base}/api/health`);
    if (res.ok) {
      healthInfo = await res.json();
      if (state === 'live_idle') render();
    }
  } catch {
    // Backend unreachable — leave healthInfo as is; user still sees the
    // generic info banner. The capture call will surface its own error.
  }
}

render();
checkHealth();
