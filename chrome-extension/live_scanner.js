/**
 * Veritas Live Scanner — content script that runs on YouTube, Twitter/X, and TikTok.
 *
 * Detects fitness/health claims in page content and injects a floating warning
 * overlay on the video player (visible even in fullscreen).
 */

(() => {
  'use strict';

  // ── Platform detection ──────────────────────────────────────────────────────
  function detectPlatform() {
    const host = location.hostname.replace('www.', '');
    if (host.includes('youtube.com')) return 'youtube';
    if (host.includes('twitter.com') || host.includes('x.com')) return 'twitter';
    if (host.includes('tiktok.com')) return 'tiktok';
    return null;
  }

  const PLATFORM = detectPlatform();
  if (!PLATFORM) return;

  // ── State ───────────────────────────────────────────────────────────────────
  const scannedTexts = new Set();
  const scannedElements = new WeakSet();
  let scanEnabled = true;
  let scanDebounce = null;
  let collectedClaims = [];
  let urlCheckInterval = null;
  let contextValid = true;
  const DEBOUNCE_MS = 1500;
  const MIN_TEXT_LENGTH = 40;

  // Fitness keywords for client-side pre-filter (avoids unnecessary API calls)
  const FITNESS_KEYWORDS = [
    'creatine', 'bcaa', 'protein', 'supplement', 'testosterone', 'fat burn',
    'weight loss', 'muscle', 'workout', 'pre-workout', 'collagen', 'tongkat',
    'ashwagandha', 'metabolism', 'cortisol', 'hormone', 'gains', 'bulking',
    'cutting', 'macros', 'calories', 'whey', 'casein', 'amino',
    'hypertrophy', 'anabolic', 'recovery', 'detox', 'cleanse', 'superfood',
    'keto', 'intermittent fasting', 'insulin', 'electrolytes', 'hiit',
    'fat burner', 'shred', 'lean', 'toned', 'boost testosterone',
    'natural testosterone', 'gut health', 'inflammation', 'joint',
  ];

  function hasFitnessContent(text) {
    const lower = text.toLowerCase();
    let matches = 0;
    for (const kw of FITNESS_KEYWORDS) {
      if (lower.includes(kw)) {
        matches++;
        if (matches >= 2) return true;
      }
    }
    return false;
  }

  function textHash(text) {
    let hash = 0;
    const str = text.slice(0, 500);
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash) + str.charCodeAt(i);
      hash |= 0;
    }
    return hash.toString(36);
  }

  // ── YouTube transcript extraction ──────────────────────────────────────────

  function formatTimestamp(seconds) {
    const s = Math.floor(seconds);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }

  function getVideoId() {
    const match = location.href.match(/[?&]v=([a-zA-Z0-9_-]{11})/);
    return match ? match[1] : null;
  }

  function extractCaptionUrlFromScripts() {
    try {
      const scripts = document.querySelectorAll('script');
      for (const script of scripts) {
        const text = script.textContent || '';
        const idx = text.indexOf('ytInitialPlayerResponse');
        if (idx === -1) continue;

        const jsonStart = text.indexOf('{', idx);
        if (jsonStart === -1) continue;

        let depth = 0;
        let jsonEnd = jsonStart;
        for (let i = jsonStart; i < text.length; i++) {
          if (text[i] === '{') depth++;
          else if (text[i] === '}') depth--;
          if (depth === 0) { jsonEnd = i + 1; break; }
        }

        const json = JSON.parse(text.slice(jsonStart, jsonEnd));
        return pickCaptionTrack(json);
      }
    } catch (err) {
      console.log('[Veritas] Script extraction failed:', err.message);
    }
    return null;
  }

  function pickCaptionTrack(playerResponse) {
    const tracks = playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (!tracks || tracks.length === 0) return null;

    const enTrack = tracks.find(t =>
      t.languageCode === 'en' || t.languageCode?.startsWith('en')
    );
    const track = enTrack || tracks[0];
    return track?.baseUrl || null;
  }

  async function extractCaptionUrl() {
    // Method 1: Parse from inline script tags (works on full page loads)
    const fromScript = extractCaptionUrlFromScripts();
    if (fromScript) {
      console.log('[Veritas] Caption URL found in inline scripts');
      return fromScript;
    }

    // Method 2: Call YouTube's innertube player API (works on SPA navigations)
    const videoId = getVideoId();
    if (!videoId) return null;

    try {
      const res = await fetch('https://www.youtube.com/youtubei/v1/player?prettyPrint=false', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          videoId,
          context: {
            client: {
              clientName: 'WEB',
              clientVersion: '2.20240101.00.00',
            },
          },
        }),
      });
      if (!res.ok) return null;
      const data = await res.json();
      const url = pickCaptionTrack(data);
      if (url) console.log('[Veritas] Caption URL found via innertube API');
      return url;
    } catch (err) {
      console.log('[Veritas] Innertube API failed:', err.message);
      return null;
    }
  }

  async function fetchTranscript(captionUrl) {
    // Try multiple format variants — YouTube's timedtext API is inconsistent
    const urls = [
      captionUrl,                                                         // raw (usually json3)
      `${captionUrl}${captionUrl.includes('?') ? '&' : '?'}fmt=srv3`,    // XML srv3
      `${captionUrl}${captionUrl.includes('?') ? '&' : '?'}fmt=vtt`,     // WebVTT
    ];

    for (const url of urls) {
      try {
        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) continue;
        const body = await res.text();
        if (!body || body.length < 10) continue;

        console.log(`[Veritas] Transcript fetched (${body.length} chars) from: ...${url.slice(-30)}`);

        // Try XML first
        const xmlSegs = parseTranscriptXml(body);
        if (xmlSegs && xmlSegs.length > 0) return xmlSegs;

        // Try JSON3
        const jsonSegs = parseTranscriptJson3(body);
        if (jsonSegs && jsonSegs.length > 0) return jsonSegs;

        // Try VTT
        const vttSegs = parseTranscriptVtt(body);
        if (vttSegs && vttSegs.length > 0) return vttSegs;
      } catch (_) {
        continue;
      }
    }

    console.log('[Veritas] All transcript fetch attempts failed');
    return null;
  }

  function parseTranscriptVtt(body) {
    try {
      if (!body.includes('WEBVTT')) return null;
      const segments = [];
      // Match timestamp lines: 00:00:01.234 --> 00:00:05.678
      const blocks = body.split(/\n\n+/);
      for (const block of blocks) {
        const match = block.match(/(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})/);
        if (!match) continue;
        const start = parseInt(match[1]) * 3600 + parseInt(match[2]) * 60 + parseInt(match[3]) + parseInt(match[4]) / 1000;
        const end = parseInt(match[5]) * 3600 + parseInt(match[6]) * 60 + parseInt(match[7]) + parseInt(match[8]) / 1000;
        // Text is everything after the timestamp line
        const lines = block.split('\n');
        const tsIdx = lines.findIndex(l => l.includes('-->'));
        const text = lines.slice(tsIdx + 1).join(' ').replace(/<[^>]+>/g, '').trim();
        if (text) {
          segments.push({ start, dur: end - start, text });
        }
      }
      return segments.length > 0 ? segments : null;
    } catch (_) {
      return null;
    }
  }

  function parseTranscriptXml(body) {
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(body, 'text/xml');
      // Check for parse errors
      if (doc.querySelector('parsererror')) return null;
      const textEls = doc.querySelectorAll('text');
      if (textEls.length === 0) return null;

      const segments = [];
      textEls.forEach(el => {
        const start = parseFloat(el.getAttribute('start') || '0');
        const dur = parseFloat(el.getAttribute('dur') || '0');
        // Decode HTML entities in the transcript text
        const tmp = document.createElement('textarea');
        tmp.innerHTML = el.textContent || '';
        const content = tmp.value.replace(/\n/g, ' ').trim();
        if (content) {
          segments.push({ start, dur, text: content });
        }
      });
      return segments;
    } catch (_) {
      return null;
    }
  }

  function parseTranscriptJson3(body) {
    try {
      const json = JSON.parse(body);
      const events = json?.events;
      if (!Array.isArray(events)) return null;

      const segments = [];
      for (const event of events) {
        // Skip events without text segments (e.g. window-style events)
        const segs = event.segs;
        if (!segs) continue;

        const start = (event.tStartMs || 0) / 1000;
        const dur = (event.dDurationMs || 0) / 1000;
        const text = segs.map(s => s.utf8 || '').join('').replace(/\n/g, ' ').trim();
        if (text) {
          segments.push({ start, dur, text });
        }
      }
      return segments.length > 0 ? segments : null;
    } catch (_) {
      return null;
    }
  }

  function extractFromTextTracks() {
    try {
      const video = document.querySelector('video');
      if (!video || !video.textTracks) return null;

      // Find an active/loaded text track (captions or subtitles)
      let track = null;
      for (let i = 0; i < video.textTracks.length; i++) {
        const t = video.textTracks[i];
        if ((t.kind === 'captions' || t.kind === 'subtitles') && t.cues && t.cues.length > 0) {
          track = t;
          break;
        }
      }
      if (!track || !track.cues || track.cues.length === 0) return null;

      console.log(`[Veritas] Fallback: extracting from textTrack (${track.cues.length} cues)`);
      const segments = [];
      for (let i = 0; i < track.cues.length; i++) {
        const cue = track.cues[i];
        const text = (cue.text || '').replace(/\n/g, ' ').trim();
        if (text) {
          segments.push({ start: cue.startTime, dur: cue.endTime - cue.startTime, text });
        }
      }
      return segments.length > 0 ? segments : null;
    } catch (_) {
      return null;
    }
  }

  function chunkTranscript(segments, maxChars = 4800) {
    // Format segments into ~60-second windows with [M:SS] timestamps
    let result = '';
    let windowStart = 0;
    const WINDOW_SIZE = 60; // seconds

    for (const seg of segments) {
      if (seg.start >= windowStart + WINDOW_SIZE) {
        windowStart = Math.floor(seg.start / WINDOW_SIZE) * WINDOW_SIZE;
      }
      const line = `[${formatTimestamp(seg.start)}] ${seg.text}`;
      if (result.length + line.length + 1 > maxChars) break;
      result += line + '\n';
    }

    return result.trim();
  }

  // ── Video seek ─────────────────────────────────────────────────────────────

  function seekVideo(seconds) {
    const video = document.querySelector('video');
    if (video) {
      video.currentTime = seconds;
      video.play().catch(() => {});
    }
  }

  // ── Progress bar markers ───────────────────────────────────────────────────

  function clearProgressMarkers() {
    document.querySelectorAll('.veritas-progress-marker').forEach(el => el.remove());
  }

  function injectProgressMarkers(claims) {
    clearProgressMarkers();

    if (PLATFORM !== 'youtube') return;

    const video = document.querySelector('video');
    const progressBar = document.querySelector('.ytp-progress-bar-container');
    if (!video || !progressBar || !video.duration) return;

    const duration = video.duration;

    for (const claim of claims) {
      if (claim.start_time == null || claim.start_time < 0) continue;

      const pct = (claim.start_time / duration) * 100;
      if (pct > 100) continue;

      const marker = document.createElement('div');
      marker.className = 'veritas-progress-marker';
      marker.setAttribute('data-veritas', 'true');

      const riskColor = claim.risk_level === 'high' ? '#ff3b30'
                      : claim.risk_level === 'medium' ? '#ff9500'
                      : '#007aff';
      marker.style.cssText = `
        position: absolute;
        left: ${pct}%;
        bottom: 0;
        width: 4px;
        height: 100%;
        background: ${riskColor};
        opacity: 0.8;
        border-radius: 1px;
        cursor: pointer;
        z-index: 99;
        pointer-events: auto;
      `;
      marker.title = claim.timestamp_label
        ? `[${claim.timestamp_label}] ${claim.text.slice(0, 60)}`
        : claim.text.slice(0, 60);

      marker.addEventListener('click', (e) => {
        e.stopPropagation();
        seekVideo(claim.start_time);
      });

      progressBar.style.position = progressBar.style.position || 'relative';
      progressBar.appendChild(marker);
    }
  }

  // ── Platform-specific DOM extractors ────────────────────────────────────────

  const extractors = {
    youtube: () => {
      const targets = [];

      // Video description — try multiple selectors for different YouTube layouts
      const descSelectors = [
        'ytd-text-inline-expander#description-inline-expander',
        '#description-inline-expander',
        'ytd-watch-metadata #description',
        '#description.ytd-watch-metadata',
        '#description-inner',
        'ytd-expander#description .content',
        'ytd-expander#description',
        '#meta-contents ytd-expander',
        '#info-contents ytd-expander',
        'ytd-watch-metadata ytd-text-inline-expander',
        'ytd-structured-description-content-renderer',
      ];
      for (const sel of descSelectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText && el.innerText.length > 20) {
          targets.push({ element: el, text: el.innerText, type: 'description' });
          break;
        }
      }

      // Video title
      const titleSelectors = [
        'h1.ytd-watch-metadata yt-formatted-string',
        'ytd-watch-metadata h1 yt-formatted-string',
        'h1.title yt-formatted-string',
        '#title h1',
        '#title yt-formatted-string',
        'ytd-watch-metadata h1',
      ];
      for (const sel of titleSelectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText && el.innerText.length > 5) {
          targets.push({ element: el, text: el.innerText, type: 'title' });
          break;
        }
      }

      // Pinned/top comments
      const comments = document.querySelectorAll(
        'ytd-comment-thread-renderer #content-text'
      );
      comments.forEach((el) => {
        if (el.innerText && el.innerText.length > MIN_TEXT_LENGTH) {
          targets.push({ element: el, text: el.innerText, type: 'comment' });
        }
      });

      console.log(`[Veritas] YouTube extractor found: ${targets.map(t => `${t.type}(${t.text.length}ch)`).join(', ') || 'nothing'}`);
      return targets;
    },

    twitter: () => {
      const targets = [];

      // Tweet text content
      const tweets = document.querySelectorAll(
        '[data-testid="tweetText"], ' +
        'article [lang] div[dir="auto"]'
      );
      tweets.forEach((el) => {
        if (el.innerText && el.innerText.length > MIN_TEXT_LENGTH) {
          targets.push({ element: el.closest('article') || el, text: el.innerText, type: 'tweet' });
        }
      });

      return targets;
    },

    tiktok: () => {
      const targets = [];

      // Video description/caption
      const descriptions = document.querySelectorAll(
        '[data-e2e="browse-video-desc"], ' +
        '[data-e2e="video-desc"], ' +
        '.tiktok-1ejylhp-DivContainer span, ' +
        '[class*="DivVideoInfoContainer"] [class*="SpanText"]'
      );
      descriptions.forEach((el) => {
        if (el.innerText && el.innerText.length > MIN_TEXT_LENGTH) {
          targets.push({ element: el, text: el.innerText, type: 'caption' });
        }
      });

      // TikTok Shop product titles/descriptions
      const shopEls = document.querySelectorAll(
        '[data-e2e="product-card"], ' +
        '[class*="ProductCard"], ' +
        '[class*="product-info"]'
      );
      shopEls.forEach((el) => {
        if (el.innerText && el.innerText.length > MIN_TEXT_LENGTH) {
          targets.push({ element: el, text: el.innerText, type: 'product' });
        }
      });

      return targets;
    },
  };

  // ── Overlay (floats on video player) ──────────────────────────────────────

  function getVideoContainer() {
    if (PLATFORM === 'youtube') {
      return document.querySelector('#movie_player') ||
             document.querySelector('.html5-video-player') ||
             document.querySelector('#player-container-inner');
    }
    if (PLATFORM === 'tiktok') {
      return document.querySelector('[data-e2e="browse-video"] .tiktok-web-player') ||
             document.querySelector('[data-e2e="browse-video"] video')?.parentElement ||
             document.querySelector('[class*="DivBasicPlayerWrapper"]');
    }
    if (PLATFORM === 'twitter') {
      return document.querySelector('[data-testid="videoPlayer"]') ||
             document.querySelector('article video')?.parentElement;
    }
    return null;
  }

  function addClaims(newClaims) {
    const existing = new Set(collectedClaims.map(c => c.text.toLowerCase()));
    for (const claim of newClaims) {
      if (!existing.has(claim.text.toLowerCase())) {
        collectedClaims.push(claim);
        existing.add(claim.text.toLowerCase());
      }
    }
    renderOverlay();
  }

  function renderOverlay() {
    // Remove existing overlay
    document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());

    if (collectedClaims.length === 0) return;

    const container = getVideoContainer();
    if (!container) {
      console.log('[Veritas] No video container found — retrying in 2s');
      setTimeout(renderOverlay, 2000);
      return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'veritas-live-overlay';
    overlay.setAttribute('data-veritas', 'true');

    const highRisk = collectedClaims.filter(c => c.risk_level === 'high');
    const medRisk = collectedClaims.filter(c => c.risk_level === 'medium');
    const severity = highRisk.length > 0 ? 'high' : medRisk.length > 0 ? 'medium' : 'low';
    overlay.classList.add(`veritas-severity-${severity}`);

    // Header with title, claim count, and close/minimize buttons
    const header = document.createElement('div');
    header.className = 'veritas-header';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'veritas-header-left';
    headerLeft.innerHTML = `
      <span class="veritas-logo">Veritas</span>
      <span class="veritas-claim-count">${collectedClaims.length} claim${collectedClaims.length !== 1 ? 's' : ''}</span>
    `;

    const closeBtn = document.createElement('span');
    closeBtn.className = 'veritas-close-btn';
    closeBtn.textContent = '\u2715';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      overlay.remove();
    });

    header.appendChild(headerLeft);
    header.appendChild(closeBtn);

    // Severity bar
    const severityBar = document.createElement('div');
    severityBar.className = 'veritas-severity-bar';

    // Claims list — shown by default
    const claimsList = document.createElement('div');
    claimsList.className = 'veritas-claims-list';

    collectedClaims.forEach((claim) => {
      const claimEl = document.createElement('div');
      claimEl.className = `veritas-claim veritas-claim-${claim.risk_level}`;

      const timestampHtml = claim.timestamp_label
        ? `<span class="veritas-timestamp" data-seek="${claim.start_time || 0}">${escapeHtml(claim.timestamp_label)}</span>`
        : '';

      claimEl.innerHTML = `
        <div class="veritas-claim-header">
          <span class="veritas-risk-dot"></span>
          ${timestampHtml}
          <span class="veritas-claim-text">${escapeHtml(claim.text)}</span>
        </div>
        ${claim.brief_verdict ? `<div class="veritas-verdict">${escapeHtml(claim.brief_verdict)}</div>` : ''}
        <div class="veritas-claim-meta">
          <span class="veritas-category">${escapeHtml(claim.category.replace(/_/g, ' '))}</span>
          <span class="veritas-risk">${claim.risk_level} risk</span>
        </div>
      `;

      // Bind click-to-seek on timestamp badge
      const tsBtn = claimEl.querySelector('.veritas-timestamp');
      if (tsBtn) {
        tsBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          seekVideo(parseFloat(tsBtn.dataset.seek));
        });
      }

      claimsList.appendChild(claimEl);
    });

    const deepCheck = document.createElement('button');
    deepCheck.className = 'veritas-deep-check-btn';
    deepCheck.textContent = 'Full fact-check';
    deepCheck.addEventListener('click', (e) => {
      e.stopPropagation();
      const text = collectedClaims.map(c => c.text).join('. ');
      chrome.runtime.sendMessage({
        type: 'LIVE_DEEP_CHECK',
        text,
        claims: collectedClaims,
      });
    });
    claimsList.appendChild(deepCheck);

    // Minimize: clicking header toggles claims list visibility
    header.addEventListener('click', (e) => {
      if (e.target.closest('.veritas-close-btn')) return;
      e.stopPropagation();
      const isVisible = claimsList.style.display !== 'none';
      claimsList.style.display = isVisible ? 'none' : 'block';
      severityBar.style.display = isVisible ? 'none' : 'block';
    });
    header.style.cursor = 'pointer';

    overlay.appendChild(header);
    overlay.appendChild(severityBar);
    overlay.appendChild(claimsList);

    container.style.position = container.style.position || 'relative';
    container.appendChild(overlay);
    console.log(`[Veritas] Overlay injected on video player with ${collectedClaims.length} claim(s)`);

    // Inject progress bar markers for claims with timestamps
    const timestampedClaims = collectedClaims.filter(c => c.start_time != null);
    if (timestampedClaims.length > 0) {
      injectProgressMarkers(timestampedClaims);
    }
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  // ── Context invalidation handling ───────────────────────────────────────────

  function isContextInvalidated(err) {
    return err?.message?.includes('Extension context invalidated');
  }

  function teardown() {
    if (!contextValid) return; // already torn down
    contextValid = false;
    scanEnabled = false;
    console.log('[Veritas] Extension context invalidated — tearing down');
    if (scanDebounce) clearTimeout(scanDebounce);
    if (urlCheckInterval) clearInterval(urlCheckInterval);
    observer.disconnect();
    document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());
    clearProgressMarkers();
  }

  // ── Scan orchestration ──────────────────────────────────────────────────────

  async function scanPage() {
    if (!scanEnabled || !contextValid) return;

    const extractor = extractors[PLATFORM];
    if (!extractor) return;

    const targets = extractor();
    const toScan = [];

    for (const target of targets) {
      if (!target.text || target.text.length < MIN_TEXT_LENGTH) continue;
      if (scannedElements.has(target.element)) continue;

      const hash = textHash(target.text);
      if (scannedTexts.has(hash)) {
        scannedElements.add(target.element);
        continue;
      }

      if (!hasFitnessContent(target.text)) {
        scannedTexts.add(hash);
        scannedElements.add(target.element);
        continue;
      }

      toScan.push({ ...target, hash });
    }

    if (toScan.length > 0) {
      console.log(`[Veritas] Scanning ${toScan.length} element(s) on ${PLATFORM}...`);

      for (const target of toScan) {
        scannedTexts.add(target.hash);
        scannedElements.add(target.element);

        try {
          console.log(`[Veritas] Sending LIVE_SCAN for "${target.type}" (${target.text.length} chars)...`);
          const response = await chrome.runtime.sendMessage({
            type: 'LIVE_SCAN',
            text: target.text,
            url: location.href,
            platform: PLATFORM,
            contentType: target.type,
            hash: target.hash,
          });

          console.log('[Veritas] Response:', JSON.stringify(response, null, 2));

          if (response && response.claims && response.claims.length > 0) {
            console.log(`[Veritas] Adding ${response.claims.length} claim(s) to overlay`);
            addClaims(response.claims);
          } else {
            console.log('[Veritas] No claims returned — skipping');
          }
        } catch (err) {
          if (isContextInvalidated(err)) { teardown(); return; }
          console.error('[Veritas] Scan error:', err);
        }
      }
    }

    // ── YouTube transcript scanning ──────────────────────────────────────────
    if (PLATFORM === 'youtube' && !scannedTexts.has('__transcript__')) {
      await scanTranscript();
    }
  }

  async function scanTranscript(retry = false) {
    // Mark as scanned immediately to prevent duplicate calls from scanPage()
    scannedTexts.add('__transcript__');

    // Extract caption URL (tries inline scripts, then innertube API)
    let captionUrl = await extractCaptionUrl();

    if (!captionUrl && !retry) {
      console.log('[Veritas] No captions found — retrying in 3s');
      await new Promise(r => setTimeout(r, 3000));
      captionUrl = await extractCaptionUrl();
    }

    let segments = null;

    if (captionUrl) {
      segments = await fetchTranscript(captionUrl);
    }

    // Fallback: extract from the video element's text tracks (auto-captions)
    if (!segments || segments.length === 0) {
      segments = extractFromTextTracks();
    }

    if (segments && segments.length > 0) {
      console.log(`[Veritas] Transcript extracted: ${segments.length} segments`);

      const transcriptText = chunkTranscript(segments);
      if (transcriptText.length >= MIN_TEXT_LENGTH && hasFitnessContent(transcriptText)) {
        const hash = textHash(transcriptText);
        try {
          console.log(`[Veritas] Sending LIVE_SCAN for "transcript" (${transcriptText.length} chars)...`);
          const response = await chrome.runtime.sendMessage({
            type: 'LIVE_SCAN',
            text: transcriptText,
            url: location.href,
            platform: PLATFORM,
            contentType: 'transcript',
            hash,
          });

          if (response && response.claims && response.claims.length > 0) {
            console.log(`[Veritas] Adding ${response.claims.length} transcript claim(s) to overlay`);
            addClaims(response.claims);
          } else {
            console.log('[Veritas] No transcript claims returned');
          }
          return;
        } catch (err) {
          if (isContextInvalidated(err)) { teardown(); return; }
          console.error('[Veritas] Transcript scan error:', err);
          return;
        }
      }
    }

    // Fallback: combine title + description + comments into a single scan
    console.log('[Veritas] No transcript available — falling back to combined page text');
    await scanCombinedPageText();
  }

  async function scanCombinedPageText() {
    if (!contextValid) return;

    // Gather all available page text (title, description, comments)
    const extractor = extractors[PLATFORM];
    if (!extractor) return;

    const targets = extractor();
    const parts = [];
    for (const t of targets) {
      if (t.text && t.text.length > 5) {
        parts.push(t.text);
      }
    }

    const combined = parts.join('\n\n').trim().slice(0, 5000);
    console.log(`[Veritas] Combined text: ${combined.length} chars from ${parts.length} source(s), preview: "${combined.slice(0, 120)}..."`);
    if (combined.length < MIN_TEXT_LENGTH) {
      console.log('[Veritas] Combined text too short — skipping');
      return;
    }

    const hash = textHash(combined);
    if (scannedTexts.has(hash)) return;
    scannedTexts.add(hash);

    if (!hasFitnessContent(combined)) {
      console.log('[Veritas] Combined page text has no fitness content — skipping');
      return;
    }

    try {
      console.log(`[Veritas] Sending LIVE_SCAN for combined page text (${combined.length} chars)...`);
      const response = await chrome.runtime.sendMessage({
        type: 'LIVE_SCAN',
        text: combined,
        url: location.href,
        platform: PLATFORM,
        contentType: 'description',
        hash,
      });

      if (response && response.claims && response.claims.length > 0) {
        console.log(`[Veritas] Adding ${response.claims.length} claim(s) from combined text`);
        addClaims(response.claims);
      } else {
        console.log('[Veritas] No claims from combined page text');
      }
    } catch (err) {
      if (isContextInvalidated(err)) { teardown(); return; }
      console.error('[Veritas] Combined text scan error:', err);
    }
  }

  function debouncedScan() {
    if (scanDebounce) clearTimeout(scanDebounce);
    scanDebounce = setTimeout(scanPage, DEBOUNCE_MS);
  }

  // ── MutationObserver for SPA content ────────────────────────────────────────

  const observer = new MutationObserver((mutations) => {
    let hasNewContent = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE &&
              !node.hasAttribute('data-veritas')) {
            hasNewContent = true;
            break;
          }
        }
      }
      if (hasNewContent) break;
    }
    if (hasNewContent) debouncedScan();
  });

  // ── URL change detection (for SPA navigation) ──────────────────────────────

  let lastUrl = location.href;
  function checkUrlChange() {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      // Remove stale overlays, progress markers, and reset all state for the new video
      document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());
      clearProgressMarkers();
      collectedClaims = [];
      scannedTexts.clear();
      debouncedScan();
    }
  }

  // ── Settings listener ───────────────────────────────────────────────────────

  function loadSettings() {
    chrome.storage.sync.get({ liveScanEnabled: true }, ({ liveScanEnabled }) => {
      scanEnabled = liveScanEnabled;
      if (scanEnabled) {
        debouncedScan();
      } else {
        document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());
      }
    });
  }

  chrome.storage.onChanged.addListener((changes) => {
    if (changes.liveScanEnabled) {
      scanEnabled = changes.liveScanEnabled.newValue;
      if (!scanEnabled) {
        document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());
      } else {
        debouncedScan();
      }
    }
  });

  // ── Message listener (for enabling/disabling from popup) ────────────────────

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === 'TOGGLE_LIVE_SCAN') {
      scanEnabled = message.enabled;
      if (!scanEnabled) {
        document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());
      } else {
        debouncedScan();
      }
      sendResponse({ ok: true });
      return true;
    }
    if (message.type === 'GET_LIVE_STATUS') {
      const overlays = document.querySelectorAll('.veritas-live-overlay').length;
      sendResponse({ enabled: scanEnabled, overlays, platform: PLATFORM });
      return true;
    }
  });

  // ── Boot ────────────────────────────────────────────────────────────────────

  loadSettings();

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });

  // Poll for URL changes (pushState doesn't fire popstate)
  urlCheckInterval = setInterval(checkUrlChange, 1000);

  // Initial scan after page is settled
  setTimeout(scanPage, 2000);
})();
