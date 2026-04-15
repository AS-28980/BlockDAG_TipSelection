"""
Post-run aggregator — reads per-node JSON metrics and combines them
into a single report + generates visualisations.

Each node independently wrote its metrics to output/nodes/<node_id>.json.
This module reads all of them, computes cross-node statistics, and
produces the same metrics as the tangle-sim version for comparison.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


def aggregate(output_dir: str | Path) -> dict:
    """Read all node JSON files and compute aggregate metrics."""
    nodes_dir = Path(output_dir) / "nodes"
    if not nodes_dir.exists():
        log.error("No nodes directory found at %s", nodes_dir)
        return {}

    node_files = sorted(nodes_dir.glob("node_*.json"))
    if not node_files:
        log.error("No node metric files found in %s", nodes_dir)
        return {}

    node_data: list[dict] = []
    for f in node_files:
        node_data.append(json.loads(f.read_text()))

    # -- Per-node summaries ------------------------------------------------
    all_tx_ids: set[str] = set()
    per_node_tx_ids: dict[str, set[str]] = {}
    tangle_sizes: dict[str, int] = {}
    final_tips: dict[str, int] = {}
    avg_tips: dict[str, float] = {}
    all_latencies: list[float] = []
    node_pids: dict[str, int] = {}
    total_issued = 0

    for nd in node_data:
        nid = nd["node_id"]
        node_pids[nid] = nd.get("pid", 0)
        tx_set = set(nd.get("all_tx_ids", []))
        all_tx_ids |= tx_set
        per_node_tx_ids[nid] = tx_set
        tangle_sizes[nid] = nd["tangle_summary"]["size"]
        final_tips[nid] = nd["tangle_summary"]["tips"]
        total_issued += nd["txs_issued"]

        th = nd.get("tip_history", [])
        if th:
            avg_tips[nid] = sum(c for _, c in th) / len(th)
        else:
            avg_tips[nid] = 0

        all_latencies.extend(nd.get("latencies", []))

    # -- Cross-node metrics ------------------------------------------------
    total_txs = len(all_tx_ids)
    if per_node_tx_ids:
        common = set.intersection(*per_node_tx_ids.values())
        convergence = len(common) / total_txs if total_txs else 1.0
    else:
        convergence = 0.0

    avg_lat = float(np.mean(all_latencies)) if all_latencies else 0.0
    max_lat = float(np.max(all_latencies)) if all_latencies else 0.0

    avg_final_tips = float(np.mean(list(final_tips.values()))) if final_tips else 0
    avg_size = float(np.mean(list(tangle_sizes.values()))) if tangle_sizes else 0
    orphan_rate = avg_final_tips / avg_size if avg_size > 0 else 0

    result = {
        "total_transactions": total_txs,
        "total_issued": total_issued,
        "convergence_ratio": convergence,
        "orphan_rate": orphan_rate,
        "avg_propagation_latency_ms": avg_lat,
        "max_propagation_latency_ms": max_lat,
        "per_node": {
            nid: {
                "pid": node_pids.get(nid, 0),
                "tangle_size": tangle_sizes[nid],
                "final_tips": final_tips[nid],
                "avg_tips": avg_tips.get(nid, 0),
                "txs_issued": next(
                    (nd["txs_issued"] for nd in node_data if nd["node_id"] == nid), 0
                ),
            }
            for nid in sorted(tangle_sizes.keys())
        },
        "node_data": node_data,   # keep raw data for viz
    }

    # Write combined results
    out_path = Path(output_dir) / "results.json"
    out_path.write_text(json.dumps(
        {k: v for k, v in result.items() if k != "node_data"},
        indent=2,
    ))
    log.info("Aggregate results written to %s", out_path)

    return result


def print_report(result: dict) -> None:
    """Print human-readable summary."""
    print("\n" + "=" * 70)
    print("  DISTRIBUTED TANGLE SIMULATION RESULTS")
    print("  (each node ran as a separate OS process)")
    print("=" * 70)
    print(f"  Total transactions:     {result['total_transactions']}")
    print(f"  Total issued:           {result['total_issued']}")
    print(f"  Convergence ratio:      {result['convergence_ratio']:.2%}")
    print(f"  Approx orphan rate:     {result['orphan_rate']:.2%}")
    print(f"  Avg propagation latency: {result['avg_propagation_latency_ms']:.1f} ms")
    print(f"  Max propagation latency: {result['max_propagation_latency_ms']:.1f} ms")
    print()
    pn = result.get("per_node", {})
    print(f"  {'Node':<12} {'PID':>6} {'Tangle':>8} {'Tips':>6} {'Avg Tips':>10} {'Issued':>8}")
    print(f"  {'-'*12} {'-'*6} {'-'*8} {'-'*6} {'-'*10} {'-'*8}")
    for nid, info in sorted(pn.items()):
        print(f"  {nid:<12} {info['pid']:>6} {info['tangle_size']:>8} "
              f"{info['final_tips']:>6} {info['avg_tips']:>10.1f} {info['txs_issued']:>8}")
    print("=" * 70 + "\n")
