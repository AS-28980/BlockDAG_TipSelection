"""
Metrics dashboard — generates multi-panel plots of simulation results.

Recreates the key figures from the papers:
    - L(t) over time (Ferraro et al. Figs 7, 8, 9)
    - Cumulative weight distribution
    - Per-node tangle size comparison
    - Propagation latency histogram
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from src.network.node import TangleNode
    from src.simulation.metrics import SimulationMetrics

logger = logging.getLogger(__name__)


class MetricsDashboard:
    """Generates a multi-panel metrics dashboard image."""

    def __init__(self, figsize: tuple[int, int] = (18, 14)) -> None:
        self.figsize = figsize

    def render(
        self,
        nodes: list["TangleNode"],
        metrics: "SimulationMetrics",
        output_path: str | Path = "dashboard.png",
        title: str = "Tangle Simulation Dashboard",
    ) -> Path:
        """Generate the full dashboard."""
        fig, axes = plt.subplots(2, 3, figsize=self.figsize)
        fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

        self._plot_tip_count(axes[0, 0], nodes)
        self._plot_tangle_sizes(axes[0, 1], metrics)
        self._plot_latency_histogram(axes[0, 2], nodes)
        self._plot_cumulative_weights(axes[1, 0], nodes)
        self._plot_tx_throughput(axes[1, 1], nodes)
        self._plot_convergence(axes[1, 2], nodes)

        plt.tight_layout(rect=[0, 0, 1, 0.95])
        out = Path(output_path)
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Dashboard saved to %s", out)
        return out

    def _plot_tip_count(self, ax, nodes: list["TangleNode"]) -> None:
        """
        L(t): number of tips over time.
        This is the central figure from Ferraro et al. (Figs 7-9).
        """
        ax.set_title("L(t): Tip Count Over Time", fontsize=11, fontweight="bold")
        for node in nodes:
            if node.metrics["tip_counts"]:
                times, counts = zip(*node.metrics["tip_counts"])
                ax.plot(times, counts, alpha=0.7, linewidth=1.2, label=node.node_id)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Number of Tips L(t)")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    def _plot_tangle_sizes(self, ax, metrics: "SimulationMetrics") -> None:
        """Bar chart of final tangle size per node."""
        ax.set_title("Final Tangle Size per Node", fontsize=11, fontweight="bold")
        names = sorted(metrics.tangle_sizes.keys())
        sizes = [metrics.tangle_sizes[n] for n in names]
        short_names = [n.replace("node_", "N") for n in names]
        bars = ax.bar(short_names, sizes, color="#5C6BC0", alpha=0.8)
        ax.set_ylabel("Transactions")
        ax.grid(True, alpha=0.3, axis="y")

    def _plot_latency_histogram(self, ax, nodes: list["TangleNode"]) -> None:
        """Distribution of message propagation latencies."""
        ax.set_title("Propagation Latency Distribution", fontsize=11, fontweight="bold")
        all_lat = []
        for node in nodes:
            all_lat.extend([lat for _, lat in node.metrics["latencies"]])
        if all_lat:
            ax.hist(all_lat, bins=40, color="#26A69A", alpha=0.8, edgecolor="white")
            ax.axvline(np.mean(all_lat), color="red", linestyle="--", label=f"Mean: {np.mean(all_lat):.0f}ms")
            ax.legend(fontsize=8)
        ax.set_xlabel("Latency (ms)")
        ax.set_ylabel("Count")
        ax.grid(True, alpha=0.3)

    def _plot_cumulative_weights(self, ax, nodes: list["TangleNode"]) -> None:
        """Distribution of cumulative weights across one node's tangle."""
        ax.set_title("Cumulative Weight Distribution", fontsize=11, fontweight="bold")
        if nodes:
            node = nodes[0]  # use first node
            weights = [
                tx.cumulative_weight
                for tx in node.tangle.get_all_txs().values()
            ]
            if weights:
                ax.hist(weights, bins=30, color="#FFA726", alpha=0.8, edgecolor="white")
                ax.set_xlabel(f"Cumulative Weight ({node.node_id})")
                ax.set_ylabel("Count")
        ax.grid(True, alpha=0.3)

    def _plot_tx_throughput(self, ax, nodes: list["TangleNode"]) -> None:
        """Transactions issued over time (aggregate)."""
        ax.set_title("Transaction Throughput", fontsize=11, fontweight="bold")
        for node in nodes:
            if node.metrics["txs_issued"]:
                times = [t for t, _ in node.metrics["txs_issued"]]
                cumulative = list(range(1, len(times) + 1))
                ax.plot(times, cumulative, alpha=0.7, linewidth=1.2, label=node.node_id)
        ax.set_xlabel("Wall Time (s)")
        ax.set_ylabel("Cumulative Txs Issued")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    def _plot_convergence(self, ax, nodes: list["TangleNode"]) -> None:
        """Show how much the tangles overlap between nodes."""
        ax.set_title("Tangle Overlap Between Nodes", fontsize=11, fontweight="bold")
        if len(nodes) < 2:
            ax.text(0.5, 0.5, "Need ≥2 nodes", ha="center", va="center")
            return

        # Compute pairwise overlap
        tx_sets = {n.node_id: set(n.tangle.get_all_txs().keys()) for n in nodes}
        names = sorted(tx_sets.keys())
        n = len(names)
        overlap_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                a = tx_sets[names[i]]
                b = tx_sets[names[j]]
                if a | b:
                    overlap_matrix[i, j] = len(a & b) / len(a | b)
                else:
                    overlap_matrix[i, j] = 1.0

        short_names = [n.replace("node_", "N") for n in names]
        im = ax.imshow(overlap_matrix, cmap="YlGn", vmin=0, vmax=1)
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(short_names, fontsize=8)
        ax.set_yticklabels(short_names, fontsize=8)
        plt.colorbar(im, ax=ax, label="Jaccard Overlap")
