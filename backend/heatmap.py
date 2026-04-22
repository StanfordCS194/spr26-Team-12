import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

from models import SegmentAnalysis


def generate_heatmap_png(segments: list[SegmentAnalysis]) -> bytes:
    scores = [s.confidence_score for s in segments]
    starts = [s.start_time for s in segments]
    ends = [s.end_time for s in segments]

    fig, ax = plt.subplots(figsize=(10, 1.2))

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "veritas", ["#27ae60", "#f39c12", "#c0392b"]
    )
    norm = plt.Normalize(0, 100)

    for start, end, score in zip(starts, ends, scores):
        ax.barh(
            0, end - start, left=start, height=1,
            color=cmap(norm(score)), edgecolor="white", linewidth=0.5,
        )
        ax.text(
            (start + end) / 2, 0, f"{score:.0f}%",
            ha="center", va="center", fontsize=8, color="white", fontweight="bold",
        )

    ax.set_xlim(starts[0], ends[-1])
    ax.set_ylim(-0.5, 0.5)
    ax.set_xlabel("Time (s)", fontsize=9)
    ax.set_yticks([])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
