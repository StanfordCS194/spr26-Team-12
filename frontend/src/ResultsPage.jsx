import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";

const API = "http://localhost:8000";

function ScoreBadge({ score }) {
  const color = score >= 50 ? "#c0392b" : "#27ae60";
  return <span style={{ color, fontWeight: 700 }}>{score.toFixed(1)}%</span>;
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
              href={report.pdf_url}
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
