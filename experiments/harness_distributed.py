"""
Experiment harness for tangle-distributed (true multi-process TCP simulator).

Writes a YAML config, spawns N subprocesses, waits for them to exit,
aggregates per-node metrics, and returns a structured result dict.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_ROOT = PROJECT_ROOT / "tangle-distributed"
sys.path.insert(0, str(DIST_ROOT))

from simulation.launcher import launch, wait_all  # noqa: E402
from simulation.aggregator import aggregate  # noqa: E402

EXP_DIR = PROJECT_ROOT / "experiments" / "dist_tmp_output"


def build_config(
    *,
    algorithm: str = "hybrid",
    alpha: float = 0.01,
    alpha_high: float = 1.0,
    alpha_low: float = 0.001,
    tx_rate: float = 2.0,
    pow_h: float = 0.2,
    m: int = 2,
    n_nodes: int = 5,
    duration: float = 30.0,
    topology: str = "full_mesh",
    topo_k: int = 3,
    p_rewire: float = 0.3,
    latency_model: str = "lognormal",
    latency_base_ms: float = 100.0,
    latency_jitter_ms: float = 50.0,
    seed: int = 42,
    base_port: int = 9300,
    attacker: dict | None = None,
) -> dict:
    cfg = {
        "simulation": {"duration": duration, "seed": seed},
        "nodes": {"count": n_nodes, "tx_rate": tx_rate, "m": m,
                  "base_port": base_port},
        "tip_selection": {"algorithm": algorithm, "alpha": alpha,
                          "alpha_high": alpha_high, "alpha_low": alpha_low},
        "pow": {"h": pow_h, "difficulty": 0},
        "network": {
            "topology": {"type": topology, "k": topo_k, "p_rewire": p_rewire},
            "latency": {"model": latency_model,
                        "base_ms": latency_base_ms,
                        "jitter_ms": latency_jitter_ms},
        },
    }
    if attacker:
        cfg["nodes"]["overrides"] = attacker
    return cfg


def run_once(params: dict[str, Any], *, log_level: str = "WARNING",
             timeout_extra: float = 60.0) -> dict[str, Any]:
    """Spawn processes for a single config and return aggregated result."""
    cfg = build_config(**params)

    # Unique tmp dir per run
    run_id = f"run_{int(time.time()*1000) % 100000}_{params.get('seed', 0)}"
    out_dir = EXP_DIR / run_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = out_dir / "scenario.yaml"
    yaml_path.write_text(yaml.dump(cfg, default_flow_style=False))

    t0 = time.time()
    procs = launch(yaml_path, output_dir=str(out_dir), log_level=log_level)
    pids = [p.pid for p in procs]
    rc = wait_all(procs, timeout=params["duration"] + timeout_extra)
    wall = time.time() - t0

    agg = aggregate(str(out_dir))

    # Load per-node json to get tip_history for L(t) analysis
    tip_time_series: dict[str, list] = {}
    nodes_dir = out_dir / "nodes"
    for f in sorted(nodes_dir.glob("node_*.json")) if nodes_dir.exists() else []:
        nd = json.loads(f.read_text())
        tip_time_series[nd["node_id"]] = nd.get("tip_history", [])

    # Steady-state mean tips
    all_L = []
    peak_L = 0
    for series in tip_time_series.values():
        if len(series) >= 4:
            half = series[len(series) // 2:]
            all_L.extend(c for _, c in half)
        for _, c in series:
            peak_L = max(peak_L, c)
    mean_L_steady = sum(all_L) / len(all_L) if all_L else 0

    # Cleanup to avoid disk bloat but keep node JSONs summary
    result = {
        "params": params,
        "pids": pids,
        "unique_pids": len(set(pids)),
        "exit_codes": rc,
        "wall_time_s": wall,
        "total_transactions": agg.get("total_transactions", 0),
        "total_issued": agg.get("total_issued", 0),
        "convergence_ratio": agg.get("convergence_ratio", 0),
        "orphan_rate": agg.get("orphan_rate", 0),
        "avg_propagation_latency_ms": agg.get("avg_propagation_latency_ms", 0),
        "max_propagation_latency_ms": agg.get("max_propagation_latency_ms", 0),
        "per_node": agg.get("per_node", {}),
        "mean_L_steady": mean_L_steady,
        "peak_L": peak_L,
        "tip_time_series": tip_time_series,
    }
    # cleanup node configs, keep metrics
    for sub in ("node_configs",):
        p = out_dir / sub
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    return result


if __name__ == "__main__":
    r = run_once({"n_nodes": 3, "duration": 20.0, "tx_rate": 2.0,
                  "pow_h": 0.2, "base_port": 9400})
    brief = {k: v for k, v in r.items() if k not in ("tip_time_series", "per_node")}
    print(json.dumps(brief, indent=2, default=str))
