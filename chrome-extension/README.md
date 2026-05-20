# Veritas Chrome Extension

Fact-check fitness influencer claims from any page — right-click selected text or paste a transcript directly into the popup.

The extension talks to the same Veritas FastAPI backend as the web app. No separate server is needed.

---

## Quick start

### 1. Start the Veritas backend

From the **repository root** (parent of `backend/` and `chrome-extension/`):

```bash
source backend/venv/bin/activate   # Windows: backend\venv\Scripts\activate
uvicorn backend.main:app --reload  # matches backend/main.py docstring — package imports need this module path
```

### 2. Load the extension in Chrome

1. Open **chrome://extensions**
2. Enable **Developer mode** (toggle in the top-right corner)
3. Click **Load unpacked**
4. Select the `chrome-extension/` folder in this repo

The purple **V** icon appears in your Chrome toolbar. Pin it for easy access.

### 3. Fact-check something

**Option A — right-click on any page**
Highlight any fitness claim on YouTube, Reddit, TikTok, Instagram, etc. → right-click → **"Fact-check with Veritas"** → the popup opens with the text already loaded.

**Option B — click the toolbar icon**
Click the V icon → paste a transcript, caption, or any fitness claim into the text box → hit **Extract claims**.

**Option C — Live Fact-Check (side panel)**
Watch a video normally → click the V icon → click **"⏺ Live fact-check"** → the side panel opens alongside the video. Choose a recording window (30/60/90 s), hit **Start recording**, and Veritas captures the tab's audio while you watch. When the timer ends (or you click Stop), it transcribes, extracts claims, and runs the full fact-check pipeline — all without closing the video.

---

## How the popup works

The popup follows the same pipeline as the Veritas web app:

```
Paste text / right-click selection
        ↓
  POST /api/process/text       ← normalize the input
        ↓
  POST /api/claims/extract     ← LLM extracts individual claims
        ↓
  Review & deselect any claims you want to skip
        ↓
  POST /api/clip-report        ← two AI agents search sources and agree on a verdict
        ↓
  Credibility score + per-claim verdict cards with source links
```

Each step has a cancel button. The fact-checking step (clip-report) typically takes **30–60 seconds** because two LLM agents run independently.

---

## Settings

Click the **⚙ gear icon** in the popup header (or go to **chrome://extensions → Veritas → Details → Extension options**).

| Setting | Default | Description |
|---|---|---|
| Backend URL | `https://veritas-api-ka3y.onrender.com` | Must match `frontend/vercel.json` so the extension and website use the same API. |
| Frontend URL | `https://veritas-ruby.vercel.app` | URL of the React web app. Used by the "Open full app" button. |

Use the **Test connection** button to verify the backend is reachable before fact-checking. It hits `/api/health` and shows whether the backend is in demo mode or live mode.

---

## Permissions explained

| Permission | Why it's needed |
|---|---|
| `storage` | Saves your backend/frontend URL settings and relays selected text from the context menu to the popup |
| `contextMenus` | Adds the right-click "Fact-check with Veritas" and "Live fact-check this tab" menu items |
| `activeTab` | Lets the background service worker open the popup when you right-click |
| `tabCapture` | Captures the tab's audio stream for the Live Fact-Check side panel |
| `sidePanel` | Enables the Live Fact-Check side panel that stays open while you watch a video |
| `http://localhost/*` | Allows the popup and side panel to call the local Veritas backend API |

The popup and recording flow only send data when you initiate an action.

On **YouTube, X/Twitter, and TikTok**, the bundled `live_scanner.js` content script scans visible page text/captions for fitness claims — those requests still go **only** to the backend URL you configure in settings.

---

## File structure

```
chrome-extension/
├── manifest.json          Extension config (Manifest V3)
├── background.js          Service worker — context menu setup and text relay
├── content_script.js      Runs on every page, responds to selection/meta queries
├── popup.html             Main popup shell
├── popup.css              Popup styles (matches Veritas dark theme)
├── popup.js               Popup state machine and API calls
├── sidepanel.html         Live Fact-Check side panel shell
├── sidepanel.css          Side panel styles (recording ring, pulse dot, verdict cards)
├── sidepanel.js           Live recording state machine (tabCapture → transcribe → fact-check)
├── options.html           Settings page
├── options.js             Settings save/load/test logic
├── generate-icons.mjs     Script to regenerate PNG icons from the SVG source
└── icons/
    ├── icon.svg           Source icon (purple V logo) — edit this to restyle
    ├── icon16.png         Generated — do not edit directly
    ├── icon48.png         Generated — do not edit directly
    └── icon128.png        Generated — do not edit directly
```

---

## Regenerating icons

If you change `icons/icon.svg`, regenerate the PNGs with:

```bash
# from the repo root (requires Node 18+ and sharp)
npm install --save-dev sharp     # one-time install
node chrome-extension/generate-icons.mjs
```

Then reload the extension at **chrome://extensions**.

---

## Deploying to a remote backend

If you host the FastAPI backend on a public server (e.g., Railway, Render, Fly.io):

1. Open the extension **Settings** page
2. Update **Backend URL** to your server's URL (e.g., `https://veritas-api.example.com`)
3. Update **Frontend URL** if yours differs from the default production URL (`https://veritas-ruby.vercel.app`).
4. In `manifest.json`, add your server to `host_permissions`:

```json
"host_permissions": [
  "http://localhost/*",
  "https://veritas-api.example.com/*"
]
```

Then reload the extension at **chrome://extensions**.

> **Note:** The backend already has `allow_origins=["*"]` CORS headers, so the extension can call it from any origin.

---

## Troubleshooting

**"Backend error 503" or "Unreachable"**
The backend is not running. Start it with `uvicorn main:app --reload` from the `backend/` directory.

**"No checkable claims found"**
The text was too short or contained no verifiable fitness claims. Try pasting a longer transcript or a specific supplement/training claim.

**Fact-checking is slow**
This is expected — two LLM agents run sequentially per claim, each doing a web search. A 3-claim transcript typically takes 45–90 seconds. If the backend has no API keys configured it will fall back to demo mode (instant cached results for a handful of showcase claims).

**Right-click menu does not open the popup**
`chrome.action.openPopup()` requires Chrome 127+. On older versions, a `!` badge appears on the extension icon instead — click the icon manually to open the popup. The selected text is already waiting there.

**"Could not capture tab audio" in the side panel**
The tab must be playing audio (start the video first), and the page must be a normal `http://` or `https://` page — `chrome://` and `edge://` pages block tab capture. Also check that you granted the `tabCapture` permission when prompted.

**Side panel opens but recording produces no speech**
Make sure the tab's volume is not muted and that the video is actively playing during the recording window. The tab audio capture picks up all audio playing in that tab (video, ads, background music) — not your microphone.

**Changes to extension files are not reflected**
After editing any file, go to **chrome://extensions** and click the **↺ reload** button on the Veritas card.
