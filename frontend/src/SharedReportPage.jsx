import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import Heatmap from "./Heatmap";

const API = "http://localhost:8000";

export default function SharedReportPage() {
  const { reportId } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API}/shared/${reportId}`)
      .then((r) => {
        if (!r.ok) throw new Error("Report not found or link has expired");
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [reportId]);

  if (loading) {
    return (
      <div className="veritas-container">
        <p className="status">Loading report...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="veritas-container">
        <div className="expired-notice">
          <h1>Veritas</h1>
          <p className="subtitle">Political Audio Fact-Checker</p>
          <p className="error">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { report, analysis } = data;
  const scoreColor = analysis.overall_score >= 50 ? "#c0392b" : "#27ae60";

  return (
    <div className="veritas-container results-page shared-page">
      <div className="shared-banner">Shared Report &mdash; Read Only</div>

      <h1>Veritas</h1>
      <p className="subtitle">Political Audio Fact-Check Report</p>

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
                  {seg.start_time.toFixed(1)}s &ndash;{" "}
                  {seg.end_time.toFixed(1)}s
                </td>
                <td
                  style={{
                    color:
                      seg.confidence_score >= 50 ? "#c0392b" : "#27ae60",
                    fontWeight: 700,
                  }}
                >
                  {seg.confidence_score.toFixed(1)}%
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
          <strong>Report ID:</strong> {report.report_id}
        </p>
        <p>
          <strong>Model:</strong> {analysis.model_used}
        </p>
        <p>
          <strong>Generated:</strong>{" "}
          {new Date(report.created_at).toLocaleString()}
        </p>
        <p>
          <strong>Link Expires:</strong>{" "}
          {new Date(report.expires_at).toLocaleDateString()}
        </p>
      </div>

      {/* download */}
      <div className="export-section">
        <a
          href={`${API}/reports/${report.report_id}/pdf`}
          className="submit-btn download-btn"
          target="_blank"
          rel="noopener noreferrer"
        >
          Download PDF
        </a>
      </div>
    </div>
  );
}
