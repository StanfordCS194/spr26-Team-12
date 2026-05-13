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

/** Vercel/Render often return HTML or plain text on 5xx; avoid response.json() on errors. */
async function readApiError(response) {
  const text = await response.text();
  try {
    const j = JSON.parse(text);
    if (j && typeof j === 'object' && j.detail != null) return String(j.detail);
    if (j && typeof j === 'object' && j.message != null) return String(j.message);
  } catch {
    /* not JSON */
  }
  const trimmed = text.trim();
  if (trimmed) return trimmed.slice(0, 400);
  return `Request failed (HTTP ${response.status})`;
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

function RosterToggle({ onClick, active }) {
  return (
    <button
      className={`icon-btn ${active ? 'is-active' : ''}`}
      onClick={onClick}
      title={active ? 'Back to fact-checker' : 'View credibility leaderboard'}
      aria-label={active ? 'Back to fact-checker' : 'View credibility leaderboard'}
    >
      {active ? '←' : 'R'}
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

/* ============================================================
   Feature 2 — Credibility leaderboard
   ============================================================ */
const VERDICT_BUCKETS = [
  { key: 'true', label: 'True', cls: 'true' },
  { key: 'mostly_true', label: 'Mostly true', cls: 'mostly_true' },
  { key: 'mixed', label: 'Mixed', cls: 'mixed' },
  { key: 'weak', label: 'Weak', cls: 'weak' },
  { key: 'false', label: 'False', cls: 'false' },
  { key: 'unverified', label: 'Unverified', cls: 'unverified' },
];

function GradeBadge({ grade, score, size = 'sm' }) {
  const display = score == null ? '—' : `${score}%`;
  return (
    <div className={`grade-badge grade-${grade.toLowerCase().replace('/', '')} grade-${size}`}>
      <div className="grade-letter">{grade}</div>
      <div className="grade-score">{display}</div>
    </div>
  );
}

function RosterListView({ items, loading, onSelect, onSeed, error, minVerified, setMinVerified }) {
  return (
    <div className="panel">
      <div className="review-head">
        <div>
          <div className="label">Credibility leaderboard</div>
          <h2>Influencers ranked by claim accuracy</h2>
        </div>
        <span className="pill">{items.length} tracked</span>
      </div>

      <div className="row" style={{ marginTop: 4 }}>
        <label className="muted-note" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          Min verified claims:
          <input
            type="number"
            min="0"
            value={minVerified}
            onChange={(e) => setMinVerified(Math.max(0, Number(e.target.value) || 0))}
            style={{ width: 64, padding: '4px 8px' }}
          />
        </label>
        <span className="pill">supports +1 · partial +0.5 · mixed 0 · weak −0.5 · contradicts −1</span>
      </div>

      {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}
      {loading && !items.length && <p className="muted-note" style={{ marginTop: 16 }}>Loading…</p>}

      {!loading && !items.length && (
        <div style={{ marginTop: 18 }}>
          <p className="muted-note">
            No influencers tracked yet. Run a clip-report with a creator name and Veritas
            will start building their credibility profile.
          </p>
          <div className="row">
            <button className="primary" onClick={onSeed}>Load demo influencers</button>
          </div>
        </div>
      )}

      <ul className="roster-list">
        {items.map((profile, idx) => {
          const c = profile.credibility;
          return (
            <li key={profile.slug}>
              <button className="roster-row" onClick={() => onSelect(profile.slug)}>
                <span className="rank">#{idx + 1}</span>
                <div className="roster-name">
                  <strong>{profile.name}</strong>
                  <span className="muted-note">
                    {c.verified_claims} verified · {c.total_claims} total
                    {c.needs_review_claims > 0 && ` · ${c.needs_review_claims} need review`}
                  </span>
                </div>
                <GradeBadge grade={c.grade} score={c.score} />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RosterDetailView({ detail, onBack, onDelete }) {
  const c = detail.credibility;
  const buckets = c.buckets || {};
  return (
    <>
      <div className="panel">
        <button className="ghost" onClick={onBack} style={{ marginBottom: 14 }}>← Back to leaderboard</button>
        <div className="profile-head">
          <div>
            <div className="label">Influencer profile</div>
            <h2 style={{ margin: '2px 0 6px' }}>{detail.name}</h2>
            <p className="muted-note" style={{ margin: 0 }}>
              First tracked {detail.first_seen ? new Date(detail.first_seen).toLocaleDateString() : '—'}
              {c.last_checked_at && ` · last clip ${new Date(c.last_checked_at).toLocaleDateString()}`}
            </p>
          </div>
          <GradeBadge grade={c.grade} score={c.score} size="lg" />
        </div>

        <div className="bucket-grid">
          {VERDICT_BUCKETS.map((b) => (
            <div key={b.key} className={`bucket bucket-${b.cls}`}>
              <div className="bucket-num">{buckets[b.key] || 0}</div>
              <div className="bucket-label">{b.label}</div>
            </div>
          ))}
        </div>
        <p className="muted-note" style={{ textAlign: 'center', marginTop: 4 }}>
          Score = (Σ weights + verified) / (2 × verified) × 100, with insufficient claims excluded.
        </p>
      </div>

      <div className="panel">
        <div className="evidence-h" style={{ marginTop: 0 }}>Claim history ({detail.claim_records.length})</div>
        {detail.claim_records.length === 0 && (
          <p className="muted-note">No claims have been logged for this influencer yet.</p>
        )}
        {detail.claim_records.map((rec) => (
          <div className="claim-history-row" key={`${rec.report_id}-${rec.claim_id}-${rec.checked_at}`}>
            <span className={`direction dir-${rec.final_direction}`}>
              {directionLabel(rec.final_direction)}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="claim-history-text">{rec.claim_text}</div>
              <div className="muted-note">
                {rec.category.replaceAll('_', ' ')} · {rec.risk_level} risk · confidence {rec.confidence}
                {rec.source_domain && ` · ${rec.source_domain}`}
                {rec.checked_at && ` · ${new Date(rec.checked_at).toLocaleDateString()}`}
                {rec.needs_review && ' · needs review'}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ justifyContent: 'space-between' }}>
        <button className="ghost" onClick={onBack}>← Back to leaderboard</button>
        <button className="ghost" onClick={onDelete}>Remove influencer</button>
      </div>
    </>
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

// --- Feature 2: Influencer credibility -----------------------------------
function ScoreRing({ score }) {
  const tier =
    score >= 85 ? 'high' : score >= 70 ? 'mid' : score >= 50 ? 'low' : 'bad';
  return <div className={`score-ring score-${tier}`}>{score}</div>;
}

function directionDot(direction) {
  const map = {
    supports: '✓',
    partially_supports: '~',
    mixed: '·',
    weak: '·',
    contradicts: '✗',
    insufficient: '?',
  };
  return map[direction] || '·';
}

function InfluencersView() {
  const [list, setList] = useState(null);
  const [active, setActive] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/influencers')
      .then((r) => r.json())
      .then((d) => setList(d.influencers || []))
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="panel"><div className="error">{error}</div></div>;
  if (!list) return <div className="panel">Loading influencers…</div>;

  if (active) {
    return <InfluencerDetail slug={active} onBack={() => setActive(null)} />;
  }

  return (
    <div className="panel">
      <div className="review-head">
        <div>
          <div className="label">Feature 2</div>
          <h2>Influencer credibility</h2>
        </div>
        <span className="pill">{list.length} tracked</span>
      </div>
      <p className="muted">
        Scores aggregate every Veritas fact-check attributed to that creator.
        High score ≠ every product they push is good (see Products).
      </p>
      <div className="influencer-grid">
        {list.map((inf) => (
          <button key={inf.slug} className="influencer-card" onClick={() => setActive(inf.slug)}>
            <div className="influencer-head">
              <div
                className="avatar"
                style={{ background: inf.avatar_color }}
                aria-hidden
              >
                {inf.name?.charAt(0) || '?'}
              </div>
              <ScoreRing score={inf.credibility_score} />
            </div>
            <div className="influencer-body">
              <div className="influencer-name">{inf.name}</div>
              <div className="influencer-handle">{inf.handle}</div>
              <div className="influencer-meta">
                {inf.followers && <span>{inf.followers}</span>}
                <span>{inf.claims_checked} claims checked</span>
              </div>
              <div className="topic-row">
                {(inf.topics || []).slice(0, 3).map((t) => (
                  <span key={t} className="topic-pill">{t}</span>
                ))}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function InfluencerDetail({ slug, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    fetch(`/api/influencers/${slug}`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [slug]);
  if (error) return <div className="panel"><div className="error">{error}</div></div>;
  if (!data) return <div className="panel">Loading…</div>;
  return (
    <>
      <div className="panel">
        <button className="ghost" onClick={onBack}>← All influencers</button>
        <div className="detail-head">
          <div className="avatar lg" style={{ background: data.avatar_color }}>
            {data.name?.charAt(0)}
          </div>
          <div className="detail-meta">
            <h2>{data.name}</h2>
            <div className="muted">{data.handle} · {(data.platforms || []).join(', ')} · {data.followers}</div>
            <p>{data.bio}</p>
            <div className="topic-row">
              {(data.topics || []).map((t) => <span key={t} className="topic-pill">{t}</span>)}
            </div>
          </div>
          <ScoreRing score={data.credibility_score} />
        </div>
        <div className="breakdown-row">
          {Object.entries(data.direction_breakdown || {}).map(([dir, n]) => (
            <span key={dir} className={`direction dir-${dir}`}>{directionLabel(dir)}: {n}</span>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="label">Recent claims fact-checked</div>
        <ul className="claim-history">
          {data.recent_claims.map((e, i) => (
            <li key={i}>
              <span className={`direction dir-${e.direction}`}>{directionDot(e.direction)} {directionLabel(e.direction)}</span>
              <div className="claim-text">{e.claim}</div>
              {e.source_clip && <div className="muted">from "{e.source_clip}"</div>}
            </li>
          ))}
        </ul>
      </div>

      {data.promoted_products?.length > 0 && (
        <div className="panel">
          <div className="label">Products in the same supplement categories</div>
          <p className="muted">
            Reminder: a credible influencer can still promote a weak product. Open each one in Products to see its independent score.
          </p>
          <div className="product-grid">
            {data.promoted_products.map((p) => (
              <a key={p.id} className="product-card" href={p.url} target="_blank" rel="noreferrer">
                <div
                  className="product-thumb"
                  data-initials={(p.brand || '?').slice(0, 2).toUpperCase()}
                >
                  {p.image_url && (
                    <img
                      src={p.image_url}
                      alt={p.product_name}
                      referrerPolicy="no-referrer"
                      onError={(e) => { e.currentTarget.style.display = 'none'; }}
                    />
                  )}
                </div>
                <div className="product-body">
                  <div className="product-brand">{p.brand}</div>
                  <div className="product-name">{p.product_name}</div>
                  <div className="product-cert muted">{p.supplement}</div>
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

// --- Feature 3: Product credibility ---------------------------------------
function ProductsView() {
  const [list, setList] = useState(null);
  const [active, setActive] = useState(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');

  useEffect(() => {
    fetch('/api/products')
      .then((r) => r.json())
      .then((d) => setList(d.products || []))
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="panel"><div className="error">{error}</div></div>;
  if (!list) return <div className="panel">Loading products…</div>;
  if (active) return <ProductDetail productId={active} onBack={() => setActive(null)} />;

  const filtered = list.filter((p) => {
    const q = filter.toLowerCase();
    return !q || p.brand.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q) || p.supplement.toLowerCase().includes(q);
  });

  return (
    <div className="panel">
      <div className="review-head">
        <div>
          <div className="label">Feature 3</div>
          <h2>Product credibility</h2>
        </div>
        <span className="pill">{list.length} products</span>
      </div>
      <p className="muted">
        Each score blends evidence (50%), third-party certification quality (30%),
        and average credibility of influencers who endorsed it (20%).
        A weakly-supported supplement can still rank low even if a famous person promotes it.
      </p>
      <input
        className="filter-input"
        type="text"
        placeholder="Filter by brand, product, or supplement…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="product-cred-grid">
        {filtered.map((p) => (
          <button key={p.id} className="product-cred-card" onClick={() => setActive(p.id)}>
            <div className="pcred-head">
              <div
                className="product-thumb sm"
                data-initials={(p.brand || '?').slice(0, 2).toUpperCase()}
              >
                {p.image_url && (
                  <img
                    src={p.image_url}
                    alt={p.product_name}
                    referrerPolicy="no-referrer"
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                )}
              </div>
              <ScoreRing score={p.credibility_score} />
            </div>
            <div className="product-body">
              <div className="product-brand">{p.brand}</div>
              <div className="product-name">{p.product_name}</div>
              <div className="product-cert">{p.supplement} · {p.certification || 'no cert'}</div>
              <div className="dim-row">
                <span>Evidence {p.evidence_score}</span>
                <span>Quality {p.quality_score}</span>
                <span>Endorse {p.endorsement_score}</span>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function ProductDetail({ productId, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    fetch(`/api/products/${productId}`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [productId]);
  if (error) return <div className="panel"><div className="error">{error}</div></div>;
  if (!data) return <div className="panel">Loading…</div>;
  return (
    <>
      <div className="panel">
        <button className="ghost" onClick={onBack}>← All products</button>
        <div className="detail-head">
          <div
            className="product-thumb md"
            data-initials={(data.brand || '?').slice(0, 2).toUpperCase()}
          >
            {data.image_url && (
              <img
                src={data.image_url}
                alt={data.product_name}
                referrerPolicy="no-referrer"
                onError={(e) => { e.currentTarget.style.display = 'none'; }}
              />
            )}
          </div>
          <div className="detail-meta">
            <h2>{data.brand} — {data.product_name}</h2>
            <div className="muted">{data.supplement} · {data.form} · {data.price_band}</div>
            <p>{data.note}</p>
            <div className="topic-row">
              {data.certification && <span className="topic-pill">{data.certification}</span>}
              {data.url && <a className="topic-pill link" href={data.url} target="_blank" rel="noreferrer">Open product page ↗</a>}
            </div>
          </div>
          <ScoreRing score={data.credibility_score} />
        </div>

        <div className="dim-row big">
          <div><div className="dim-label">Evidence</div><div className="dim-val">{data.evidence_score}</div></div>
          <div><div className="dim-label">Quality</div><div className="dim-val">{data.quality_score}</div></div>
          <div><div className="dim-label">Endorsements</div><div className="dim-val">{data.endorsement_score}</div></div>
        </div>
        <div className="breakdown-row">
          {Object.entries(data.evidence_breakdown || {}).map(([dir, n]) => (
            <span key={dir} className={`direction dir-${dir}`}>{directionLabel(dir)}: {n}</span>
          ))}
        </div>
      </div>

      {data.evidence_claims?.length > 0 && (
        <div className="panel">
          <div className="label">What influencers have claimed about {data.supplement}</div>
          <ul className="claim-history">
            {data.evidence_claims.map((e, i) => (
              <li key={i}>
                <span className={`direction dir-${e.direction}`}>{directionDot(e.direction)} {directionLabel(e.direction)}</span>
                <div className="claim-text">{e.claim}</div>
                {e.influencer_slug && <div className="muted">— {e.influencer_slug}{e.source_clip ? ` · "${e.source_clip}"` : ''}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.promoted_by?.length > 0 && (
        <div className="panel">
          <div className="label">Promoted by</div>
          <p className="muted">
            Cross-check: a high-cred influencer can still recommend a low-evidence supplement (and vice versa).
          </p>
          <div className="influencer-grid sm">
            {data.promoted_by.map((p) => (
              <div key={p.slug} className="influencer-card">
                <div className="influencer-head">
                  <div className="avatar" style={{ background: p.avatar_color }}>{p.name?.charAt(0)}</div>
                  <ScoreRing score={p.credibility_score} />
                </div>
                <div className="influencer-body">
                  <div className="influencer-name">{p.name}</div>
                  <div className="influencer-handle">{p.handle}</div>
                  <div className="muted">{p.calls.length} call(s) on this supplement</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export default function App() {
  const [theme, setTheme] = useTheme();
  const [view, setView] = useState('factcheck'); // 'factcheck' | 'influencers' | 'products'
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

  // Feature 2: state for the (now-unused) original roster leaderboard.
  // The top-nav added by Features 2+3 uses 'view' declared above with values
  // 'factcheck' | 'influencers' | 'products' instead.
  const [roster, setRoster] = useState([]);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterError, setRosterError] = useState('');
  const [rosterMin, setRosterMin] = useState(0);
  const [activeProfile, setActiveProfile] = useState(null);

  const abortRef = useRef(null);

  async function loadRoster() {
    setRosterLoading(true);
    setRosterError('');
    try {
      const response = await fetch(`/api/influencers?min_verified=${rosterMin}`);
      if (!response.ok) throw new Error(await readApiError(response));
      setRoster(await response.json());
    } catch (err) {
      setRosterError(err.message || String(err));
    } finally {
      setRosterLoading(false);
    }
  }

  useEffect(() => {
    if (view === 'roster') loadRoster();
  }, [view, rosterMin]);

  // Pick up text handed off from the Chrome extension's "Open full app" button.
  // The extension forwards ?text=...&creator=...&source=... (and optionally
  // &autorun=1 to immediately kick off the extract pipeline) so the user lands
  // on the web app with the same transcript already loaded.
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const incomingText = params.get('text');
      if (incomingText) {
        setText(incomingText.slice(0, 12000));
        setTab('text');
      }
      const incomingCreator = params.get('creator');
      if (incomingCreator) setCreatorName(incomingCreator.slice(0, 120));
      // Strip the params so refresh doesn't re-fill, but keep the path/hash.
      if (incomingText || incomingCreator || params.get('source') || params.get('autorun')) {
        const cleanUrl = window.location.pathname + window.location.hash;
        window.history.replaceState({}, '', cleanUrl);
      }
    } catch {}
  }, []);

  async function openProfile(slug) {
    setRosterError('');
    try {
      const response = await fetch(`/api/influencers/${slug}`);
      if (!response.ok) throw new Error(await readApiError(response));
      setActiveProfile(await response.json());
      setView('roster-detail');
    } catch (err) {
      setRosterError(err.message || String(err));
    }
  }

  async function seedRoster() {
    try {
      await fetch('/api/influencers/seed', { method: 'POST' });
      loadRoster();
    } catch (err) {
      setRosterError(err.message || String(err));
    }
  }

  async function deleteActiveProfile() {
    if (!activeProfile) return;
    if (!confirm(`Remove ${activeProfile.name} from the leaderboard?`)) return;
    try {
      const response = await fetch(`/api/influencers/${activeProfile.slug}`, { method: 'DELETE' });
      if (!response.ok && response.status !== 204) {
        throw new Error(await readApiError(response));
      }
      setActiveProfile(null);
      setView('roster');
    } catch (err) {
      setRosterError(err.message || String(err));
    }
  }

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
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()).text;
    }
    if (tab === 'link') {
      const response = await fetch('/api/process/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
        signal: abortRef.current.signal,
      });
      if (!response.ok) throw new Error(await readApiError(response));
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
      if (!response.ok) throw new Error(await readApiError(response));
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
      if (!response.ok) throw new Error(await readApiError(response));
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
      if (!response.ok) throw new Error(await readApiError(response));
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
      if (!response.ok) throw new Error(await readApiError(response));
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

      <nav className="topnav">
        {[
          { id: 'factcheck', label: 'Fact Check' },
          { id: 'influencers', label: 'Influencers' },
          { id: 'products', label: 'Products' },
        ].map((v) => (
          <button
            key={v.id}
            className={`topnav-btn ${view === v.id ? 'active' : ''}`}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </nav>

      {view === 'influencers' && <InfluencersView />}
      {view === 'products' && <ProductsView />}

      {view === 'factcheck' && state === 'idle' && (
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

          {tab === 'link' ? (
            <>
              <input
                type="url"
                placeholder="Paste video or article URL (YouTube, TikTok, …)"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <div className="row">
                <button className="primary" disabled={!canSubmit} onClick={prepareClaims}>Extract claims</button>
                {platform && <span className="pill">platform: {platform}</span>}
              </div>
              <div className="profile-row">
                <input
                  type="text"
                  placeholder="@handle (optional, not the URL above)"
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
            </>
          ) : (
            <>
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
            </>
          )}
        </div>
      )}

      {view === 'factcheck' && (state === 'processing' || state === 'checking') && (
        <div className="panel">
          <ProgressList stage={state} />
          <div className="row">
            <button className="ghost" onClick={() => abortRef.current?.abort()}>Cancel</button>
          </div>
        </div>
      )}

      {view === 'factcheck' && state === 'review' && (
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

      {view === 'factcheck' && state === 'report' && report && (
        <>
          <ReportView report={report} />
          <div className="row" style={{ justifyContent: 'center', gap: 12 }}>
            <button className="ghost" onClick={reset}>Check another clip</button>
            {report.creator_name && (
              <button className="ghost" onClick={() => openProfile(report.creator_name.toLowerCase().replace(/^@+/, '').replace(/[^\w\s-]/g, '').replace(/[\s_]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown')}>
                View {report.creator_name}'s credibility →
              </button>
            )}
          </div>
        </>
      )}

      {view === 'factcheck' && state === 'error' && (
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
