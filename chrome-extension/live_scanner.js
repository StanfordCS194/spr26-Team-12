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
  const scannedElementLengths = new WeakMap();
  let scanEnabled = true;
  let scanDebounce = null;
  let collectedClaims = [];
  let urlCheckInterval = null;
  let contextValid = true;
  let transcriptScanActive = false; // prevents concurrent transcript scans
  const DEBOUNCE_MS = 1500;
  const MIN_TEXT_LENGTH = 40;

  // Health & fitness keywords for client-side pre-filter.
  // Broad enough to catch general health claims (not just gym/supplement content).
  const FITNESS_KEYWORDS = [
    // Supplements & ingredients
    'creatine', 'bcaa', 'protein', 'supplement', 'collagen', 'tongkat',
    'ashwagandha', 'whey', 'casein', 'amino', 'pre-workout', 'probiotic',
    'vitamin', 'magnesium', 'zinc', 'omega-3', 'fish oil', 'shilajit',
    'melatonin', 'electrolytes', 'antioxidant', 'superfood',
    // Hormones & biology
    'testosterone', 'estrogen', 'cortisol', 'hormone', 'insulin',
    'metabolism', 'anabolic', 'endocrine', 'thyroid', 'serotonin',
    'dopamine', 'adrenaline', 'growth hormone',
    // Fitness & training
    'muscle', 'workout', 'hypertrophy', 'gains', 'bulking', 'cutting',
    'fat burn', 'fat burner', 'weight loss', 'cardio', 'hiit',
    'shred', 'lean', 'toned', 'recovery', 'overtraining',
    // Nutrition & diet
    'macros', 'calories', 'keto', 'intermittent fasting', 'carbs',
    'glycemic', 'cholesterol', 'saturated fat', 'sugar', 'fiber',
    'gut health', 'microbiome', 'detox', 'cleanse', 'diet',
    // General health & medical
    'blood pressure', 'heart disease', 'diabetes', 'cancer risk',
    'inflammation', 'immune', 'longevity', 'anti-aging', 'skin health',
    'joint', 'bone density', 'fertility', 'sperm', 'libido',
    'sleep', 'insomnia', 'circadian', 'stress', 'anxiety',
    'posture', 'injury', 'chronic pain', 'arthritis',
    'urologist', 'cardiologist', 'doctor', 'clinical study',
    'side effect', 'health benefit', 'peer reviewed', 'evidence',
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

  // ── YouTube transcript extraction (via backend SerpAPI proxy) ─────────────

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

  async function fetchTranscriptFromBackend(videoId) {
    try {
      console.log(`[Veritas] Fetching transcript from backend for video ${videoId}...`);
      const response = await chrome.runtime.sendMessage({
        type: 'FETCH_TRANSCRIPT',
        videoId,
      });

      if (response.error) {
        console.log(`[Veritas] Backend transcript error: ${response.error}`);
        return null;
      }

      const segments = (response.segments || [])
        .filter(seg => seg.snippet && seg.snippet.trim())
        .map(seg => ({
          start: seg.start_ms / 1000,
          dur: (seg.end_ms - seg.start_ms) / 1000,
          text: seg.snippet.trim(),
        }));

      if (segments.length > 0) {
        console.log(`[Veritas] Backend returned ${segments.length} transcript segments (${response.fetch_time_ms}ms)`);
      } else {
        console.log('[Veritas] Backend returned no transcript segments');
      }
      return segments.length > 0 ? segments : null;
    } catch (err) {
      console.log(`[Veritas] Backend transcript fetch failed: ${err.message}`);
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

  let overlayExpanded = false;
  let overlayDismissed = false;
  let timestampWatcher = null;
  let shownClaimTimestamps = new Set();

  function addClaims(newClaims) {
    const existing = new Set(collectedClaims.map(c => c.text.toLowerCase()));
    for (const claim of newClaims) {
      if (!existing.has(claim.text.toLowerCase())) {
        collectedClaims.push(claim);
        existing.add(claim.text.toLowerCase());
      }
    }
    renderAlertPill();
    startTimestampWatcher();
  }

  function getSeverity() {
    const highRisk = collectedClaims.filter(c => c.risk_level === 'high');
    const medRisk = collectedClaims.filter(c => c.risk_level === 'medium');
    return highRisk.length > 0 ? 'high' : medRisk.length > 0 ? 'medium' : 'low';
  }

  // ── Alert pill (compact notification) ────────────────────────────────────

  function renderAlertPill() {
    if (overlayExpanded || overlayDismissed) return;
    if (collectedClaims.length === 0) return;

    // Remove existing pill
    document.querySelectorAll('.veritas-alert-pill').forEach(el => el.remove());

    const container = getVideoContainer();
    if (!container) return;

    const severity = getSeverity();
    const pill = document.createElement('div');
    pill.className = 'veritas-alert-pill';
    pill.setAttribute('data-veritas', 'true');
    pill.innerHTML = `
      <span class="veritas-alert-dot veritas-alert-dot-${severity}"></span>
      <span class="veritas-alert-logo">Veritas</span>
      <span class="veritas-alert-text">${collectedClaims.length} claim${collectedClaims.length !== 1 ? 's' : ''} to verify</span>
      <span class="veritas-alert-expand">\u203A</span>
    `;

    pill.addEventListener('click', (e) => {
      e.stopPropagation();
      expandOverlay();
    });

    container.style.position = container.style.position || 'relative';
    container.appendChild(pill);
    console.log(`[Veritas] Alert pill shown: ${collectedClaims.length} claim(s)`);

    // Inject progress bar markers
    const timestampedClaims = collectedClaims.filter(c => c.start_time != null);
    if (timestampedClaims.length > 0) {
      injectProgressMarkers(timestampedClaims);
    }
  }

  // ── Expanded overlay (slides in from right) ──────────────────────────────

  function expandOverlay(highlightClaimIndex = -1) {
    overlayExpanded = true;

    // Remove pill
    document.querySelectorAll('.veritas-alert-pill').forEach(el => el.remove());
    // Remove existing overlay
    document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());

    if (collectedClaims.length === 0) return;

    const container = getVideoContainer();
    if (!container) {
      console.log('[Veritas] No video container found — retrying in 2s');
      setTimeout(() => expandOverlay(highlightClaimIndex), 2000);
      return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'veritas-live-overlay veritas-slide-in';
    overlay.setAttribute('data-veritas', 'true');

    const severity = getSeverity();
    overlay.classList.add(`veritas-severity-${severity}`);

    // Header
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
      collapseOverlay();
    });

    header.appendChild(headerLeft);
    header.appendChild(closeBtn);

    // Severity bar
    const severityBar = document.createElement('div');
    severityBar.className = 'veritas-severity-bar';

    // Claims list (scrollable)
    const claimsList = document.createElement('div');
    claimsList.className = 'veritas-claims-list';

    collectedClaims.forEach((claim, idx) => {
      const claimEl = document.createElement('div');
      claimEl.className = `veritas-claim veritas-claim-${claim.risk_level}`;
      if (idx === highlightClaimIndex) {
        claimEl.classList.add('veritas-claim-active');
      }
      claimEl.setAttribute('data-claim-idx', idx);

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

    // Minimize: clicking header collapses back to pill
    header.addEventListener('click', (e) => {
      if (e.target.closest('.veritas-close-btn')) return;
      e.stopPropagation();
      collapseOverlay();
    });
    header.style.cursor = 'pointer';

    overlay.appendChild(header);
    overlay.appendChild(severityBar);
    overlay.appendChild(claimsList);

    container.style.position = container.style.position || 'relative';
    container.appendChild(overlay);
    console.log(`[Veritas] Overlay expanded with ${collectedClaims.length} claim(s)`);

    // Scroll to highlighted claim
    if (highlightClaimIndex >= 0) {
      const activeEl = claimsList.querySelector('.veritas-claim-active');
      if (activeEl) {
        setTimeout(() => activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
      }
    }

    // Inject progress bar markers
    const timestampedClaims = collectedClaims.filter(c => c.start_time != null);
    if (timestampedClaims.length > 0) {
      injectProgressMarkers(timestampedClaims);
    }
  }

  function collapseOverlay() {
    overlayExpanded = false;
    const overlay = document.querySelector('.veritas-live-overlay');
    if (overlay) {
      overlay.classList.remove('veritas-slide-in');
      overlay.classList.add('veritas-slide-out');
      overlay.addEventListener('animationend', () => {
        overlay.remove();
        renderAlertPill();
      }, { once: true });
    } else {
      renderAlertPill();
    }
  }

  // ── Timestamp watcher (triggers slide-in at claim timestamps) ────────────

  function startTimestampWatcher() {
    if (timestampWatcher) return; // already running
    if (PLATFORM !== 'youtube') return;

    const video = document.querySelector('video');
    if (!video) return;

    timestampWatcher = setInterval(() => {
      if (overlayDismissed) { clearInterval(timestampWatcher); return; }

      const currentTime = video.currentTime;
      for (let i = 0; i < collectedClaims.length; i++) {
        const claim = collectedClaims[i];
        if (claim.start_time == null) continue;

        // Trigger when video enters the claim's time window (within 2 seconds)
        const key = `${i}_${claim.start_time}`;
        if (shownClaimTimestamps.has(key)) continue;

        if (currentTime >= claim.start_time && currentTime <= claim.start_time + 3) {
          shownClaimTimestamps.add(key);
          console.log(`[Veritas] Timestamp hit: claim ${i} at ${formatTimestamp(claim.start_time)}`);

          // If not expanded, slide the overlay in and highlight this claim
          if (!overlayExpanded) {
            expandOverlay(i);
          } else {
            // Already expanded — just highlight and scroll to the active claim
            highlightActiveClaim(i);
          }
          break;
        }
      }
    }, 500);
  }

  function highlightActiveClaim(idx) {
    const overlay = document.querySelector('.veritas-live-overlay');
    if (!overlay) return;

    // Remove previous highlights
    overlay.querySelectorAll('.veritas-claim-active').forEach(el =>
      el.classList.remove('veritas-claim-active')
    );

    const claimEl = overlay.querySelector(`[data-claim-idx="${idx}"]`);
    if (claimEl) {
      claimEl.classList.add('veritas-claim-active');
      claimEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
    if (timestampWatcher) clearInterval(timestampWatcher);
    observer.disconnect();
    document.querySelectorAll('.veritas-live-overlay').forEach(el => el.remove());
    document.querySelectorAll('.veritas-alert-pill').forEach(el => el.remove());
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

      // Rescan elements whose text grew significantly (YouTube lazy-loads
      // descriptions — first render is often truncated to ~400 chars).
      const prevLen = scannedElementLengths.get(target.element) || 0;
      const grewSignificantly = prevLen > 0 && target.text.length > prevLen * 2 && target.text.length - prevLen > 200;
      if (scannedElements.has(target.element) && !grewSignificantly) continue;

      const hash = textHash(target.text);
      if (scannedTexts.has(hash)) {
        scannedElements.add(target.element);
        scannedElementLengths.set(target.element, target.text.length);
        continue;
      }

      if (!hasFitnessContent(target.text)) {
        scannedTexts.add(hash);
        scannedElements.add(target.element);
        scannedElementLengths.set(target.element, target.text.length);
        continue;
      }

      toScan.push({ ...target, hash });
    }

    if (toScan.length > 0) {
      console.log(`[Veritas] Scanning ${toScan.length} element(s) on ${PLATFORM}...`);

      for (const target of toScan) {
        scannedTexts.add(target.hash);
        scannedElements.add(target.element);
        scannedElementLengths.set(target.element, target.text.length);

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
    if (PLATFORM === 'youtube' && !transcriptScanActive && !scannedTexts.has('__transcript_done__')) {
      await scanTranscript();
    }
  }

  async function scanTranscript() {
    // Concurrency lock — only one transcript scan can run at a time
    if (transcriptScanActive) return;
    transcriptScanActive = true;

    try {
      const videoId = getVideoId();
      if (!videoId) {
        console.log('[Veritas] No video ID found — skipping transcript');
        return;
      }

      const segments = await fetchTranscriptFromBackend(videoId);

      if (segments && segments.length > 0) {
        scannedTexts.add('__transcript_done__');
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
          } catch (err) {
            if (isContextInvalidated(err)) { teardown(); return; }
            console.error('[Veritas] Transcript scan error:', err);
          }
        } else {
          console.log('[Veritas] Transcript too short or no fitness content');
        }
        return;
      }

      // No transcript — fall back to combined page text (title + description)
      scannedTexts.add('__transcript_done__');
      console.log('[Veritas] No transcript available — falling back to combined page text');
      await scanCombinedPageText();
    } finally {
      transcriptScanActive = false;
    }
  }

  async function scanCombinedPageText() {
    if (!contextValid) return;

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
      document.querySelectorAll('.veritas-alert-pill').forEach(el => el.remove());
      clearProgressMarkers();
      collectedClaims = [];
      scannedTexts.clear();
      transcriptScanActive = false;
      overlayExpanded = false;
      overlayDismissed = false;
      shownClaimTimestamps.clear();
      if (timestampWatcher) { clearInterval(timestampWatcher); timestampWatcher = null; }
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

  // Initial scan after page settles
  setTimeout(scanPage, 2000);
})();
