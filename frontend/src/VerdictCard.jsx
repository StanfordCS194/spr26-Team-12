const TIER_META = {
  1: { label: 'Contradicted',     icon: '✗', klass: 't1' },
  2: { label: 'Weak evidence',    icon: '~', klass: 't2' },
  3: { label: 'Mixed evidence',   icon: '↔', klass: 't3' },
  4: { label: 'Moderate support', icon: '↑', klass: 't4' },
  5: { label: 'Strong support',   icon: '✓', klass: 't5' },
};

const STUDY_LABEL = {
  meta_analysis: 'Meta-analysis',
  rct: 'RCT',
  observational: 'Observational',
  review: 'Review',
  fact_sheet: 'Fact sheet',
  position_stand: 'Position stand',
  animal: 'Animal study',
  in_vitro: 'In vitro',
};

function TierBar({ tier }) {
  return (
    <>
      <div className="tier-segments">
        {[1, 2, 3, 4, 5].map((n) => (
          <div key={n} className={`seg ${n <= tier ? `on t${tier}` : ''}`} />
        ))}
      </div>
      <div className="tier-scale">
        <span>Contradicted</span>
        <span>Strong</span>
      </div>
    </>
  );
}

function Confidence({ level }) {
  return (
    <span className={`confidence ${level}`} title={`Confidence: ${level}`}>
      <span className="dots">
        <span className="dot d1" />
        <span className="dot d2" />
        <span className="dot d3" />
      </span>
      <span style={{ textTransform: 'capitalize' }}>{level} confidence</span>
    </span>
  );
}

function ExtractedBlock({ claim }) {
  return (
    <div className="extracted-block">
      <div className="label">Extracted claim</div>
      <div className="text">{claim}</div>
    </div>
  );
}

function SuggestionChips({ items, onPick }) {
  if (!items?.length) return null;
  return (
    <div className="example-chips" style={{ marginTop: 16 }}>
      <span className="chip-label">Try a showcase claim:</span>
      {items.map((s) => (
        <span key={s} className="chip" onClick={() => onPick?.(s)}>
          {s}
        </span>
      ))}
    </div>
  );
}

function StatusPanel({ icon, tone, title, children }) {
  return (
    <div className={`status-panel tone-${tone}`}>
      <div className="status-icon" aria-hidden>{icon}</div>
      <div className="status-body">
        <div className="status-title">{title}</div>
        <div className="status-text">{children}</div>
      </div>
    </div>
  );
}

function OkVerdict({ verdict }) {
  const meta = TIER_META[verdict.tier] || TIER_META[3];
  return (
    <>
      <ExtractedBlock claim={verdict.extracted_claim} />

      <div className="verdict-head">
        <span className={`tier-chip ${meta.klass}`}>
          <span className="icon">{meta.icon}</span>
          Tier {verdict.tier} · {meta.label}
        </span>
        <Confidence level={verdict.confidence} />
      </div>

      <TierBar tier={verdict.tier} />

      <div className="summary">{verdict.summary}</div>

      <div className="grid">
        <div className="cell">
          <div className="k">Effect size</div>
          <div className="v">{verdict.effect_size}</div>
        </div>
        <div className="cell">
          <div className="k">Typical dose</div>
          <div className="v">{verdict.dose}</div>
        </div>
        <div className="cell">
          <div className="k">Population</div>
          <div className="v">{verdict.population}</div>
        </div>
        <div className="cell">
          <div className="k">Confidence in tier</div>
          <div className="v" style={{ textTransform: 'capitalize' }}>
            {verdict.confidence}
          </div>
        </div>
      </div>

      <div className="why">{verdict.why}</div>

      <div className="evidence-h">Evidence ({verdict.evidence.length})</div>
      {verdict.evidence.map((e, i) => (
        <div key={i} className={`ev s-${e.study_type}`}>
          <div className="top">
            <div className="title">
              <a href={e.source_url} target="_blank" rel="noreferrer">
                {e.source_title}
              </a>
            </div>
            <span className="pill">{STUDY_LABEL[e.study_type] || e.study_type}</span>
          </div>
          <div className="meta">
            {e.year}
            {e.sample_size ? ` · n=${e.sample_size}` : ''}
            {e.population ? ` · ${e.population}` : ''}
          </div>
          <div className="note">{e.relevance_note}</div>
        </div>
      ))}

      <div className="footer-note">
        Generated in {(verdict.generation_time_ms / 1000).toFixed(1)}s · request {verdict.request_id.slice(0, 8)}
      </div>
    </>
  );
}

function OutOfScope({ verdict, onPickSuggestion }) {
  const isPrescription = verdict.scope_reason === 'prescription';
  return (
    <>
      <ExtractedBlock claim={verdict.extracted_claim} />
      {isPrescription ? (
        <StatusPanel
          icon="℞"
          tone="info"
          title="Prescription medication — outside our scope"
        >
          We only evaluate fitness supplements, vitamins, and over-the-counter
          sports-nutrition substances. Prescription drugs require a clinician
          and aren't part of the curated research corpus.
        </StatusPanel>
      ) : (
        <StatusPanel
          icon="◌"
          tone="info"
          title="Not a supplement claim"
        >
          Veritas fact-checks fitness supplements — vitamins, herbs,
          nootropics, amino acids, sports nutrition. This claim doesn't look
          like one. Try a supplement, dose, effect, or population.
        </StatusPanel>
      )}
      <SuggestionChips
        items={verdict.suggested_supplements}
        onPick={onPickSuggestion}
      />
    </>
  );
}

function NoEvidence({ verdict, onPickSuggestion }) {
  return (
    <>
      <ExtractedBlock claim={verdict.extracted_claim} />
      <StatusPanel
        icon="◐"
        tone="warn"
        title="Demo mode — limited cache"
      >
        Veritas covers every supplement when provider API keys are configured.
        You're on the demo build, which only ships pre-computed verdicts for a
        handful of showcase claims. Pick one below to see the full UX, or add
        provider keys to fact-check new claims.
      </StatusPanel>
      <SuggestionChips
        items={verdict.suggested_supplements}
        onPick={onPickSuggestion}
      />
    </>
  );
}

function SystemError({ verdict, onRetry }) {
  return (
    <>
      <ExtractedBlock claim={verdict.extracted_claim} />
      <StatusPanel icon="!" tone="error" title="Something broke on our side">
        {verdict.error_detail ||
          "The evidence check did not respond in time or returned an unparseable result."}
      </StatusPanel>
      {onRetry && (
        <div className="row" style={{ justifyContent: 'center', marginTop: 14 }}>
          <button className="primary" onClick={onRetry}>Retry</button>
        </div>
      )}
    </>
  );
}

export function VerdictCard({ verdict, onPickSuggestion, onRetry }) {
  const status = verdict.status || 'ok';
  return (
    <div className="panel">
      {status === 'ok' && <OkVerdict verdict={verdict} />}
      {status === 'out_of_scope' && (
        <OutOfScope verdict={verdict} onPickSuggestion={onPickSuggestion} />
      )}
      {status === 'no_evidence' && (
        <NoEvidence verdict={verdict} onPickSuggestion={onPickSuggestion} />
      )}
      {status === 'system_error' && (
        <SystemError verdict={verdict} onRetry={onRetry} />
      )}
    </div>
  );
}
