// options.js — load and save Veritas extension settings

const backendInput  = document.getElementById('backendUrl');
const frontendInput = document.getElementById('frontendUrl');
const saveBtn       = document.getElementById('saveBtn');
const testBtn       = document.getElementById('testBtn');
const saveStatus    = document.getElementById('saveStatus');
const testStatus    = document.getElementById('testStatus');

// Load saved values
chrome.storage.sync.get(
  { backendUrl: 'http://localhost:8000', frontendUrl: 'http://localhost:5173' },
  ({ backendUrl, frontendUrl }) => {
    backendInput.value  = backendUrl;
    frontendInput.value = frontendUrl;
  }
);

// Save
saveBtn.addEventListener('click', () => {
  const backendUrl  = backendInput.value.trim()  || 'http://localhost:8000';
  const frontendUrl = frontendInput.value.trim() || 'http://localhost:5173';
  chrome.storage.sync.set({ backendUrl, frontendUrl }, () => {
    saveStatus.textContent = 'Saved!';
    setTimeout(() => { saveStatus.textContent = ''; }, 2000);
  });
});

// Test connection
testBtn.addEventListener('click', async () => {
  const url = (backendInput.value.trim() || 'http://localhost:8000').replace(/\/$/, '');
  testStatus.textContent = 'Connecting…';
  try {
    const res = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const data = await res.json();
      const mode = data.demo_mode ? 'demo mode' : 'live mode';
      testStatus.textContent = `✓ Connected (${mode})`;
      testStatus.style.color = 'var(--green, #4ade80)';
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
