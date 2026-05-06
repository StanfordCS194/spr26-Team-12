// Service worker — sets up the context menu and relays selected text to the popup.

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'veritas-factcheck',
    title: 'Fact-check with Veritas',
    contexts: ['selection'],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== 'veritas-factcheck') return;
  const text = (info.selectionText || '').trim();
  if (!text) return;

  // Store the selected text so the popup picks it up on open.
  chrome.storage.session.set({ pendingText: text });

  // Show a badge so the user knows text is ready even if the popup
  // doesn't open automatically (openPopup requires Chrome 127+).
  chrome.action.setBadgeText({ text: '!' });
  chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' });

  // Try to open the popup programmatically (Chrome 127+).
  if (chrome.action.openPopup) {
    chrome.action.openPopup().catch(() => {
      // Silently ignore — badge already signals the user to click the icon.
    });
  }
});

// Clear the badge when the popup is opened manually.
chrome.action.onClicked.addListener(() => {
  chrome.action.setBadgeText({ text: '' });
});
