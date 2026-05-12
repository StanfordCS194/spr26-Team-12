/**
 * Veritas Chrome Extension — popup.js
 *
 * State machine: idle → processing → review → checking → report | error
 *
 * All network calls go through apiFetch() against the user-configured backendUrl.
 * No URLs from page content are ever fetched (SSRF-safe). All API/user strings
 * are rendered through esc() / textContent (XSS-safe).
 */

const DEMO_TRANSCRIPT =
  'Creatine makes you go bald, BCAAs are required if you want to build muscle, and tongkat ali can double your testosterone naturally.';

const DEFAULT_BACKEND = 'http://localhost:8000';

// Loading-phase choreography. The backend doesn't stream progress, so we
// fake a smooth multi-step indicator that completes in time with the real
// network call. Roughly tuned to the typical 30-60s clip-report runtime.
const CHECK_PHASES = [
  { label: 'Normalizing input',         estMs: 600  },
  { label: 'Extracting claims',         estMs: 5000 },
  { label: 'Searching sources',         estMs: 8000 },
  { label: 'Cross-checking with agents', estMs: 25000 },
  { label: 'Building agreement',        estMs: 4000 },
];

// ── State ──────────────────────────────────────────────────────────────────
let state = 'idle';
let transcript = '';
let claims = [];
let report = null;
let errorMsg = '';
let creatorName = '';
let abortController = null;
let backendHealth = null;  // { ok, demo_mode } | null while unknown | { offline: true }
let loadingPhase = 0;
let loadingTimer = null;
let lastReportMeta = null; // { score, summary, savedAt }

// ── DOM root ───────────────────────────────────────────────────────────────
const app = document.getElementById('app');

// ── Settings + header status pill ──────────────────────────────────────────
document.getElementById('settingsBtn').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});
document.getElementById('statusPill').addEventListener('click', () => {
  // Re-poll first; if still offline, surface settings.
  checkHealth(true).then((h) => {
    if (!h || h.offline) chrome.runtime.openOptionsPage();
  });
});

async function getBase() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND }, ({ backendUrl }) => {
      resolve((backendUrl || DEFAULT_BACKEND).replace(/\/$/, ''));
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

async function checkHealth(silent = false) {
  const pill = document.getElementById('statusPill');
  if (!silent) setPill('checking', '…', 'Checking backend…');
  try {
    const base = await getBase();
    const res = await fetch(`${base}/api/health`, { method: 'GET' });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    backendHealth = { ok: !!data.ok, demo_mode: !!data.demo_mode };
    if (!backendHealth.ok) {
      setPill('offline', 'Offline', 'Backend reachable but reports not-ok');
    } else if (backendHealth.demo_mode) {
      setPill('demo', 'Demo', 'Backend in demo mode — fact-checks use canned results');
    } else {
      setPill('live', 'Live', 'Backend live — real AI fact-check pipeline');
    }
  } catch (_err) {
    backendHealth = { offline: true };
    setPill('offline', 'Offline', 'Cannot reach backend. Click to open settings.');
  }
  // Re-render whatever state we're in so banners update.
  if (state === 'idle' || state === 'error') render();
  return backendHealth;
}

function setPill(kind, label, tooltip) {
  const pill = document.getElementById('statusPill');
  pill.className = `status-pill status-pill-${kind}`;
  pill.title = tooltip || '';
  pill.querySelector('.status-label').textContent = label;
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
  return DIR_LABELS[d] || String(d || '').replace(/_/g, ' ');
}

function scoreColor(score) {
  if (score >= 70) return 'var(--green)';
  if (score >= 45) return 'var(--yellow)';
  return 'var(--red)';
}

function qualityClass(score) {
  if (typeof score !== 'number') return 'q-low';
  if (score >= 0.7) return 'q-high';
  if (score >= 0.4) return 'q-med';
  return 'q-low';
}

function safeDomain(url) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '');
    return host;
  } catch {
    return '';
  }
}

