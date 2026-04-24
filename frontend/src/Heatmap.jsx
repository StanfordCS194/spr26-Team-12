import { useState } from "react";

/**
 * 3-stop colour ramp: green (authentic) → yellow (uncertain) → red (AI-generated).
 * pct is in [0, 1] where 1 = 100% AI probability.
 */
export function segColor(pct) {
  if (pct <= 0.5) {
    const t = pct * 2;
    return [
      Math.round(39  + t * (230 - 39)),
      Math.round(174 + t * (190 - 174)),
      Math.round(96  + t * (0   - 96)),
    ];
  }
  const t = (pct - 0.5) * 2;
  return [
    Math.round(230 + t * (192 - 230)),
    Math.round(190 + t * (57  - 190)),
    Math.round(0   + t * (43  - 0)),
  ];
}

/**
 * Interactive confidence heatmap.
 * Hovering a segment shows exact probability + top-3 contributors (Feature 3.1).
 */
export default function Heatmap({ segments }) {
  const [tooltip, setTooltip] = useState(null);

  return (
    <div className="heatmap-wrapper">
      <div className="heatmap">
        {segments.map((seg, i) => {
          const [r, g, b] = segColor(seg.confidence_score / 100);
          return (
            <div
              key={i}
              className="heatmap-segment"
              style={{ backgroundColor: `rgb(${r},${g},${b})`, flex: 1 }}
              onMouseEnter={(e) =>
                setTooltip({ seg, x: e.clientX, y: e.clientY })
              }
              onMouseMove={(e) =>
                setTooltip((prev) =>
                  prev ? { ...prev, x: e.clientX, y: e.clientY } : null
                )
              }
              onMouseLeave={() => setTooltip(null)}
            >
              <span className="seg-time">{seg.start_time.toFixed(0)}s</span>
              <span className="seg-score">{seg.confidence_score.toFixed(0)}%</span>
            </div>
          );
        })}
      </div>

      {tooltip && (
        <div
          className="heatmap-tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="tooltip-time-range">
            {tooltip.seg.start_time.toFixed(1)}s &ndash; {tooltip.seg.end_time.toFixed(1)}s
          </div>
          <div className="tooltip-probability">
            AI probability:{" "}
            <strong>{tooltip.seg.confidence_score.toFixed(1)}%</strong>
          </div>
          {tooltip.seg.contributors?.length > 0 && (
            <div className="tooltip-contributors">
              <div className="tooltip-contrib-label">Top contributors:</div>
              {tooltip.seg.contributors.map((c, j) => (
                <div key={j} className="tooltip-contributor">&middot; {c}</div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="heatmap-legend">
        <span style={{ color: "#27ae60" }}>&#9679; Likely Authentic</span>
        <span style={{ color: "#d4ac0d" }}>&#9679; Uncertain</span>
        <span style={{ color: "#c0392b" }}>&#9679; Likely AI-Generated</span>
      </div>
    </div>
  );
}
