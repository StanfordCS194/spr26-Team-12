// options.js — load and save Veritas extension settings

const backendInput   = document.getElementById('backendUrl');
const frontendInput  = document.getElementById('frontendUrl');
const liveScanToggle = document.getElementById('liveScanToggle');
const saveBtn        = document.getElementById('saveBtn');
const testBtn        = document.getElementById('testBtn');
const saveStatus     = document.getElementById('saveStatus');
const testStatus     = document.getElementById('testStatus');
const clearCacheBtn  = document.getElementById('clearCacheBtn');
const cacheStatus    = document.getElementById('cacheStatus');
const scanStats      = document.getElementById('scanStats');

// Load saved values
chrome.storage.sync.get(
  {
    backendUrl: VERITAS_DEFAULT_BACKEND,
    frontendUrl: VERITAS_DEFAULT_FRONTEND,
    liveScanEnabled: true,
  },
  ({ backendUrl, frontendUrl, liveScanEnabled }) => {
    backendInput.value  = backendUrl;
    frontendInput.value = frontendUrl;
    liveScanToggle.checked = liveScanEnabled;
  }
);

// Save
saveBtn.addEventListener('click', () => {
  const backendUrl  = backendInput.value.trim()  || VERITAS_DEFAULT_BACKEND;
  const frontendUrl = frontendInput.value.trim() || VERITAS_DEFAULT_FRONTEND;
  const liveScanEnabled = liveScanToggle.checked;
  chrome.storage.sync.set({ backendUrl, frontendUrl, liveScanEnabled }, () => {
    saveStatus.textContent = 'Saved!';
    setTimeout(() => { saveStatus.textContent = ''; }, 2000);
  });
});

// Live scan toggle (instant save)
liveScanToggle.addEventListener('change', () => {
  chrome.storage.sync.set({ liveScanEnabled: liveScanToggle.checked });
});

// Test connection
testBtn.addEventListener('click', async () => {
  const url = (backendInput.value.trim() || VERITAS_DEFAULT_BACKEND).replace(/\/$/, '');
  testStatus.textContent = 'Connecting…';
  try {
    const res = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const data = await res.json();
      const mode = data.demo_mode ? 'demo mode' : 'live mode';
      testStatus.textContent = `✓ Connected (${mode})`;
      testStatus.style.color = 'var(--green, #4ade80)';
      const fromApi = typeof data.web_app_url === 'string' ? data.web_app_url.trim().replace(/\/$/, '') : '';
      const curFe = (frontendInput.value.trim() || VERITAS_DEFAULT_FRONTEND).replace(/\/$/, '');
      if (fromApi && /localhost|127\.0\.0\.1/i.test(curFe)) {
        frontendInput.value = fromApi;
        chrome.storage.sync.set({ frontendUrl: fromApi });
      }
    } else {
      testStatus.textContent = `✗ HTTP ${res.status}`;
      testStatus.style.color = '#f87171';
    }
  } catch (err) {
    testStatus.textContent = `✗ ${err.message || 'Unreachable'}`;
    testStatus.style.color = '#f87171';
  }
  setTimeout(() => {
    testStatus.textContent = '';
    testStatus.style.color = '';
  }, 5000);
});

// Clear scan cache
clearCacheBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'CLEAR_SCAN_CACHE' }, (response) => {
    if (response && response.ok) {
      cacheStatus.textContent = 'Cache cleared';
      cacheStatus.style.color = 'var(--green, #4ade80)';
    }
    setTimeout(() => {
      cacheStatus.textContent = '';
      cacheStatus.style.color = '';
    }, 2000);
  });
});

// Show scan stats
chrome.runtime.sendMessage({ type: 'GET_SCAN_STATS' }, (response) => {
  if (response) {
    scanStats.textContent = `Cache: ${response.cacheSize} entries | Queue: ${response.queueLength} pending`;
  }
});
