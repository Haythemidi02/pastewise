// service_worker.js
// Minimal background context — only handles things content.js cannot:
// 1. Opening dashboard.html as a new tab
// 2. Relaying messages between content.js and other extension pages

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {

    // content.js or popup.js asks to open the full dashboard
    case "OPEN_DASHBOARD": {
      chrome.tabs.create({
        url: chrome.runtime.getURL("dashboard.html")
      });
      sendResponse({ ok: true });
      break;
    }

    // content.js tells us the user just pasted (with or without reading)
    // We forward it to the Python backend in case content.js fetch fails
    // (service workers can bypass stricter CSP on some pages)
    case "RECORD_PASTE": {
      fetch("http://localhost:8000/record-paste", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ read_first: message.read_first })
      })
        .then(() => sendResponse({ ok: true }))
        .catch((err) => sendResponse({ ok: false, error: err.message }));

      return true; // keeps the message channel open for the async response
    }

    // popup.js asks for current stats to display in the toolbar popup
    case "GET_STATS": {
      fetch("http://localhost:8000/stats")
        .then((r) => r.json())
        .then((data) => sendResponse({ ok: true, data }))
        .catch((err) => sendResponse({ ok: false, error: err.message }));

      return true;
    }

    default:
      sendResponse({ ok: false, error: `Unknown message type: ${message.type}` });
  }
});

// First install — open options page so user can confirm settings
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({
      url: chrome.runtime.getURL("options.html")
    });
  }
});