// ── XSS-safe text insertion ─────────────────────────────────────────────────
function esc(str) {
  const d = document.createElement('div');
  d.textContent = str == null ? '' : String(str);
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

// ── Banners ─────────────────────────────────────────────────────────────────
function banners() {
  if (backendHealth && backendHealth.offline) {
    return `
      <div class="offline-banner">
        <div class="demo-banner-icon">⚠</div>
        <div>
          Backend not reachable.
          <a href="#" id="bannerRetry" style="color:#fca5a5; text-decoration:underline;">Retry</a> ·
          <a href="#" id="bannerSettings" style="color:#fca5a5; text-decoration:underline;">Settings</a>
        </div>
      </div>
    `;
  }
  if (backendHealth && backendHealth.demo_mode) {
    return `
      <div class="demo-banner">
        <div class="demo-banner-icon">🛈</div>
        <div>
          <strong>Demo mode</strong> — fact-checks return canned results for showcase claims (creatine, BCAAs, tongkat ali). Add API keys to <code>backend/.env</code> for live AI checks.
        </div>
      </div>
    `;
  }
  return '';
}

function wireBanner() {
  const retry = document.getElementById('bannerRetry');
  const settings = document.getElementById('bannerSettings');
  retry && retry.addEventListener('click', (e) => { e.preventDefault(); checkHealth(); });
  settings && settings.addEventListener('click', (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
}

function lastReportRow() {
  if (!lastReportMeta) return '';
  const minsAgo = Math.max(1, Math.round((Date.now() - lastReportMeta.savedAt) / 60000));
  return `
    <div class="last-report-row">
      <div class="lr-meta">Last report — ${esc(lastReportMeta.summary).slice(0, 60)}…</div>
      <a id="viewLastReport">View ↗</a>
    </div>
  `;
}

function wireLastReport() {
  const link = document.getElementById('viewLastReport');
  if (link && lastReportMeta && lastReportMeta.report) {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      report = lastReportMeta.report;
      state = 'report';
      render();
    });
  }
}

// ── Idle ────────────────────────────────────────────────────────────────────
function renderIdle() {
  app.innerHTML = `
    ${banners()}
    ${lastReportRow()}
    <textarea
      id="inputText"
      placeholder="Paste a transcript, caption, or fitness claim…"
      maxlength="12000"
    ></textarea>
    <div class="char-count">
      <span id="charCount">0 / 12000</span>
      <span class="kbd-hint"><span class="kbd">⌘</span> + <span class="kbd">↵</span> extract</span>
    </div>

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

  wireBanner();
  wireLastReport();

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

  // Cmd/Ctrl + Enter to extract from anywhere in the textarea.
  textarea.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !extractBtn.disabled) {
      e.preventDefault();
      extractBtn.click();
    }
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
    textarea.focus();
  });

  document.getElementById('liveBtn').addEventListener('click', () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tabId = tabs[0] && tabs[0].id;
      if (tabId) {
        chrome.sidePanel.open({ tabId }).catch(() => {
          chrome.runtime.openOptionsPage();
        });
      }
      window.close();
    });
  });

  // Pick up text forwarded by the context menu (right-click → "Fact-check with Veritas").
  // If present, AUTO-extract instead of forcing the user to click again.
  chrome.storage.session.get('pendingText', ({ pendingText }) => {
    if (pendingText) {
      textarea.value = pendingText;
      charCount.textContent = `${pendingText.length} / 12000`;
      updateExtractBtn();
      chrome.storage.session.remove('pendingText');
      chrome.action.setBadgeText({ text: '' });
      // Don't auto-extract if backend is offline — the user needs to see why.
      if (!(backendHealth && backendHealth.offline)) {
        runExtract(pendingText);
      }
    }
  });
}

// ── Loading ─────────────────────────────────────────────────────────────────
function renderLoading() {
  const isChecking = state === 'checking';
  const stepsHtml = isChecking
    ? `<div class="step-indicator">
         ${CHECK_PHASES.map((p, i) => `
           <div class="step-row ${i === loadingPhase ? 'is-active' : (i < loadingPhase ? 'is-done' : '')}" data-step="${i}">
             <div class="step-bullet"></div>
             <div class="step-label">${esc(p.label)}</div>
           </div>
         `).join('')}
       </div>`
    : '';

  app.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <div class="loading-msg">${isChecking ? 'Fact-checking with two AI agents…' : 'Extracting claims…'}</div>
      ${isChecking ? '<div class="loading-sub">Typically 30–60 seconds</div>' : ''}
      ${stepsHtml}
      <div class="btn-row" style="justify-content:center; margin-top:14px;">
        <button class="btn-ghost" id="cancelBtn">Cancel</button>
        <span class="kbd-hint">or press <span class="kbd">esc</span></span>
      </div>
    </div>
  `;
  document.getElementById('cancelBtn').addEventListener('click', cancelOngoing);
}

function advanceLoadingPhase(targetIndex) {
  loadingPhase = Math.min(targetIndex, CHECK_PHASES.length - 1);
  // Live-mutate dom rather than re-render to avoid flicker.
  document.querySelectorAll('.step-row').forEach((el) => {
    const idx = parseInt(el.dataset.step, 10);
    el.classList.toggle('is-active', idx === loadingPhase);
    el.classList.toggle('is-done',   idx <  loadingPhase);
  });
}

function startLoadingPhaseTimer(startAt = 0) {
  loadingPhase = startAt;
  stopLoadingPhaseTimer();
  // Schedule each subsequent phase using cumulative estimates.
  let elapsed = 0;
  for (let i = startAt + 1; i < CHECK_PHASES.length; i++) {
    elapsed += CHECK_PHASES[i - 1].estMs;
    const targetIdx = i;
    setTimeout(() => {
      if (state === 'checking') advanceLoadingPhase(targetIdx);
    }, elapsed);
  }
}

function stopLoadingPhaseTimer() {
  // No-op marker: simpler than tracking each setTimeout id.
  // setTimeout handlers above guard with `if (state === 'checking')`.
  loadingTimer = null;
}

function cancelOngoing() {
  if (abortController) abortController.abort();
  if (state === 'checking') { state = claims.length ? 'review' : 'idle'; }
  else if (state === 'processing') { state = 'idle'; }
  render();
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
          <span class="tag">${esc((claim.category || '').replace(/_/g, ' '))}</span>
          ${claim.risk_level === 'high' ? '<span class="tag tag-high">high risk</span>' : ''}
        </div>
      </label>
    </li>
  `).join('');

  app.innerHTML = `
    ${banners()}
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

  wireBanner();

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
  const claimsHtml = report.claims.map((item, claimIdx) => {
    const dir = item.agreement.final_direction;
    const confidence = item.agreement.confidence || 'low';
    const summary = item.agreement.summary || '';
    const sources = item.sources || [];

    // "Sources-only" case: demo mode pulled curated evidence but had no LLM/cache
    // hit and no heuristic signal. Show a neutral badge + helpful footer rather
    // than the failure-shaped "No verdict" badge.
    const isSourcesOnly =
      dir === 'insufficient' &&
      sources.length > 0 &&
      /demo mode/i.test(summary);

    const sourcesHtml = sources.slice(0, 4).map((s, sIdx) => {
      const domain = safeDomain(s.url);
      const qcls = qualityClass(s.quality_score);
      const hasSnippet = !!(s.snippet && s.snippet.trim());
      return `
        <li class="source-row" data-claim="${claimIdx}" data-source="${sIdx}">
          <div class="source-head">
            <span class="source-quality-dot ${qcls}"
                  title="Source quality: ${typeof s.quality_score === 'number' ? s.quality_score.toFixed(2) : 'unknown'}"></span>
            <a class="source-link" href="${esc(s.url)}" target="_blank" rel="noreferrer"
               title="${esc(s.title)}">${esc(s.title)}</a>
            ${domain ? `<span class="source-domain">${esc(domain)}</span>` : ''}
            ${hasSnippet ? `<button class="source-toggle" data-claim="${claimIdx}" data-source="${sIdx}" aria-label="Toggle snippet">▾</button>` : ''}
          </div>
          ${hasSnippet ? `<div class="source-snippet" id="snip-${claimIdx}-${sIdx}">${esc(s.snippet).slice(0, 600)}</div>` : ''}
        </li>
      `;
    }).join('');

    const badgeBlock = isSourcesOnly
      ? `<div class="badges-stack">
           <span class="dir-badge dir-sources-only" title="Curated sources retrieved; configure API keys for a directional verdict.">Sources only</span>
         </div>`
      : `<div class="badges-stack">
           <span class="dir-badge dir-${dir}">${dirLabel(dir)}</span>
           <span class="conf-badge conf-${confidence}">${esc(confidence)} confidence</span>
         </div>`;

    const summaryBlock = isSourcesOnly
      ? `<div class="claim-summary">Veritas pulled ${sources.length} curated source${sources.length !== 1 ? 's' : ''} for this claim. Configure API keys in <code>backend/.env</code> to run the live two-agent fact-check.</div>`
      : `<div class="claim-summary">${esc(summary)}</div>`;

    return `
      <div class="claim-result">
        <div class="claim-result-head">
          <div class="claim-result-text">${esc(item.claim.normalized_claim)}</div>
          ${badgeBlock}
        </div>
        ${summaryBlock}
        ${sources.length ? `<ul class="sources-list">${sourcesHtml}</ul>` : ''}
      </div>
    `;
  }).join('');

  const score = report.clip_credibility_score;
  const ringColor = scoreColor(score);
  const ringPct = Math.round((Math.max(0, Math.min(100, score)) / 100) * 360);

  app.innerHTML = `
    ${banners()}
    <div class="report-hero">
      <div class="score-ring" style="--ring-color:${ringColor}; --ring-pct:${ringPct}deg;">
        <div class="score-inner">
          <div class="score-num">${score}</div>
          <div class="score-label">/ 100</div>
        </div>
      </div>
      <div class="overall-summary">${esc(report.overall_summary)}</div>
    </div>
    ${claimsHtml}
    <div class="footer-actions">
      <button class="btn-ghost"   id="resetBtn">Check another</button>
      <button class="btn-primary" id="openAppBtn">Open full app ↗</button>
    </div>
  `;

  wireBanner();

  document.querySelectorAll('.source-toggle').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const c = btn.dataset.claim;
      const s = btn.dataset.source;
      const snip = document.getElementById(`snip-${c}-${s}`);
      if (snip) {
        snip.classList.toggle('is-open');
        btn.classList.toggle('is-open');
      }
    });
  });

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
  const isNetwork = /fetch|network|failed|offline|reach/i.test(errorMsg || '');
  app.innerHTML = `
    ${banners()}
    <div class="error-box">${esc(errorMsg)}</div>
    <div class="btn-row">
      ${isNetwork ? `<button class="btn-primary" id="testBtn">Test connection</button>` : ''}
      ${isNetwork ? `<button class="btn-ghost" id="settingsLinkBtn">Open settings</button>` : ''}
      <button class="btn-ghost" id="retryBtn">Start over</button>
    </div>
  `;
  wireBanner();
  const testBtn = document.getElementById('testBtn');
  const settingsLinkBtn = document.getElementById('settingsLinkBtn');
  testBtn && testBtn.addEventListener('click', async () => {
    const h = await checkHealth();
    if (h && !h.offline) {
      errorMsg = ''; state = 'idle'; render();
    }
  });
  settingsLinkBtn && settingsLinkBtn.addEventListener('click', () => chrome.runtime.openOptionsPage());
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
  startLoadingPhaseTimer(0);
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
    // Mark final step done.
    advanceLoadingPhase(CHECK_PHASES.length - 1);
    state = 'report';
    // Persist last report so reopening the popup can recover it.
    lastReportMeta = {
      score: report.clip_credibility_score,
      summary: report.overall_summary || '',
      savedAt: Date.now(),
      report,
    };
    chrome.storage.session.set({ lastReport: lastReportMeta }).catch(() => {});
  } catch (err) {
    if (err.name === 'AbortError') { state = 'review'; render(); return; }
    errorMsg = err.message || String(err);
    state = 'error';
  }
  render();
}

// ── Global keyboard ─────────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && (state === 'processing' || state === 'checking')) {
    cancelOngoing();
  }
});

// ── Boot ─────────────────────────────────────────────────────────────────────
async function boot() {
  // Restore last report (best effort).
  try {
    const stored = await chrome.storage.session.get('lastReport');
    if (stored && stored.lastReport && stored.lastReport.report) {
      // Only show if fresh (<2h old).
      const age = Date.now() - (stored.lastReport.savedAt || 0);
      if (age < 2 * 60 * 60 * 1000) {
        lastReportMeta = stored.lastReport;
      }
    }
  } catch {}
  render();
  checkHealth();
}

boot();
