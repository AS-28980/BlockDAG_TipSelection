"""
Tangle DAG visualisation.

Renders the Tangle as a directed graph using pure matplotlib.
Colour-codes nodes by status (genesis, confirmed, tip, attached)
and sizes them by cumulative weight.

Works without networkx by using the Tangle's native data export.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

if TYPE_CHECKING:
    from src.core.tangle import Tangle

logger = logging.getLogger(__name__)


class TangleVisualizer:
    """Renders a Tangle DAG to an image file."""

    COLORS = {
        "genesis": "#4CAF50",
        "confirmed": "#5C6BC0",
        "tip": "#EF5350",
        "attached": "#78909C",
        "pending": "#BDBDBD",
    }

    def __init__(self, figsize: tuple[int, int] = (16, 10)) -> None:
        self.figsize = figsize

    def render(
        self,
        tangle: "Tangle",
        output_path: str | Path = "tangle.png",
        title: str = "Tangle DAG",
        show_weights: bool = True,
        highlight_tips: bool = True,
    ) -> Path:
        """Render the tangle to an image."""
        nodes_data = tangle.to_node_data()
        edges = tangle.to_edge_list()

        if not nodes_data:
            logger.warning("Empty tangle, nothing to render")
            return Path(output_path)

        fig, ax = plt.subplots(1, 1, figsize=self.figsize)
        ax.set_title(title, fontsize=14, fontweight="bold")

        # Build lookup
        node_map = {n["tx_id"]: n for n in nodes_data}
        pos = self._compute_layout(nodes_data, tangle.genesis_id)

        # Draw edges (arrows)
        for child_id, parent_id in edges:
            if child_id in pos and parent_id in pos:
                x0, y0 = pos[child_id]
                x1, y1 = pos[parent_id]
                ax.annotate(
                    "", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(
                        arrowstyle="->",
                        color="#90A4AE",
                        lw=1.0,
                        alpha=0.5,
                        connectionstyle="arc3,rad=0.05",
                    ),
                )

        # Draw nodes
        for ndata in nodes_data:
            nid = ndata["tx_id"]
            if nid not in pos:
                continue
            x, y = pos[nid]

            if nid == tangle.genesis_id:
                color = self.COLORS["genesis"]
            elif ndata["is_tip"]:
                color = self.COLORS["tip"]
            elif ndata["status"] == "CONFIRMED":
                color = self.COLORS["confirmed"]
            elif ndata["status"] == "PENDING_POW":
                color = self.COLORS["pending"]
            else:
                color = self.COLORS["attached"]

            max_cw = max((n["cw"] for n in nodes_data), default=1)
            size = 200 + 600 * (ndata["cw"] / max_cw) if show_weights else 300

            ax.scatter(x, y, s=size, c=color, alpha=0.9, edgecolors="#37474F", linewidths=1.0, zorder=5)
            ax.text(x, y, ndata["label"], ha="center", va="center", fontsize=5, color="white", fontweight="bold", zorder=6)

        # Legend
        legend_elements = [
            mpatches.Patch(color=self.COLORS["genesis"], label="Genesis"),
            mpatches.Patch(color=self.COLORS["confirmed"], label="Confirmed"),
            mpatches.Patch(color=self.COLORS["attached"], label="Attached"),
            mpatches.Patch(color=self.COLORS["tip"], label="Tip"),
        ]
        ax.legend(handles=legend_elements, loc="upper left", fontsize=9)

        ax.set_xlabel("Time →", fontsize=10)
        ax.set_facecolor("#FAFAFA")
        fig.patch.set_facecolor("#FAFAFA")
        ax.axis("off")
        plt.tight_layout()

        out = Path(output_path)
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Tangle visualisation saved to %s", out)
        return out

    def _compute_layout(self, nodes_data: list[dict], genesis_id: str) -> dict:
        """x = timestamp (time axis), y = spread to avoid overlap."""
        pos = {}
        timestamps = {n["tx_id"]: n["timestamp"] for n in nodes_data}

        if not timestamps:
            return pos

        min_ts = min(timestamps.values())
        max_ts = max(timestamps.values())
        ts_range = max_ts - min_ts if max_ts > min_ts else 1.0

        buckets: dict[int, list[str]] = defaultdict(list)
        n_buckets = max(10, len(nodes_data) // 3)
        for nid, ts in timestamps.items():
            bucket = int((ts - min_ts) / ts_range * n_buckets)
            buckets[bucket].append(nid)

        for bucket, nids in buckets.items():
            x = bucket / n_buckets * 10
            n = len(nids)
            for i, nid in enumerate(nids):
                y = (i - n / 2) * 0.8
                pos[nid] = (x, y)

        return pos

    def render_comparison(
        self,
        tangles: dict[str, "Tangle"],
        output_path: str | Path = "tangle_comparison.png",
    ) -> Path:
        """Render multiple node tangles side by side for comparison."""
        n = len(tangles)
        fig, axes = plt.subplots(1, n, figsize=(self.figsize[0], self.figsize[1] // 2 + 2))
        if n == 1:
            axes = [axes]

        for ax, (name, tangle) in zip(axes, tangles.items()):
            nodes_data = tangle.to_node_data()
            edges = tangle.to_edge_list()
            pos = self._compute_layout(nodes_data, tangle.genesis_id)

            for child_id, parent_id in edges:
                if child_id in pos and parent_id in pos:
                    x0, y0 = pos[child_id]
                    x1, y1 = pos[parent_id]
                    ax.annotate(
                        "", xy=(x1, y1), xytext=(x0, y0),
                        arrowprops=dict(arrowstyle="->", color="#B0BEC5", lw=0.7, alpha=0.4),
                    )

            for ndata in nodes_data:
                nid = ndata["tx_id"]
                if nid not in pos:
                    continue
                x, y = pos[nid]
                if nid == tangle.genesis_id:
                    color = self.COLORS["genesis"]
                elif ndata["is_tip"]:
                    color = self.COLORS["tip"]
                else:
                    color = self.COLORS["attached"]
                ax.scatter(x, y, s=80, c=color, alpha=0.85, edgecolors="gray", linewidths=0.5, zorder=5)

            tip_count = sum(1 for n in nodes_data if n["is_tip"])
            ax.set_title(f"{name} (size={len(nodes_data)}, tips={tip_count})", fontsize=9)
            ax.axis("off")

        plt.tight_layout()
        out = Path(output_path)
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return out
