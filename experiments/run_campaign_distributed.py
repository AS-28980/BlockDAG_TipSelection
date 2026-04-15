"""
Experiment campaign for tangle-distributed.

Because every run spawns real OS processes (with spawn overhead and port
allocation), we keep this campaign smaller than the in-process one but
still comprehensive.  Each run uses a unique base_port to avoid clashes.

Categories:
  H) MCMC alpha sweep          - confirm paper prediction in true MP setting
  I) Algorithm comparison      - random / mcmc_low / mcmc_high / hybrid
  J) Topology comparison       - full_mesh / ring / small_world / random_k / star
  K) Latency sensitivity       - base_ms ∈ {20, 100, 300, 800}
  L) Scale test                - n_nodes ∈ {3, 5, 8}
  M) Attack scenario           - one node issuing at 4× the rate
  N) Long-run convergence      - 60s, 5 nodes, hybrid
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP_ROOT))

from harness_distributed import run_once  # noqa: E402

RESULTS_DIR = EXP_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True, parents=True)


def _base(**kw):
    b = dict(
        algorithm="hybrid",
        alpha=0.01,
        alpha_high=1.0,
        alpha_low=0.001,
        tx_rate=2.0,
        pow_h=0.2,
        m=2,
        n_nodes=5,
        duration=25.0,
        topology="full_mesh",
        latency_model="lognormal",
        latency_base_ms=100.0,
        latency_jitter_ms=50.0,
        seed=42,
    )
    b.update(kw)
    return b


def build_grid():
    exps = []

    # H) alpha sweep
    for alpha in [0.001, 0.01, 0.1, 0.5, 1.0, 2.0]:
        for seed in [42, 101]:
            exps.append(("H_alpha", _base(algorithm="mcmc", alpha=alpha, seed=seed)))

    # I) algo comparison
    for (tag, over) in [
        ("random", {"algorithm": "random"}),
        ("mcmc_low", {"algorithm": "mcmc", "alpha": 0.001}),
        ("mcmc_high", {"algorithm": "mcmc", "alpha": 1.0}),
        ("hybrid", {"algorithm": "hybrid"}),
    ]:
        for seed in [42, 101]:
            p = _base(seed=seed, **over)
            p["algo_tag"] = tag
            exps.append(("I_algorithm", p))

    # J) topology comparison — need n=8 to make topology matter
    for topo in ["full_mesh", "ring", "small_world", "random_k", "star"]:
        for seed in [42, 101]:
            exps.append(("J_topology", _base(topology=topo, n_nodes=8, seed=seed)))

    # K) latency sweep
    for base_ms in [20, 100, 300, 800]:
        for seed in [42, 101]:
            exps.append(("K_latency", _base(latency_base_ms=base_ms,
                                              latency_jitter_ms=base_ms * 0.3,
                                              seed=seed)))

    # L) scale test
    for n in [3, 5, 8]:
        for seed in [42, 101]:
            exps.append(("L_scale", _base(n_nodes=n, seed=seed)))

    # M) attack: one node issues at 4× rate
    for seed in [42, 101]:
        p = _base(n_nodes=7, tx_rate=1.0, seed=seed)
        p["attacker"] = {"node_0": {"tx_rate": 4.0}}
        exps.append(("M_attack", p))

    # N) long-run baseline
    for seed in [42]:
        exps.append(("N_longrun", _base(duration=60.0, n_nodes=5, seed=seed)))

    # Assign unique base_ports to avoid collisions
    for i, (_, p) in enumerate(exps):
        p["base_port"] = 9500 + i * 20
    return exps


def main():
    grid = build_grid()
    print(f"Total distributed experiments: {len(grid)}", flush=True)
    total_est = sum(p["duration"] for _, p in grid)
    print(f"Estimated sim-time total: {total_est:.0f}s (+ spawn overhead)", flush=True)

    results = []
    t_all = time.time()
    for i, (cat, params) in enumerate(grid, start=1):
        tag = params.pop("algo_tag", None)
        try:
            t0 = time.time()
            r = run_once(params, log_level="ERROR")
            r["category"] = cat
            if tag:
                r["algo_tag"] = tag
            results.append(r)
            print(f"[{i:3d}/{len(grid)}] {cat:14s} "
                  f"n={params['n_nodes']} algo={params['algorithm']} "
                  f"α={params.get('alpha'):.3g} λ={params['tx_rate']} "
                  f"topo={params['topology']} lat={params['latency_base_ms']:.0f} "
                  f"seed={params['seed']} "
                  f"→ txs={r['total_transactions']} "
                  f"conv={r['convergence_ratio']:.2f} "
                  f"L̄={r['mean_L_steady']:.2f} wall={time.time()-t0:.1f}s",
                  flush=True)
        except Exception as e:
            print(f"[{i:3d}/{len(grid)}] {cat} FAILED: {e}", flush=True)
            traceback.print_exc()
            results.append({"category": cat, "params": params, "error": str(e)})

        if i % 3 == 0 or i == len(grid):
            (RESULTS_DIR / "dist_results.json").write_text(
                json.dumps(results, indent=1, default=str))

    print(f"\nTotal wall time: {(time.time()-t_all)/60:.1f} min", flush=True)
    print(f"Saved: {RESULTS_DIR/'dist_results.json'}", flush=True)


if __name__ == "__main__":
    main()
