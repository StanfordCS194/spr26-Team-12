import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";

const API = "http://localhost:8000";

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

  const fc = analysis.fact_check;
  const scoreColor = fc && fc.consistency_score >= 60 ? "#27ae60" : "#c0392b";

  return (
    <div className="veritas-container results-page">
      <Link to="/" className="back-link">&larr; New Analysis</Link>

      <h1>Veritas</h1>
      <p className="subtitle">Political Audio Fact-Checker</p>

      {/* verdict */}
      {fc && (
        <div className="verdict-card">
          <div className="verdict-label">Verdict</div>
          <div className="verdict-text" style={{ color: scoreColor }}>
            {analysis.verdict}
          </div>
          <div className="verdict-score">
            <span className="score-big" style={{ color: scoreColor }}>
              {fc.consistency_score.toFixed(0)}%
            </span>
            <span className="score-label">Factual Consistency</span>
          </div>
        </div>
      )}

      {/* fact check claims */}
      {fc && (
        <div className="section">
          <h2>Fact-Check Results</h2>
          <p className="summary-text">{fc.summary}</p>

          {fc.claims.length > 0 && (
            <div className="claims-list">
              {fc.claims.map((claim, i) => (
                <div key={i} className={`claim-card claim-${claim.verdict.toLowerCase()}`}>
                  <div className="claim-header">
                    <span className="claim-verdict">{claim.verdict}</span>
                    <span className="claim-text">"{claim.claim}"</span>
                  </div>
                  <p className="claim-explanation">{claim.explanation}</p>
                  {claim.sources.length > 0 && (
                    <p className="claim-sources">
                      <strong>Sources:</strong> {claim.sources.join(", ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          <details className="transcript-toggle">
            <summary>View Full Transcript</summary>
            <p className="transcript-text">{fc.transcript}</p>
          </details>
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
