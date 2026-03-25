"""
Metrics collection and aggregation across all nodes.

Collects per-node and global statistics that correspond to the
quantities analysed in the papers:

    - L(t): number of tips over time  (Ferraro et al. §II, Figs 7-9)
    - Transaction throughput
    - Network propagation latency
    - Orphan rate (transactions never confirmed)
    - Cumulative weight distribution
    - Tangle divergence between nodes
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.network.node import TangleNode

logger = logging.getLogger(__name__)


@dataclass
class SimulationMetrics:
    """Aggregated simulation results."""
    duration: float = 0.0
    total_txs: int = 0
    total_tips_final: dict[str, int] = field(default_factory=dict)
    avg_tip_count: dict[str, float] = field(default_factory=dict)
    avg_propagation_latency_ms: float = 0.0
    max_propagation_latency_ms: float = 0.0
    orphan_rate: float = 0.0
    tangle_sizes: dict[str, int] = field(default_factory=dict)
    convergence_ratio: float = 0.0  # fraction of txs in all tangles


class MetricsCollector:
    """
    Gathers metrics from all nodes after simulation completes.
    """

    def __init__(self) -> None:
        self._snapshots: list[dict] = []

    def collect(self, nodes: list["TangleNode"], duration: float) -> SimulationMetrics:
        """Aggregate metrics from all nodes."""
        m = SimulationMetrics(duration=duration)

        all_tx_ids: set[str] = set()
        per_node_tx_ids: dict[str, set[str]] = {}
        all_latencies: list[float] = []

        for node in nodes:
            nid = node.node_id
            tangle_txs = set(node.tangle.get_all_txs().keys())
            all_tx_ids |= tangle_txs
            per_node_tx_ids[nid] = tangle_txs

            m.tangle_sizes[nid] = node.tangle.size
            m.total_tips_final[nid] = len(node.tangle.tips)

            # Average tip count from time series
            if node.metrics["tip_counts"]:
                counts = [c for _, c in node.metrics["tip_counts"]]
                m.avg_tip_count[nid] = sum(counts) / len(counts)

            # Propagation latencies
            for _, lat in node.metrics["latencies"]:
                all_latencies.append(lat)

        m.total_txs = len(all_tx_ids)

        if all_latencies:
            m.avg_propagation_latency_ms = sum(all_latencies) / len(all_latencies)
            m.max_propagation_latency_ms = max(all_latencies)

        # Convergence: fraction of all transactions present in every node
        if nodes and all_tx_ids:
            common = set.intersection(*per_node_tx_ids.values()) if per_node_tx_ids else set()
            m.convergence_ratio = len(common) / len(all_tx_ids)

        # Orphan rate: tips that stayed tips (never got approved)
        # across all nodes — approximate as avg final tip count / tangle size
        if m.total_txs > 0:
            avg_tips = sum(m.total_tips_final.values()) / len(m.total_tips_final)
            avg_size = sum(m.tangle_sizes.values()) / len(m.tangle_sizes)
            m.orphan_rate = avg_tips / avg_size if avg_size > 0 else 0

        return m

    def print_report(self, metrics: SimulationMetrics) -> None:
        """Print a human-readable summary."""
        print("\n" + "=" * 70)
        print("  SIMULATION RESULTS")
        print("=" * 70)
        print(f"  Duration:           {metrics.duration:.1f}s")
        print(f"  Total transactions: {metrics.total_txs}")
        print(f"  Convergence ratio:  {metrics.convergence_ratio:.2%}")
        print(f"  Avg latency:        {metrics.avg_propagation_latency_ms:.1f} ms")
        print(f"  Max latency:        {metrics.max_propagation_latency_ms:.1f} ms")
        print(f"  Approx orphan rate: {metrics.orphan_rate:.2%}")
        print()
        print("  Per-node summary:")
        for nid in sorted(metrics.tangle_sizes.keys()):
            size = metrics.tangle_sizes[nid]
            tips = metrics.total_tips_final[nid]
            avg_t = metrics.avg_tip_count.get(nid, 0)
            print(f"    {nid}: size={size}, tips={tips}, avg_tips={avg_t:.1f}")
        print("=" * 70 + "\n")

    def to_json(self, metrics: SimulationMetrics) -> str:
        return json.dumps({
            "duration": metrics.duration,
            "total_txs": metrics.total_txs,
            "tangle_sizes": metrics.tangle_sizes,
            "total_tips_final": metrics.total_tips_final,
            "avg_tip_count": metrics.avg_tip_count,
            "avg_propagation_latency_ms": metrics.avg_propagation_latency_ms,
            "max_propagation_latency_ms": metrics.max_propagation_latency_ms,
            "orphan_rate": metrics.orphan_rate,
            "convergence_ratio": metrics.convergence_ratio,
        }, indent=2)
