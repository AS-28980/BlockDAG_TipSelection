"""
Visualization dashboard — generates multi-panel figures from
the aggregated results of the distributed simulation.

Reproduces the key figures from the papers:
    - L(t) per node  (Ferraro et al. Figs 7-9)
    - Tangle size per node (bar chart)
    - Propagation latency histogram
    - Cumulative weight distribution
    - Transaction throughput
    - Convergence heatmap
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

log = logging.getLogger(__name__)


def generate_dashboard(
    agg_result: dict,
    output_dir: str | Path,
    title: str = "Distributed Tangle Simulation",
) -> Path:
    """Generate a 6-panel dashboard from aggregated results."""
    node_data = agg_result.get("node_data", [])
    if not node_data:
        log.warning("No node data for dashboard")
        return Path(output_dir) / "dashboard.png"

    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

    _plot_tip_count(axes[0, 0], node_data)
    _plot_tangle_sizes(axes[0, 1], agg_result)
    _plot_latency(axes[0, 2], node_data)
    _plot_weights(axes[1, 0], node_data)
    _plot_throughput(axes[1, 1], node_data)
    _plot_convergence(axes[1, 2], node_data)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out = Path(output_dir) / "dashboard.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Dashboard saved to %s", out)
    return out


def generate_tangle_viz(
    agg_result: dict,
    output_dir: str | Path,
) -> Path:
    """Generate a per-node tangle comparison figure."""
    node_data = agg_result.get("node_data", [])
    n = len(node_data)
    if n == 0:
        return Path(output_dir) / "tangle_comparison.png"

    fig, axes = plt.subplots(1, min(n, 6), figsize=(min(n, 6) * 5, 5))
    if n == 1:
        axes = [axes]

    for ax, nd in zip(axes, node_data[:6]):
        edges = nd.get("edges", [])
        all_tx_ids = set(nd.get("all_tx_ids", []))
        tips = set()
        # Reconstruct tip set: nodes with no children
        parents_of = defaultdict(set)
        for child, parent in edges:
            parents_of[parent].add(child)
        for txid in all_tx_ids:
            if txid not in parents_of or not parents_of[txid]:
                tips.add(txid)

        # Simple layout: hash-based scatter
        positions = {}
        for i, txid in enumerate(sorted(all_tx_ids)):
            x = i * 0.3
            y = (hash(txid) % 100) / 100 * 4 - 2
            positions[txid] = (x, y)

        # Draw edges
        for child, parent in edges:
            if child in positions and parent in positions:
                x0, y0 = positions[child]
                x1, y1 = positions[parent]
                ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                            arrowprops=dict(arrowstyle="->", color="#B0BEC5",
                                            lw=0.5, alpha=0.4))

        # Draw nodes
        for txid, (x, y) in positions.items():
            color = "#EF5350" if txid in tips else "#78909C"
            ax.scatter(x, y, s=30, c=color, alpha=0.8, edgecolors="none", zorder=5)

        nid = nd["node_id"]
        size = nd["tangle_summary"]["size"]
        tip_count = nd["tangle_summary"]["tips"]
        ax.set_title(f"{nid} (size={size}, tips={tip_count})", fontsize=9)
        ax.axis("off")

    plt.tight_layout()
    out = Path(output_dir) / "tangle_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# -- individual panels -----------------------------------------------------

def _plot_tip_count(ax, node_data: list[dict]) -> None:
    ax.set_title("L(t): Tip Count Over Time", fontsize=11, fontweight="bold")
    for nd in node_data:
        th = nd.get("tip_history", [])
        if th:
            t, c = zip(*th)
            ax.plot(t, c, alpha=0.7, lw=1.2, label=nd["node_id"])
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("L(t)")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)


def _plot_tangle_sizes(ax, result: dict) -> None:
    ax.set_title("Final Tangle Size per Node", fontsize=11, fontweight="bold")
    pn = result.get("per_node", {})
    names = sorted(pn.keys())
    sizes = [pn[n]["tangle_size"] for n in names]
    short = [n.replace("node_", "N") for n in names]
    ax.bar(short, sizes, color="#5C6BC0", alpha=0.8)
    ax.set_ylabel("Transactions")
    ax.grid(True, alpha=0.3, axis="y")


def _plot_latency(ax, node_data: list[dict]) -> None:
    ax.set_title("Propagation Latency Distribution", fontsize=11, fontweight="bold")
    lats = []
    for nd in node_data:
        lats.extend(nd.get("latencies", []))
    if lats:
        ax.hist(lats, bins=40, color="#26A69A", alpha=0.8, edgecolor="white")
        ax.axvline(np.mean(lats), color="red", ls="--",
                   label=f"Mean: {np.mean(lats):.0f}ms")
        ax.legend(fontsize=8)
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Count")
    ax.grid(True, alpha=0.3)


def _plot_weights(ax, node_data: list[dict]) -> None:
    ax.set_title("Cumulative Weight Distribution", fontsize=11, fontweight="bold")
    # Use first node as representative
    if node_data:
        # Reconstruct weights from edges
        nd = node_data[0]
        edges = nd.get("edges", [])
        all_ids = set(nd.get("all_tx_ids", []))
        # Count approvers per tx
        approver_count: dict[str, int] = defaultdict(lambda: 1)
        children_of: dict[str, set[str]] = defaultdict(set)
        for child, parent in edges:
            children_of[parent].add(child)
        # BFS from each node to count all indirect approvers
        for txid in all_ids:
            visited = set()
            stack = [txid]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                for kid in children_of.get(cur, set()):
                    stack.append(kid)
            approver_count[txid] = len(visited)
        weights = list(approver_count.values())
        if weights:
            ax.hist(weights, bins=30, color="#FFA726", alpha=0.8, edgecolor="white")
    ax.set_xlabel("Cumulative Weight")
    ax.set_ylabel("Count")
    ax.grid(True, alpha=0.3)


def _plot_throughput(ax, node_data: list[dict]) -> None:
    ax.set_title("Transaction Throughput", fontsize=11, fontweight="bold")
    for nd in node_data:
        issued = nd.get("issued", [])
        if issued:
            times = [t for t, _ in issued]
            if times:
                t0 = times[0]
                times = [t - t0 for t in times]
                cum = list(range(1, len(times) + 1))
                ax.plot(times, cum, alpha=0.7, lw=1.2, label=nd["node_id"])
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Cumulative Txs Issued")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)


def _plot_convergence(ax, node_data: list[dict]) -> None:
    ax.set_title("Tangle Overlap Between Nodes", fontsize=11, fontweight="bold")
    if len(node_data) < 2:
        ax.text(0.5, 0.5, "Need ≥2 nodes", ha="center", va="center")
        return
    tx_sets = {nd["node_id"]: set(nd.get("all_tx_ids", [])) for nd in node_data}
    names = sorted(tx_sets.keys())
    n = len(names)
    mat = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            a, b = tx_sets[names[i]], tx_sets[names[j]]
            mat[i, j] = len(a & b) / len(a | b) if (a | b) else 1.0
    short = [n.replace("node_", "N") for n in names]
    im = ax.imshow(mat, cmap="YlGn", vmin=0, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(short, fontsize=8)
    ax.set_yticklabels(short, fontsize=8)
    plt.colorbar(im, ax=ax, label="Jaccard Overlap")
