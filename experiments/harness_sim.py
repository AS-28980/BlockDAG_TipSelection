"""
Experiment harness for tangle-sim (in-process asyncio simulator).

Takes a parameter dict, builds a scenario config, runs the simulation,
and returns a structured result dict including the L(t) time series
from every node, final tangle metrics, convergence, and latencies.

Used by run_campaign_sim.py to sweep parameters and collect data.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIM_ROOT = PROJECT_ROOT / "tangle-sim"
sys.path.insert(0, str(SIM_ROOT))

from src.simulation.engine import SimulationEngine  # noqa: E402


def build_config(
    *,
    algorithm: str = "hybrid",
    alpha: float = 0.01,
    alpha_high: float = 1.0,
    alpha_low: float = 0.001,
    use_random_swipe: bool = False,
    tx_rate: float = 2.0,
    pow_h: float = 0.3,
    m: int = 2,
    n_nodes: int = 5,
    duration: float = 30.0,
    topology: str = "full_mesh",
    topo_k: int = 3,
    p_rewire: float = 0.3,
    latency_model: str = "LOGNORMAL",
    latency_base_ms: float = 100.0,
    latency_jitter_ms: float = 50.0,
    gossip_strategy: str = "flood",
    gossip_k: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    return {
        "simulation": {"duration": duration, "seed": seed},
        "nodes": {"count": n_nodes, "tx_rate": tx_rate, "m": m},
        "tip_selection": {
            "algorithm": algorithm,
            "alpha": alpha,
            "alpha_high": alpha_high,
            "alpha_low": alpha_low,
            "use_random_swipe": use_random_swipe,
        },
        "pow": {"h": pow_h, "difficulty": 0},
        "network": {
            "topology": {"type": topology, "k": topo_k, "p_rewire": p_rewire},
            "latency": {"model": latency_model, "base_ms": latency_base_ms,
                        "jitter_ms": latency_jitter_ms},
            "gossip": {"strategy": gossip_strategy, "k": gossip_k},
        },
    }


def run_once(params: dict[str, Any], *, log_level: str = "ERROR") -> dict[str, Any]:
    """Build sim from a parameter dict, run it, and return a result dict."""
    logging.getLogger().setLevel(getattr(logging, log_level))
    cfg = build_config(**params)

    engine = SimulationEngine.from_dict(cfg)
    t0 = time.time()
    metrics = asyncio.run(engine.run())
    wall = time.time() - t0

    # Pull per-node L(t) series and latencies
    tip_time_series: dict[str, list[tuple[float, int]]] = {}
    latencies: list[float] = []
    issued_per_node: dict[str, int] = {}
    for node in engine.nodes:
        tip_time_series[node.node_id] = list(node.metrics.get("tip_counts", []))
        latencies.extend([lat for _, lat in node.metrics.get("latencies", [])])
        issued_per_node[node.node_id] = getattr(node, "issued_count", 0) or len(
            [k for k, v in node.tangle.get_all_txs().items() if v.issuer_id == node.node_id]
        )

    tangle_sizes = list(metrics.tangle_sizes.values())
    size_mean = sum(tangle_sizes) / len(tangle_sizes) if tangle_sizes else 0
    size_var = (sum((s - size_mean) ** 2 for s in tangle_sizes) / len(tangle_sizes)
                if tangle_sizes else 0)

    # avg steady-state L(t): mean of tip counts across all nodes, last half of series
    all_L = []
    for series in tip_time_series.values():
        if len(series) >= 4:
            half = series[len(series) // 2:]
            all_L.extend(c for _, c in half)
    mean_L_steady = sum(all_L) / len(all_L) if all_L else 0
    peak_L = max((c for s in tip_time_series.values() for _, c in s), default=0)

    return {
        "params": params,
        "wall_time_s": wall,
        "duration": metrics.duration,
        "total_txs": metrics.total_txs,
        "convergence_ratio": metrics.convergence_ratio,
        "orphan_rate": metrics.orphan_rate,
        "avg_latency_ms": metrics.avg_propagation_latency_ms,
        "max_latency_ms": metrics.max_propagation_latency_ms,
        "tangle_sizes": metrics.tangle_sizes,
        "size_mean": size_mean,
        "size_stddev": size_var ** 0.5,
        "total_tips_final": metrics.total_tips_final,
        "avg_tip_count": metrics.avg_tip_count,
        "mean_L_steady": mean_L_steady,
        "peak_L": peak_L,
        "tip_time_series": tip_time_series,
        "issued_per_node": issued_per_node,
        "latencies_sample": latencies[:1000],
    }


if __name__ == "__main__":
    import json
    r = run_once({"n_nodes": 3, "duration": 15.0, "tx_rate": 2.0, "pow_h": 0.3})
    print(json.dumps({k: v for k, v in r.items() if k not in ("tip_time_series", "latencies_sample")}, indent=2, default=str))
