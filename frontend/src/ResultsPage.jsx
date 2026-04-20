import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";

const API = "http://localhost:8000";

function ScoreBadge({ score }) {
  const color = score >= 50 ? "#c0392b" : "#27ae60";
  return <span style={{ color, fontWeight: 700 }}>{score.toFixed(1)}%</span>;
}

// Decision matrix from FEATURE-4-PLAN.md §2. Combines Feature 2 (AI score)
// with Feature 4 (speaker similarity) so similarity is never displayed alone.
function decisionCell(aiScore, simScore) {
  const aiHigh = aiScore > 70, aiLow = aiScore < 30;
  const simHigh = simScore >= 75, simLow = simScore < 45;
  if (aiHigh && simHigh)
    return { tone: "danger", icon: "🚨", title: "Likely cloned voice of claimed speaker",
      body: "High AI-generation probability and high acoustic similarity to the reference voice. Consistent with a voice clone of the claimed speaker." };
  if (aiHigh && simLow)
    return { tone: "danger", icon: "🚨", title: "Synthetic, and not the claimed speaker",
      body: "High AI-generation probability and low similarity to the reference voice. The clip appears synthetic and does not match the claimed speaker." };
  if (aiHigh)
    return { tone: "danger", icon: "🚨", title: "Suspected clone",
      body: "High AI-generation probability with partial speaker similarity. Treat as suspected synthetic audio." };
  if (aiLow && simHigh)
    return { tone: "ok", icon: "✅", title: "Authentic, matches claimed speaker",
      body: "Low AI-generation probability and high similarity to the reference voice." };
  if (aiLow && simLow)
    return { tone: "warn", icon: "❓", title: "Authentic, but not the claimed speaker",
      body: "Low AI-generation probability but low similarity to the reference voice — the clip may be of a different speaker than claimed." };
  return { tone: "warn", icon: "⚠", title: "Inconclusive — re-check source",
    body: "AI-generation probability and speaker similarity are both in the uncertain band. Verify the source clip and try a longer recording if available." };
}

function VerdictMatrixBanner({ analysis }) {
  if (!analysis.speaker_match) return null;
  const cell = decisionCell(analysis.overall_score, analysis.speaker_match.similarity_score);
  const palette = {
    ok:     { bg: "#e8f5e9", border: "#27ae60", color: "#1e6b3a" },
    warn:   { bg: "#fff8e1", border: "#f1c40f", color: "#7a5a00" },
    danger: { bg: "#fdecea", border: "#c0392b", color: "#8b1a1a" },
  }[cell.tone];
  return (
    <div className="section" style={{
      background: palette.bg, border: `2px solid ${palette.border}`,
      borderRadius: 8, padding: "16px 18px",
    }}>
      <div style={{ fontSize: 13, color: palette.color, fontWeight: 700, letterSpacing: 0.5 }}>
        COMBINED VERDICT
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: palette.color, margin: "4px 0 8px" }}>
        {cell.icon} {cell.title}
      </div>
      <div style={{ color: "#333", lineHeight: 1.45 }}>{cell.body}</div>
      <div style={{ marginTop: 10, fontSize: 13, color: "#555" }}>
        AI probability <strong>{analysis.overall_score.toFixed(1)}%</strong>
        {" · "}
        Speaker similarity <strong>{analysis.speaker_match.similarity_score.toFixed(1)}%</strong>
        {" vs. "}<em>{analysis.speaker_match.claimed_speaker}</em>
      </div>
    </div>
  );
}

function Heatmap({ segments }) {
  return (
    <div className="heatmap">
      {segments.map((seg, i) => {
        const pct = seg.confidence_score / 100;
        const r = Math.round(39 + pct * (192 - 39));
        const g = Math.round(174 - pct * (174 - 57));
        const b = Math.round(96 - pct * (96 - 43));
        return (
          <div
            key={i}
            className="heatmap-segment"
            style={{ backgroundColor: `rgb(${r},${g},${b})`, flex: 1 }}
            title={`${seg.start_time.toFixed(1)}s–${seg.end_time.toFixed(1)}s: ${seg.confidence_score.toFixed(1)}%`}
          >
            <span className="seg-time">{seg.start_time.toFixed(0)}s</span>
            <span className="seg-score">{seg.confidence_score.toFixed(0)}%</span>
          </div>
        );
      })}
    </div>
  );
}

