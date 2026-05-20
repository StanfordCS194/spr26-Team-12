// Service worker — sets up context menus, relays selected text to the popup,
// opens the Live Fact-Check side panel, and coordinates live scanning with
// the backend API (caching + rate limiting).

importScripts('defaults.js');

// ── Context menu setup ────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'veritas-factcheck',
    title: 'Fact-check with Veritas',
    contexts: ['selection'],
  });

  chrome.contextMenus.create({
    id: 'veritas-live',
    title: 'Live fact-check this tab',
    contexts: ['page', 'video', 'audio'],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'veritas-factcheck') {
    const text = (info.selectionText || '').trim();
    if (!text) return;

    chrome.storage.session.set({ pendingText: text });
    chrome.action.setBadgeText({ text: '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' });

    if (chrome.action.openPopup) {
      chrome.action.openPopup().catch(() => {});
    }
    return;
  }

  if (info.menuItemId === 'veritas-live' && tab && tab.id) {
    // Open the Live Fact-Check side panel for this tab.
    chrome.sidePanel.open({ tabId: tab.id }).catch(() => {
      // sidePanel.open unavailable on restricted pages (chrome://, etc.).
    });
  }
});

chrome.action.onClicked.addListener(() => {
  chrome.action.setBadgeText({ text: '' });
});

// ── Live scan coordination ────────────────────────────────────────────────────

const scanCache = new Map();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const MAX_CACHE_SIZE = 100;
const RATE_LIMIT_MS = 2000;
let lastScanTime = 0;
let pendingScans = [];
let processingQueue = false;

async function getBackendUrl() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ backendUrl: VERITAS_DEFAULT_BACKEND }, ({ backendUrl }) => {
      resolve((backendUrl || VERITAS_DEFAULT_BACKEND).replace(/\/$/, ''));
    });
  });
}

function cleanCache() {
  const now = Date.now();
  for (const [key, entry] of scanCache) {
    if (now - entry.timestamp > CACHE_TTL_MS) {
      scanCache.delete(key);
    }
  }
  if (scanCache.size > MAX_CACHE_SIZE) {
    const entries = [...scanCache.entries()].sort((a, b) => a[1].timestamp - b[1].timestamp);
    const toRemove = entries.slice(0, entries.length - MAX_CACHE_SIZE);
    toRemove.forEach(([key]) => scanCache.delete(key));
  }
}

async function callQuickScan(text, url, platform, contentType) {
  const base = await getBackendUrl();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 50000);

  try {
    const body = { text: text.slice(0, 5000), url, platform };
    if (contentType) body.content_type = contentType;
    const res = await fetch(`${base}/api/claims/quick-scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!res.ok) {
      return { claims: [], error: `HTTP ${res.status}` };
    }
    return await res.json();
  } catch (err) {
    clearTimeout(timeout);
    return { claims: [], error: err.message };
  }
}

async function processQueue() {
  if (processingQueue || pendingScans.length === 0) return;
  processingQueue = true;

  while (pendingScans.length > 0) {
    const elapsed = Date.now() - lastScanTime;
    if (elapsed < RATE_LIMIT_MS) {
      await new Promise(r => setTimeout(r, RATE_LIMIT_MS - elapsed));
    }

    const scan = pendingScans.shift();
    lastScanTime = Date.now();

    try {
      const result = await callQuickScan(scan.text, scan.url, scan.platform, scan.contentType);
      const cacheEntry = { claims: result.claims || [], timestamp: Date.now() };
      scanCache.set(scan.hash, cacheEntry);
      cleanCache();
      scan.resolve(cacheEntry);
    } catch (err) {
      scan.resolve({ claims: [] });
    }
  }

  processingQueue = false;
}

// ── Message handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Direct scan — bypasses rate-limit queue for parallel transcript chunks
  if (message.type === 'LIVE_SCAN_DIRECT') {
    const { text, url, platform, contentType } = message;
    callQuickScan(text, url, platform, contentType).then(result => {
      sendResponse({ claims: result.claims || [] });
    }).catch(() => {
      sendResponse({ claims: [] });
    });
    return true;
  }

  if (message.type === 'LIVE_SCAN') {
    const { text, url, platform, hash, contentType } = message;

    // Check cache first
    const cached = scanCache.get(hash);
    if (cached && (Date.now() - cached.timestamp < CACHE_TTL_MS)) {
      sendResponse({ claims: cached.claims, cached: true });
      return true;
    }

    // Queue the scan
    const promise = new Promise((resolve) => {
      pendingScans.push({ text, url, platform, hash, contentType, resolve });
    });

    promise.then((result) => {
      sendResponse({ claims: result.claims || [], cached: false });
    });

    processQueue();
    return true; // keep message channel open for async response
  }

  if (message.type === 'FETCH_TRANSCRIPT') {
    const { videoId } = message;
    (async () => {
      const base = await getBackendUrl();
      try {
        console.log(`[Veritas BG] Fetching transcript for ${videoId}`);
        const res = await fetch(`${base}/api/transcript/${videoId}`, {
          signal: AbortSignal.timeout(20000),
        });
        if (!res.ok) {
          const detail = await res.text().catch(() => '');
          console.log(`[Veritas BG] Transcript fetch HTTP ${res.status}: ${detail.slice(0, 200)}`);
          sendResponse({ error: `HTTP ${res.status}`, segments: [] });
          return;
        }
        const data = await res.json();
        console.log(`[Veritas BG] Got ${data.segments?.length || 0} transcript segments in ${data.fetch_time_ms}ms`);
        sendResponse(data);
      } catch (err) {
        console.error('[Veritas BG] Transcript fetch error:', err.message);
        sendResponse({ error: err.message, segments: [] });
      }
    })();
    return true; // keep message channel open for async response
  }

  if (message.type === 'LIVE_DEEP_CHECK') {
    // Store the text for deep fact-check and open popup
    chrome.storage.session.set({ pendingText: message.text });
    chrome.action.setBadgeText({ text: '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' });
    if (chrome.action.openPopup) {
      chrome.action.openPopup().catch(() => {});
    }
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === 'GET_SCAN_STATS') {
    sendResponse({
      cacheSize: scanCache.size,
      queueLength: pendingScans.length,
    });
    return true;
  }

  if (message.type === 'CLEAR_SCAN_CACHE') {
    scanCache.clear();
    sendResponse({ ok: true });
    return true;
  }
});

// ── Badge for live scan status ────────────────────────────────────────────────

chrome.storage.sync.get({ liveScanEnabled: true }, ({ liveScanEnabled }) => {
  if (liveScanEnabled) {
    chrome.action.setBadgeText({ text: '' });
  }
});
