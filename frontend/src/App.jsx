import { useEffect, useRef, useState } from 'react';

const THEME_KEY = 'sfc.theme';

function detectPlatform(url) {
  const value = (url || '').toLowerCase();
  if (value.includes('reddit.com')) return 'reddit';
  if (value.includes('youtube.com') || value.includes('youtu.be')) return 'youtube';
  if (value.includes('tiktok.com')) return 'tiktok';
  if (/^https?:\/\//.test(value)) return 'article';
  return null;
}

function useTheme() {
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme || 'light'
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch {}
  }, [theme]);
  return [theme, setTheme];
}

function ThemeToggle({ theme, setTheme }) {
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <button
      className="icon-btn"
      onClick={() => setTheme(next)}
      title={`Switch to ${next} mode`}
      aria-label={`Switch to ${next} mode`}
    >
      {theme === 'dark' ? 'L' : 'D'}
    </button>
  );
}

function ProgressList({ stage }) {
  const steps = [
    { id: 'transcribe', label: 'Preparing transcript' },
    { id: 'extract', label: 'Extracting claims' },
    { id: 'search', label: 'Searching sources' },
    { id: 'checks', label: 'Cross-checking evidence' },
    { id: 'judge', label: 'Finalizing result' },
  ];
  const activeByStage = {
    processing: 1,
    checking: 3,
  };
  const activeIndex = activeByStage[stage] ?? 0;
  return (
    <ul className="progress-list">
      {steps.map((step, index) => {
        const klass = index < activeIndex ? 'done' : index === activeIndex ? 'active' : '';
        return (
          <li key={step.id} className={klass}>
            <span className="status">{index < activeIndex ? '✓' : ''}</span>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

function hasSystemVerdict(item) {
  return ['strong_agreement', 'partial_agreement'].includes(item.agreement.agreement_level);
}

function directionLabel(direction) {
  const labels = {
    supports: 'Supported',
    partially_supports: 'Partly supported',
    mixed: 'Mixed',
    weak: 'Weak evidence',
    contradicts: 'Contradicted',
    insufficient: 'Insufficient evidence',
  };
  return labels[direction] || direction.replaceAll('_', ' ');
}

function EvidenceBadge({ direction }) {
  return <span className={`direction dir-${direction}`}>{directionLabel(direction)}</span>;
}

function SystemStatusBadge({ item }) {
  if (item.status === 'no_evidence' || item.agreement.agreement_level === 'insufficient_sources') {
    return <span className="agreement agr-insufficient_sources">No verdict</span>;
  }
  if (!hasSystemVerdict(item)) {
    return <span className="agreement agr-conclusion_disagreement">Needs review</span>;
  }
  return <span className="agreement agr-strong_agreement">Verified result</span>;
}

function sourceLabel(provider) {
  if (provider === 'curated_corpus') return 'research index';
  if (provider === 'pubmed') return 'PubMed';
  if (provider === 'tavily') return 'web search';
  return 'source';
}

function ClaimEditor({ claims, setClaims }) {
  function updateClaim(index, patch) {
    setClaims(claims.map((claim, i) => (i === index ? { ...claim, ...patch } : claim)));
  }
  function removeClaim(index) {
    setClaims(claims.filter((_, i) => i !== index));
  }
  function addClaim() {
    setClaims([
      ...claims,
      {
        claim_id: `claim_${claims.length + 1}`,
        raw_claim: '',
        normalized_claim: '',
        category: 'other',
        risk_level: 'low',
        selected: true,
      },
    ]);
  }

  return (
    <div className="claim-editor">
      {claims.map((claim, index) => (
        <div className="claim-edit" key={claim.claim_id || index}>
          <label className="check-row">
            <input
              type="checkbox"
              checked={claim.selected !== false}
              onChange={(e) => updateClaim(index, { selected: e.target.checked })}
            />
            <span>Fact-check this claim</span>
          </label>
          <textarea
            value={claim.normalized_claim}
            onChange={(e) => updateClaim(index, {
              normalized_claim: e.target.value,
              raw_claim: claim.raw_claim || e.target.value,
            })}
            placeholder="Edit this into one clear, factual claim"
            maxLength={350}
          />
          <div className="claim-meta-row">
            <select
              value={claim.category || 'other'}
              onChange={(e) => updateClaim(index, { category: e.target.value })}
            >
              {['supplement', 'training', 'nutrition', 'weight_loss', 'muscle_gain', 'hormones', 'recovery', 'sleep', 'injury', 'product_marketing', 'medical_boundary', 'other'].map((item) => (
                <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>
              ))}
            </select>
            <select
              value={claim.risk_level || 'low'}
              onChange={(e) => updateClaim(index, { risk_level: e.target.value })}
            >
              <option value="low">low risk</option>
              <option value="medium">medium risk</option>
              <option value="high">high risk</option>
            </select>
            <button className="ghost" onClick={() => removeClaim(index)}>Remove</button>
          </div>
        </div>
      ))}
      <button className="ghost" onClick={addClaim}>Add claim</button>
    </div>
  );
}
function RecommendationsSection({ item }) {
  const recs = item.recommendations || [];
  if (!recs.length) return null;
  const direction = item.agreement?.final_direction;
  const isContradicted = direction === 'contradicts';
  const isWeak = direction === 'weak' || direction === 'insufficient';
  let caveat = 'Third-party verified options if you choose to supplement. Veritas is not a substitute for medical advice.';
  if (isContradicted) {
    caveat = 'Veritas does not endorse this claim. These are simply third-party verified options for the supplement involved.';
  } else if (isWeak) {
    caveat = 'Evidence is limited. If you still choose to try this supplement, these are third-party verified options.';
  }
  return (
    <>
      <div className="evidence-h">Verified products ({recs.length})</div>
      <p className="muted-note" style={{ marginTop: -4, marginBottom: 10 }}>{caveat}</p>
      <div className="product-grid">
        {recs.map((rec) => (
          <a className="product-card" key={rec.id} href={rec.url} target="_blank" rel="noreferrer">
            <div className="product-thumb" data-initials={(rec.brand || 'V').slice(0, 1).toUpperCase()}>
              {rec.image_url && (
                <img
                  src={rec.image_url}
                  alt={`${rec.brand} ${rec.product_name}`}
                  referrerPolicy="no-referrer"
                  onError={(event) => { event.currentTarget.style.visibility = 'hidden'; }}
                />
              )}
            </div>
            <div className="product-body">
              <div className="product-brand">{rec.brand}</div>
              <div className="product-name">{rec.product_name}</div>
              {rec.certification && <span className="product-cert">{rec.certification}</span>}
              {rec.form && (
                <div className="product-meta">{rec.form}{rec.price_band ? ` · ${rec.price_band}` : ''}</div>
              )}
              {rec.note && <div className="product-note">{rec.note}</div>}
              <span className="product-link">View product →</span>
            </div>
          </a>
        ))}
      </div>
      <p className="product-disclaimer">
        Dietary supplements are not FDA-approved like prescription drugs. Veritas only surfaces products with the strongest available regulated bar &mdash; third-party verification (NSF Certified for Sport, USP Verified, or Informed Sport / Informed Choice) made in FDA-registered cGMP facilities.
      </p>
    </>
  );
}
function ReportView({ report }) {
  const verdictCount = report.claims.filter(hasSystemVerdict).length;
  const reviewCount = report.claims.length - verdictCount;
  return (
    <div className="report-stack">
      <div className="panel report-hero">
        <div>
          <div className="label">Clip report</div>
          <h2>{report.clip_credibility_score}/100 credibility</h2>
          <p>{report.overall_summary}</p>
          {reviewCount > 0 && (
            <p className="muted-note">{reviewCount} claim(s) need more review before Veritas can rate them clearly.</p>
          )}
          <details className="score-explainer">
            <summary>How is this score calculated?</summary>
            <p>
              Veritas starts every clip at <strong>75/100</strong> and adjusts based on how the
              evidence lands for each claim. Claims that are clearly <em>supported</em> raise the score,
              while <em>weak</em>, <em>contradicted</em>, or <em>insufficient</em> claims lower it.
              High-risk claims that come back weak or contradicted carry an extra penalty,
              and claims where the evidence review couldn&rsquo;t reach a clear answer take a smaller deduction.
              The score is capped between 0 and 100.
            </p>
            <p className="muted-note" style={{ marginTop: 6 }}>
              Think of it as &ldquo;how trustworthy was this clip overall&rdquo; &mdash; not a medical rating.
            </p>
          </details>
        </div>
        {report.needs_human_review && <span className="review-flag">Needs review</span>}
      </div>

      <div className="panel">
        <div className="evidence-h" style={{ marginTop: 0 }}>Transcript</div>
        <p className="transcript-box">{report.transcript}</p>
      </div>

      {report.claims.map((item) => (
        <div className="panel claim-result" key={item.claim.claim_id}>
          <div className="claim-result-head">
            <div>
              <div className="label">{item.claim.category.replaceAll('_', ' ')} · {item.claim.risk_level} risk</div>
              <h3>{item.claim.normalized_claim}</h3>
            </div>
            <div className="badge-row">
              {hasSystemVerdict(item) && <EvidenceBadge direction={item.agreement.final_direction} />}
              <SystemStatusBadge item={item} />
            </div>
          </div>

          <p className="summary">
            {hasSystemVerdict(item)
              ? item.agreement.summary
              : 'Veritas needs a clearer evidence signal before rating this claim.'}
          </p>
          <div className="why">{item.agreement.why}</div>

          <div className="evidence-h">Sources ({item.sources.length})</div>
          {item.sources.length === 0 && <div className="muted-note">No sources found for this claim.</div>}
          {item.sources.map((source) => (
            <div className="source-card" key={source.url}>
              <div className="top">
                <div className="title"><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></div>
                <span className="pill">{sourceLabel(source.provider)} · q{source.quality_score}</span>
              </div>
              <div className="meta">{source.source_type}{source.year ? ` · ${source.year}` : ''}</div>
              <div className="note">{source.summary || source.snippet || 'No snippet available.'}</div>
            </div>
          ))}

          <RecommendationsSection item={item} />
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [theme, setTheme] = useTheme();
  const [tab, setTab] = useState('text');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [audioFile, setAudioFile] = useState(null);
  const [drag, setDrag] = useState(false);

  const [creatorName, setCreatorName] = useState('');
  const [brandName, setBrandName] = useState('');
  const [state, setState] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [claims, setClaims] = useState([]);
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');

  const abortRef = useRef(null);

  useEffect(() => {
    function onPaste(e) {
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'));
      if (item) {
        const file = item.getAsFile();
        if (file) {
          setTab('screenshot');
          setImageFile(file);
        }
      }
    }
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, []);

  async function preprocess() {
    if (tab === 'text') {
      const response = await fetch('/api/process/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Text processing failed');
      return (await response.json()).text;
    }
    if (tab === 'link') {
      const response = await fetch('/api/process/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Link processing failed');
      return (await response.json()).text;
    }
    if (tab === 'screenshot') {
      if (!imageFile) throw new Error('No image selected.');
      const form = new FormData();
      form.append('image', imageFile);
      const response = await fetch('/api/process/screenshot', {
        method: 'POST',
        body: form,
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Screenshot processing failed');
      return (await response.json()).text;
    }
    if (tab === 'audio') {
      if (!audioFile) throw new Error('No audio selected.');
      const form = new FormData();
      form.append('audio', audioFile);
      const response = await fetch('/api/process/audio', {
        method: 'POST',
        body: form,
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Audio transcription failed');
      return (await response.json()).text;
    }
    throw new Error('Unknown input type.');
  }

  async function prepareClaims() {
    setError(''); setReport(null); setClaims([]); setTranscript('');
    abortRef.current = new AbortController();
    try {
      setState('processing');
      const processed = await preprocess();
      setTranscript(processed);
      const response = await fetch('/api/claims/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: processed, source: tab }),
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Claim extraction failed');
      const payload = await response.json();
      setClaims(payload.claims || []);
      setState('review');
    } catch (err) {
      if (err.name === 'AbortError') { setState('idle'); return; }
      setError(err.message || String(err));
      setState('error');
    }
  }

  async function runReport() {
    setError(''); setReport(null);
    abortRef.current = new AbortController();
    try {
      setState('checking');
      const response = await fetch('/api/clip-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcript,
          claims,
          source: tab,
          creator_name: creatorName || null,
          brand_name: brandName || null,
        }),
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Report generation failed');
      setReport(await response.json());
      setState('report');
    } catch (err) {
      if (err.name === 'AbortError') { setState('review'); return; }
      setError(err.message || String(err));
      setState('error');
    }
  }

  function reset() {
    setState('idle'); setTranscript(''); setClaims([]); setReport(null); setError('');
  }

  const platform = tab === 'link' ? detectPlatform(url) : null;
  const canSubmit =
    state === 'idle' &&
    ((tab === 'text' && text.trim().length > 0) ||
      (tab === 'link' && /^https?:\/\//.test(url)) ||
      (tab === 'screenshot' && imageFile) ||
      (tab === 'audio' && audioFile));
  const selectedCount = claims.filter((claim) => claim.selected !== false && claim.normalized_claim.trim()).length;

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="logo">V</div>
          <div>
            <h1>Veritas</h1>
            <span className="sub">Your fitness bro fact checker</span>
          </div>
        </div>
        <ThemeToggle theme={theme} setTheme={setTheme} />
      </header>

      {state === 'idle' && (
        <div className="panel">
          <div className="tabs">
            {['text', 'audio', 'link', 'screenshot'].map((item) => (
              <button
                key={item}
                className={`tab ${tab === item ? 'active' : ''}`}
                onClick={() => setTab(item)}
              >
                {item === 'text' ? 'Transcript' : item === 'audio' ? 'Audio' : item === 'link' ? 'Link' : 'Screenshot'}
              </button>
            ))}
          </div>

          <div className="profile-row">
            <input
              type="text"
              placeholder="Influencer handle (optional)"
              value={creatorName}
              onChange={(e) => setCreatorName(e.target.value)}
            />
            <input
              type="text"
              placeholder="Brand name (optional)"
              value={brandName}
              onChange={(e) => setBrandName(e.target.value)}
            />
          </div>

          {tab === 'text' && (
            <>
              <textarea
                placeholder="Paste a transcript, caption, or influencer rant..."
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={12000}
              />
              <div className="row">
                <button className="primary" disabled={!canSubmit} onClick={prepareClaims}>Extract claims</button>
                <span className="pill">{text.length}/12000</span>
              </div>
            </>
          )}

          {tab === 'audio' && (
            <>
              <label
                className={`dropzone ${drag ? 'drag' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault(); setDrag(false);
                  const file = e.dataTransfer.files?.[0];
                  if (file) setAudioFile(file);
                }}
              >
                <input
                  type="file"
                  accept="audio/*,video/mp4,video/quicktime,video/webm"
                  style={{ display: 'none' }}
                  onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
                />
                {audioFile ? <span>{audioFile.name} - click to replace</span> : <span>Drop an audio/video clip or click to choose one</span>}
              </label>
              <div className="row">
                <button className="primary" disabled={!canSubmit} onClick={prepareClaims}>Transcribe and extract claims</button>
                <span className="pill">Audio transcription</span>
              </div>
            </>
          )}

          {tab === 'link' && (
            <>
              <input
                type="url"
                placeholder="https://www.tiktok.com/..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <div className="row">
                <button className="primary" disabled={!canSubmit} onClick={prepareClaims}>Extract claims</button>
                {platform && <span className="pill">platform: {platform}</span>}
              </div>
            </>
          )}

          {tab === 'screenshot' && (
            <>
              <label
                className={`dropzone ${drag ? 'drag' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault(); setDrag(false);
                  const file = e.dataTransfer.files?.[0];
                  if (file) setImageFile(file);
                }}
              >
                <input
                  type="file"
                  accept="image/*"
                  style={{ display: 'none' }}
                  onChange={(e) => setImageFile(e.target.files?.[0] || null)}
                />
                {imageFile ? <span>{imageFile.name} - click to replace</span> : <span>Drop a screenshot, click to choose, or paste with Cmd+V</span>}
              </label>
              <div className="row">
                <button className="primary" disabled={!canSubmit} onClick={prepareClaims}>Extract claims</button>
              </div>
            </>
          )}
        </div>
      )}

      {(state === 'processing' || state === 'checking') && (
        <div className="panel">
          <ProgressList stage={state} />
          <div className="row">
            <button className="ghost" onClick={() => abortRef.current?.abort()}>Cancel</button>
          </div>
        </div>
      )}

      {state === 'review' && (
        <>
          <div className="panel">
            <div className="label">Transcript</div>
            <p className="transcript-box">{transcript}</p>
          </div>
          <div className="panel">
            <div className="review-head">
              <div>
                <div className="label">Review claims</div>
                <h2>Edit before fact-checking</h2>
              </div>
              <span className="pill">{selectedCount} selected</span>
            </div>
            <ClaimEditor claims={claims} setClaims={setClaims} />
            <div className="row">
              <button className="primary" disabled={selectedCount === 0} onClick={runReport}>Fact-check selected claims</button>
              <button className="ghost" onClick={reset}>Start over</button>
            </div>
          </div>
        </>
      )}

      {state === 'report' && report && (
        <>
          <ReportView report={report} />
          <div className="row" style={{ justifyContent: 'center' }}>
            <button className="ghost" onClick={reset}>Check another clip</button>
          </div>
        </>
      )}

      {state === 'error' && (
        <div className="panel">
          <div className="error">Something went wrong: {error}</div>
          <div className="row">
            <button className="ghost" onClick={reset}>Start over</button>
          </div>
        </div>
      )}

      <div className="footer-note">Evidence-checked claim report · sources shown per claim</div>
    </div>
  );
}
