/**
 * Veritas Chrome Extension — popup.js
 *
 * State machine: idle → processing → review → checking → report | error
 *
 * API calls go to the configured backend URL (default http://localhost:8000).
 * The same endpoints used by the web frontend are reused here.
 */

const DEMO_TRANSCRIPT =
  'Creatine makes you go bald, BCAAs are required if you want to build muscle, and tongkat ali can double your testosterone naturally.';

// ── State ──────────────────────────────────────────────────────────────────
let state = 'idle';
let transcript = '';
let claims = [];
let report = null;
let errorMsg = '';
let creatorName = '';
let abortController = null;

// ── DOM root ───────────────────────────────────────────────────────────────
const app = document.getElementById('app');

// ── Settings ───────────────────────────────────────────────────────────────
document.getElementById('settingsBtn').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

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

// ── Direction labels ────────────────────────────────────────────────────────
const DIR_LABELS = {
  supports: 'Supported',
  partially_supports: 'Partly supported',
  mixed: 'Mixed',
  weak: 'Weak evidence',
  contradicts: 'Contradicted',
  insufficient: 'No verdict',
};

function dirLabel(d) {
  return DIR_LABELS[d] || d.replace(/_/g, ' ');
}

// ── Score colour ────────────────────────────────────────────────────────────
function scoreColor(score) {
  if (score >= 70) return 'var(--green)';
  if (score >= 45) return 'var(--yellow)';
  return 'var(--red)';
}

// ── XSS-safe text insertion ─────────────────────────────────────────────────
function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

// ── Render dispatcher ───────────────────────────────────────────────────────
function render() {
  app.innerHTML = '';
  if (state === 'idle')                   renderIdle();
  else if (state === 'processing' ||
           state === 'checking')          renderLoading();
  else if (state === 'review')            renderReview();
  else if (state === 'report')            renderReport();
  else if (state === 'error')             renderError();
}

// ── Idle ────────────────────────────────────────────────────────────────────
function renderIdle() {
  app.innerHTML = `
    <textarea
      id="inputText"
      placeholder="Paste a transcript, caption, or fitness claim…"
      maxlength="12000"
    ></textarea>
    <div class="char-count" id="charCount">0 / 12000</div>

    <input
      type="text"
      id="creatorInput"
      placeholder="Creator handle (optional, e.g. @fitnessguru)"
    />

    <div class="btn-row">
      <button class="btn-primary" id="extractBtn" disabled>Extract claims</button>
      <button class="btn-ghost"   id="demoBtn">Try demo</button>
    </div>
    <div class="btn-row" style="margin-top:8px;">
      <button class="btn-ghost" id="liveBtn" style="width:100%;justify-content:center;">
        ⏺ Live fact-check (side panel)
      </button>
    </div>
  `;

  const textarea    = document.getElementById('inputText');
  const charCount   = document.getElementById('charCount');
  const extractBtn  = document.getElementById('extractBtn');
  const creatorInput= document.getElementById('creatorInput');

  function updateExtractBtn() {
    extractBtn.disabled = textarea.value.trim().length < 5;
  }

  textarea.addEventListener('input', () => {
    charCount.textContent = `${textarea.value.length} / 12000`;
    updateExtractBtn();
  });

  creatorInput.addEventListener('input', () => {
    creatorName = creatorInput.value.trim();
  });

  extractBtn.addEventListener('click', () => {
    const text = textarea.value.trim();
    if (text) runExtract(text);
  });

  document.getElementById('demoBtn').addEventListener('click', () => {
    textarea.value = DEMO_TRANSCRIPT;
    charCount.textContent = `${DEMO_TRANSCRIPT.length} / 12000`;
    updateExtractBtn();
  });

  document.getElementById('liveBtn').addEventListener('click', () => {
    // Open the side panel for the tab that triggered this popup, then close the popup.
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tabId = tabs[0] && tabs[0].id;
      if (tabId) {
        chrome.sidePanel.open({ tabId }).catch(() => {
          // sidePanel.open may not be available on all pages (e.g. chrome:// URLs).
          chrome.runtime.openOptionsPage(); // fallback: open settings
        });
      }
      window.close();
    });
  });

  // Pick up text forwarded by the context menu (right-click → "Fact-check with Veritas").
  chrome.storage.session.get('pendingText', ({ pendingText }) => {
    if (pendingText) {
      textarea.value = pendingText;
      charCount.textContent = `${pendingText.length} / 12000`;
      updateExtractBtn();
      chrome.storage.session.remove('pendingText');
      chrome.action.setBadgeText({ text: '' });
    }
  });
}

