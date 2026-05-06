// Runs on every page. Responds to messages from the popup requesting
// the current text selection or basic page metadata.

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'GET_SELECTION') {
    sendResponse({ text: window.getSelection()?.toString()?.trim() || '' });
    return true;
  }
  if (message.type === 'GET_PAGE_META') {
    sendResponse({
      title: document.title,
      url: window.location.href,
      description:
        document.querySelector('meta[name="description"]')?.getAttribute('content') ||
        document.querySelector('meta[property="og:description"]')?.getAttribute('content') ||
        '',
    });
    return true;
  }
});