export default function ResultsPage() {
  const { analysisId } = useParams();
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [report, setReport] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetch(`${API}/analysis/${analysisId}`)
      .then((r) => {
        if (!r.ok) throw new Error("Analysis not found");
        return r.json();
      })
      .then(setAnalysis)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [analysisId]);

  async function handleExport() {
    setReportLoading(true);
    try {
      const res = await fetch(`${API}/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis_id: analysisId }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      setReport(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setReportLoading(false);
    }
  }

  function copyShareLink() {
    const url = `${window.location.origin}${report.share_url}`;
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return (
      <div className="veritas-container">
        <p className="status">Loading results...</p>
      </div>
    );
  }

  if (error && !analysis) {
    return (
      <div className="veritas-container">
        <p className="error">{error}</p>
        <Link to="/" className="back-link">&larr; Back</Link>
      </div>
    );
  }

  if (!analysis) return null;

  const scoreColor = analysis.overall_score >= 50 ? "#c0392b" : "#27ae60";

  return (
    <div className="veritas-container results-page">
      <Link to="/" className="back-link">&larr; New Analysis</Link>

      <h1>Veritas</h1>
      <p className="subtitle">Analysis Results</p>

      {/* verdict */}
      <div className="verdict-card">
        <div className="verdict-label">Verdict</div>
        <div className="verdict-text" style={{ color: scoreColor }}>
          {analysis.verdict}
        </div>
        <div className="verdict-score">
          <span className="score-big" style={{ color: scoreColor }}>
            {analysis.overall_score.toFixed(1)}%
          </span>
          <span className="score-label">AI Probability</span>
        </div>
        <div className="confidence-interval">
          Confidence: {analysis.confidence_low.toFixed(1)}% &ndash;{" "}
          {analysis.confidence_high.toFixed(1)}%
        </div>
      </div>

      {/* combined AI + speaker verdict (Feature 4 decision matrix) */}
      <VerdictMatrixBanner analysis={analysis} />

      {/* heatmap */}
      <div className="section">
        <h2>Confidence Heatmap</h2>
        <Heatmap segments={analysis.segments} />
      </div>

      {/* summary */}
      <div className="section">
        <h2>Summary</h2>
        <p className="summary-text">{analysis.summary}</p>
      </div>

      {/* segments table */}
      <div className="section">
        <h2>Segment Details</h2>
        <table className="segments-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Score</th>
              <th>Contributors</th>
            </tr>
          </thead>
          <tbody>
            {analysis.segments.map((seg, i) => (
              <tr key={i}>
                <td>
                  {seg.start_time.toFixed(1)}s &ndash; {seg.end_time.toFixed(1)}s
                </td>
                <td>
                  <ScoreBadge score={seg.confidence_score} />
                </td>
                <td>{seg.contributors.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* speaker match */}
      {analysis.speaker_match && (
        <div className="section">
          <h2>Speaker Identity Match</h2>
          <div className="speaker-match">
            <div>
              <strong>Claimed Speaker:</strong>{" "}
              {analysis.speaker_match.claimed_speaker}
            </div>
            <div>
              <strong>Similarity:</strong>{" "}
              {analysis.speaker_match.similarity_score.toFixed(1)}%
            </div>
            <div>
              <strong>Interpretation:</strong>{" "}
              {analysis.speaker_match.interpretation}
            </div>
          </div>
        </div>
      )}

      {/* meta */}
      <div className="section meta-info">
        <p>
          <strong>Model:</strong> {analysis.model_used}
        </p>
        <p>
          <strong>Analyzed:</strong>{" "}
          {new Date(analysis.analyzed_at).toLocaleString()}
        </p>
      </div>

      {/* export */}
      <div className="export-section">
        {error && <p className="error">{error}</p>}
        {!report ? (
          <button
            className="submit-btn"
            onClick={handleExport}
            disabled={reportLoading}
          >
            {reportLoading ? "Generating Report..." : "Export Report"}
          </button>
        ) : (
          <div className="report-actions">
            <a
              href={`${API}${report.pdf_url}`}
              className="submit-btn download-btn"
              target="_blank"
              rel="noopener noreferrer"
            >
              Download PDF
            </a>
            <button className="submit-btn share-btn" onClick={copyShareLink}>
              {copied ? "Link Copied!" : "Copy Share Link"}
            </button>
            <p className="expires-note">
              Share link expires{" "}
              {new Date(report.expires_at).toLocaleDateString()}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