// ── Loading ─────────────────────────────────────────────────────────────────
function renderLoading() {
  const isChecking = state === 'checking';
  app.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <div class="loading-msg">${isChecking ? 'Fact-checking with two AI agents…' : 'Extracting claims…'}</div>
      ${isChecking ? '<div class="loading-sub">This takes 30–60 seconds</div>' : ''}
      <div class="btn-row" style="justify-content:center; margin-top:14px;">
        <button class="btn-ghost" id="cancelBtn">Cancel</button>
      </div>
    </div>
  `;
  document.getElementById('cancelBtn').addEventListener('click', () => {
    abortController && abortController.abort();
    state = isChecking ? 'review' : 'idle';
    render();
  });
}

// ── Review ───────────────────────────────────────────────────────────────────
function renderReview() {
  const sel = () => claims.filter((c) => c.selected !== false && c.normalized_claim.trim());

  const itemsHtml = claims.map((claim, i) => `
    <li class="claim-item" data-index="${i}">
      <input
        type="checkbox"
        id="ck_${i}"
        data-index="${i}"
        ${claim.selected !== false ? 'checked' : ''}
      />
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
      <strong>${claims.length} claim${claims.length !== 1 ? 's' : ''}</strong> extracted —
      uncheck any you want to skip
    </div>
    <ul class="claims-list">${itemsHtml}</ul>
    <div class="btn-row">
      <button class="btn-primary" id="checkBtn" ${sel().length === 0 ? 'disabled' : ''}>
        Fact-check ${sel().length} claim${sel().length !== 1 ? 's' : ''}
      </button>
      <button class="btn-ghost" id="backBtn">Start over</button>
    </div>
  `;

  function refreshCheckBtn() {
    const n = sel().length;
    const btn = document.getElementById('checkBtn');
    btn.disabled = n === 0;
    btn.textContent = `Fact-check ${n} claim${n !== 1 ? 's' : ''}`;
  }

  document.querySelectorAll('.claim-item input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener('change', () => {
      claims[parseInt(cb.dataset.index)].selected = cb.checked;
      refreshCheckBtn();
    });
  });

  document.getElementById('checkBtn').addEventListener('click', runReport);
  document.getElementById('backBtn').addEventListener('click', () => {
    state = 'idle'; transcript = ''; claims = [];
    render();
  });
}

// ── Report ───────────────────────────────────────────────────────────────────
function renderReport() {
  const claimsHtml = report.claims.map((item) => {
    const dir = item.agreement.final_direction;
    const sourcesHtml = item.sources.slice(0, 3).map((s) => `
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

  const score = report.clip_credibility_score;

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
      <button class="btn-ghost"   id="resetBtn">Check another</button>
      <button class="btn-primary" id="openAppBtn">Open full app ↗</button>
    </div>
  `;

  document.getElementById('resetBtn').addEventListener('click', () => {
    state = 'idle'; transcript = ''; claims = []; report = null;
    render();
  });

  document.getElementById('openAppBtn').addEventListener('click', () => {
    chrome.storage.sync.get({ frontendUrl: 'http://localhost:5173' }, ({ frontendUrl }) => {
      chrome.tabs.create({ url: frontendUrl || 'http://localhost:5173' });
    });
  });
}

// ── Error ────────────────────────────────────────────────────────────────────
function renderError() {
  app.innerHTML = `
    <div class="error-box">${esc(errorMsg)}</div>
    <div class="btn-row">
      <button class="btn-ghost" id="retryBtn">Start over</button>
    </div>
  `;
  document.getElementById('retryBtn').addEventListener('click', () => {
    state = 'idle'; errorMsg = '';
    render();
  });
}

// ── Actions ──────────────────────────────────────────────────────────────────
async function runExtract(text) {
  abortController = new AbortController();
  state = 'processing';
  render();
  try {
    const processed = await apiFetch('/api/process/text', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
    transcript = processed.text;

    const extracted = await apiFetch('/api/claims/extract', {
      method: 'POST',
      body: JSON.stringify({ transcript, source: 'text' }),
    });
    claims = extracted.claims || [];
    state = claims.length > 0 ? 'review' : 'error';
    if (state === 'error') errorMsg = 'No checkable claims found in the text. Try pasting a longer transcript or a specific claim.';
  } catch (err) {
    if (err.name === 'AbortError') { state = 'idle'; render(); return; }
    errorMsg = err.message || String(err);
    state = 'error';
  }
  render();
}

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
        source: 'text',
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

// ── Boot ─────────────────────────────────────────────────────────────────────
render();
