"""
Full experiment campaign for tangle-sim.

Runs multiple parameter sweeps, each with multiple seeds, and saves all
results to experiments/results/sim_results.json plus a flat CSV for
easy analysis.

Experiment categories:
  A) MCMC alpha sweep        - reproduces Ferraro Figs 7-9 intuition
  B) Algorithm comparison    - Random / MCMC-low / MCMC-high / Hybrid
  C) Arrival rate lambda     - L(t) scaling with throughput
  D) PoW delay h sweep       - stability vs latency
  E) Scale test              - n_nodes varying
  F) Topology comparison     - full_mesh / ring / small_world / random_k / star
  G) Latency sensitivity     - base_ms varying
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP_ROOT))

from harness_sim import run_once  # noqa: E402

RESULTS_DIR = EXP_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True, parents=True)


def _base(**kw):
    """Baseline config; override via kwargs."""
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
        latency_model="LOGNORMAL",
        latency_base_ms=100.0,
        latency_jitter_ms=50.0,
        seed=42,
    )
    b.update(kw)
    return b


def build_experiment_grid():
    exps = []

    # A) Alpha sweep for MCMC
    for alpha in [0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0]:
        for seed in [42, 101]:
            exps.append(("A_alpha_sweep",
                         _base(algorithm="mcmc", alpha=alpha, seed=seed)))

    # B) Algorithm comparison
    algos = [
        ("random", {"algorithm": "random"}),
        ("mcmc_low", {"algorithm": "mcmc", "alpha": 0.001}),
        ("mcmc_high", {"algorithm": "mcmc", "alpha": 1.0}),
        ("hybrid", {"algorithm": "hybrid"}),
    ]
    for name, over in algos:
        for seed in [42, 101]:
            exps.append(("B_algorithm", _base(seed=seed, **over) | {"algo_tag": name}))

    # C) Arrival rate sweep (lambda in txs/sec per node)
    for lam in [0.5, 1.0, 2.0, 5.0, 10.0]:
        for seed in [42, 101]:
            exps.append(("C_lambda", _base(tx_rate=lam, seed=seed)))

    # D) PoW h sweep
    for h in [0.1, 0.3, 0.6, 1.0]:
        for seed in [42, 101]:
            exps.append(("D_pow_h", _base(pow_h=h, seed=seed)))

    # E) Scale test (nodes)
    for n in [3, 5, 8, 12]:
        for seed in [42, 101]:
            exps.append(("E_scale", _base(n_nodes=n, seed=seed)))

    # F) Topology comparison
    for topo in ["full_mesh", "ring", "small_world", "random_k", "star"]:
        for seed in [42, 101]:
            exps.append(("F_topology", _base(topology=topo, n_nodes=8, seed=seed)))

    # G) Latency sensitivity
    for base_ms in [20, 100, 300, 800]:
        for seed in [42, 101]:
            exps.append(("G_latency", _base(latency_base_ms=base_ms,
                                            latency_jitter_ms=base_ms * 0.3,
                                            seed=seed)))

    return exps


def main():
    grid = build_experiment_grid()
    print(f"Total tangle-sim experiments: {len(grid)}")
    total_est = sum(p[1]["duration"] for p in grid)
    print(f"Estimated sim-time total: {total_est:.0f}s")

    all_results = []
    t_all = time.time()
    for i, (category, params) in enumerate(grid, start=1):
        tag = params.pop("algo_tag", None)
        try:
            t0 = time.time()
            r = run_once(params, log_level="ERROR")
            r["category"] = category
            if tag:
                r["algo_tag"] = tag
            all_results.append(r)
            print(f"[{i:3d}/{len(grid)}] {category:16s} "
                  f"n={params['n_nodes']} algo={params['algorithm']} "
                  f"α={params.get('alpha'):.3g} λ={params['tx_rate']} "
                  f"h={params['pow_h']} topo={params['topology']} "
                  f"seed={params['seed']} "
                  f"→ txs={r['total_txs']} L̄={r['mean_L_steady']:.2f} "
                  f"conv={r['convergence_ratio']:.2f} "
                  f"wall={time.time()-t0:.1f}s")
        except Exception as e:
            print(f"[{i:3d}/{len(grid)}] {category} FAILED: {e}")
            traceback.print_exc()
            all_results.append({"category": category, "params": params,
                                "error": str(e)})

        # Write progressively so partial runs are saved
        if i % 5 == 0 or i == len(grid):
            (RESULTS_DIR / "sim_results.json").write_text(
                json.dumps(all_results, indent=1, default=str))

    print(f"\nTotal wall time: {(time.time()-t_all)/60:.1f} minutes")
    print(f"Results saved to {RESULTS_DIR/'sim_results.json'}")


if __name__ == "__main__":
    main()
