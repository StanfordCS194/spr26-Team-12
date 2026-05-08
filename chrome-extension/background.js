// Service worker — sets up context menus and relays selected text / side panel opens.

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

    // Store the selected text so the popup picks it up on open.
    chrome.storage.session.set({ pendingText: text });

    // Show a badge so the user knows text is ready if the popup
    // doesn't open automatically (openPopup requires Chrome 127+).
    chrome.action.setBadgeText({ text: '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' });

    // Try to open the popup programmatically (Chrome 127+).
    if (chrome.action.openPopup) {
      chrome.action.openPopup().catch(() => {
        // Silently ignore — badge already signals the user to click the icon.
      });
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

// Clear the badge when the popup is opened manually.
chrome.action.onClicked.addListener(() => {
  chrome.action.setBadgeText({ text: '' });
});
