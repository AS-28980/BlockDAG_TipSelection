"""
Aggregate, analyze and plot the campaign results.

Reads experiments/results/sim_results.json and dist_results.json, produces:
 - experiments/results/sim_summary.csv   (flat table, one row per run)
 - experiments/results/dist_summary.csv
 - experiments/plots/*.png
 - experiments/results/combined_analysis.json
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

EXP = Path(__file__).resolve().parent
RES = EXP / "results"
PLOTS = EXP / "plots"
PLOTS.mkdir(exist_ok=True, parents=True)


def load(path):
    if not path.exists():
        return []
    return json.loads(path.read_text())


# -------------------- Flat CSVs --------------------
SIM_FIELDS = [
    "category", "algorithm", "alpha", "alpha_high", "alpha_low", "tx_rate",
    "pow_h", "m", "n_nodes", "duration", "topology", "latency_model",
    "latency_base_ms", "latency_jitter_ms", "seed", "algo_tag",
    "total_txs", "convergence_ratio", "orphan_rate", "avg_latency_ms",
    "max_latency_ms", "size_mean", "size_stddev", "mean_L_steady", "peak_L",
    "wall_time_s",
]

DIST_FIELDS = [
    "category", "algorithm", "alpha", "alpha_high", "alpha_low", "tx_rate",
    "pow_h", "m", "n_nodes", "duration", "topology", "latency_model",
    "latency_base_ms", "latency_jitter_ms", "seed", "algo_tag",
    "total_transactions", "total_issued", "convergence_ratio", "orphan_rate",
    "avg_propagation_latency_ms", "max_propagation_latency_ms",
    "mean_L_steady", "peak_L", "unique_pids", "wall_time_s",
]


def flatten(records, fields):
    rows = []
    for r in records:
        if "error" in r:
            continue
        p = r.get("params", {})
        row = {}
        for k in fields:
            if k in r:
                row[k] = r[k]
            elif k in p:
                row[k] = p[k]
            else:
                row[k] = ""
        rows.append(row)
    return rows


def write_csv(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def group_mean(records, key_fn, value_fn):
    """Return {key: (mean, stdev, n)} grouping records."""
    buckets = defaultdict(list)
    for r in records:
        if "error" in r:
            continue
        try:
            v = value_fn(r)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            buckets[key_fn(r)].append(v)
        except Exception:
            pass
    out = {}
    for k, vs in buckets.items():
        if vs:
            out[k] = (statistics.mean(vs),
                      statistics.stdev(vs) if len(vs) > 1 else 0.0,
                      len(vs))
    return out


# -------------------- PLOT HELPERS --------------------
def _errbar(ax, xs, groups, label=None, color=None):
    if not groups:
        return
    xs_sorted = sorted(groups.keys())
    means = [groups[x][0] for x in xs_sorted]
    stds = [groups[x][1] for x in xs_sorted]
    ax.errorbar(xs_sorted, means, yerr=stds, fmt="o-", capsize=4,
                label=label, color=color, linewidth=2, markersize=6)


def plot_alpha_sweep(sim_recs, dist_recs):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("MCMC α sensitivity — reproduction of Ferraro et al. Figs 7-9",
                 fontsize=14, fontweight="bold")

    sim_alpha = [r for r in sim_recs if r.get("category") == "A_alpha_sweep"]
    dist_alpha = [r for r in dist_recs if r.get("category") == "H_alpha"]

    # Panel 1: mean tips L(t) vs alpha (log x)
    ax = axes[0]
    g_sim = group_mean(sim_alpha, lambda r: r["params"]["alpha"],
                       lambda r: r["mean_L_steady"])
    g_dst = group_mean(dist_alpha, lambda r: r["params"]["alpha"],
                       lambda r: r["mean_L_steady"])
    _errbar(ax, None, g_sim, label="tangle-sim", color="tab:blue")
    _errbar(ax, None, g_dst, label="tangle-distributed", color="tab:orange")
    ax.set_xscale("log")
    ax.set_xlabel("α (MCMC bias)")
    ax.set_ylabel("Steady-state mean L(t)  (# tips)")
    ax.set_title("Tip count vs α")
    ax.grid(alpha=0.3)
    ax.legend()

    # Panel 2: convergence vs alpha
    ax = axes[1]
    g_sim = group_mean(sim_alpha, lambda r: r["params"]["alpha"],
                       lambda r: r["convergence_ratio"])
    g_dst = group_mean(dist_alpha, lambda r: r["params"]["alpha"],
                       lambda r: r["convergence_ratio"])
    _errbar(ax, None, g_sim, "tangle-sim", "tab:blue")
    _errbar(ax, None, g_dst, "tangle-distributed", "tab:orange")
    ax.set_xscale("log")
    ax.set_xlabel("α")
    ax.set_ylabel("Convergence ratio")
    ax.set_title("Convergence vs α")
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.3)
    ax.legend()

    # Panel 3: orphan rate vs alpha
    ax = axes[2]
    g_sim = group_mean(sim_alpha, lambda r: r["params"]["alpha"],
                       lambda r: r["orphan_rate"])
    g_dst = group_mean(dist_alpha, lambda r: r["params"]["alpha"],
                       lambda r: r["orphan_rate"])
    _errbar(ax, None, g_sim, "tangle-sim", "tab:blue")
    _errbar(ax, None, g_dst, "tangle-distributed", "tab:orange")
    ax.set_xscale("log")
    ax.set_xlabel("α")
    ax.set_ylabel("Orphan rate")
    ax.set_title("Orphan rate vs α")
    ax.grid(alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(PLOTS / "01_alpha_sweep.png", dpi=150)
    plt.close()


def plot_Lt_curves(sim_recs):
    """Plot L(t) time-series overlaid for each alpha in the sweep."""
    sim_alpha = [r for r in sim_recs
                 if r.get("category") == "A_alpha_sweep" and r["params"]["seed"] == 42]
    if not sim_alpha:
        return
    fig, ax = plt.subplots(figsize=(11, 6))
    sim_alpha.sort(key=lambda r: r["params"]["alpha"])
    colors = plt.cm.viridis(np.linspace(0, 0.95, len(sim_alpha)))
    for i, r in enumerate(sim_alpha):
        series_by_node = r.get("tip_time_series", {})
        if not series_by_node:
            continue
        # average across nodes at each sample time
        all_t = sorted({t for s in series_by_node.values() for t, _ in s})
        if not all_t:
            continue
        ys = []
        for t in all_t:
            vals = []
            for s in series_by_node.values():
                closest = min(s, key=lambda tc: abs(tc[0] - t))
                vals.append(closest[1])
            ys.append(sum(vals) / len(vals))
        ax.plot(all_t, ys, color=colors[i], linewidth=1.8,
                label=f"α = {r['params']['alpha']:g}")
    ax.set_xlabel("Simulation time (s)")
    ax.set_ylabel("L(t) = mean # tips across nodes")
    ax.set_title("L(t) trajectories under MCMC for increasing α (tangle-sim)")
    ax.grid(alpha=0.3)
    ax.legend(title="α", loc="upper left", fontsize=9)
    plt.tight_layout()
    plt.savefig(PLOTS / "02_Lt_curves_alpha.png", dpi=150)
    plt.close()


def plot_algorithm_comparison(sim_recs, dist_recs):
    sim_a = [r for r in sim_recs if r.get("category") == "B_algorithm"]
    dist_a = [r for r in dist_recs if r.get("category") == "I_algorithm"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Algorithm comparison — Random vs MCMC(α=0.001) vs MCMC(α=1.0) vs Hybrid",
                 fontsize=13, fontweight="bold")

    metrics = [
        ("mean_L_steady", "Steady-state mean L(t)"),
        ("convergence_ratio", "Convergence ratio"),
        ("orphan_rate", "Orphan rate"),
        ("avg_latency_ms", "Avg propagation latency (ms)"),
    ]
    dist_metrics = {
        "mean_L_steady": "mean_L_steady",
        "convergence_ratio": "convergence_ratio",
        "orphan_rate": "orphan_rate",
        "avg_latency_ms": "avg_propagation_latency_ms",
    }

    tags = ["random", "mcmc_low", "mcmc_high", "hybrid"]
    x = np.arange(len(tags))
    width = 0.35

    for ax, (m, title) in zip(axes.flat, metrics):
        sim_vals = [group_mean(sim_a, lambda r, t=t: r.get("algo_tag"),
                                lambda r, k=m: r[k]).get(t, (0, 0, 0)) for t in tags]
        dm = dist_metrics[m]
        dist_vals = [group_mean(dist_a, lambda r: r.get("algo_tag"),
                                lambda r, k=dm: r[k]).get(t, (0, 0, 0)) for t in tags]

        sim_m = [v[0] for v in sim_vals]
        sim_e = [v[1] for v in sim_vals]
        dist_m = [v[0] for v in dist_vals]
        dist_e = [v[1] for v in dist_vals]

        ax.bar(x - width/2, sim_m, width, yerr=sim_e, capsize=4,
               label="tangle-sim", color="tab:blue")
        ax.bar(x + width/2, dist_m, width, yerr=dist_e, capsize=4,
               label="tangle-distributed", color="tab:orange")
        ax.set_xticks(x)
        ax.set_xticklabels(tags, rotation=10)
        ax.set_title(title)
        ax.grid(alpha=0.3, axis="y")
        ax.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(PLOTS / "03_algorithm_comparison.png", dpi=150)
    plt.close()


def plot_lambda_sweep(sim_recs):
    recs = [r for r in sim_recs if r.get("category") == "C_lambda"]
    if not recs:
        return
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    g_L = group_mean(recs, lambda r: r["params"]["tx_rate"],
                     lambda r: r["mean_L_steady"])
    g_T = group_mean(recs, lambda r: r["params"]["tx_rate"],
                     lambda r: r["total_txs"] / r["duration"])

    _errbar(axes[0], None, g_L, "sim", "tab:blue")
    axes[0].set_xlabel("λ  (tx/s per node)")
    axes[0].set_ylabel("Steady-state L(t)")
    axes[0].set_title("Paper prediction: L ~ 2λh  —  tip count grows linearly with λ")
    axes[0].grid(alpha=0.3)

    _errbar(axes[1], None, g_T, "throughput", "tab:green")
    axes[1].set_xlabel("λ  (tx/s per node)")
    axes[1].set_ylabel("Observed throughput (tx/s aggregate)")
    axes[1].set_title("Throughput scaling")
    axes[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOTS / "04_lambda_sweep.png", dpi=150)
    plt.close()


def plot_h_sweep(sim_recs):
    recs = [r for r in sim_recs if r.get("category") == "D_pow_h"]
    if not recs:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    g_L = group_mean(recs, lambda r: r["params"]["pow_h"],
                     lambda r: r["mean_L_steady"])
    _errbar(ax, None, g_L, "L(t)", "tab:red")
    ax.set_xlabel("h (PoW delay, s)")
    ax.set_ylabel("Steady-state L(t)")
    ax.set_title("Effect of PoW delay h on tip count (paper: L ≈ 2λh)")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOTS / "05_h_sweep.png", dpi=150)
    plt.close()


def plot_topology(sim_recs, dist_recs):
    sim_t = [r for r in sim_recs if r.get("category") == "F_topology"]
    dst_t = [r for r in dist_recs if r.get("category") == "J_topology"]

    topos = ["full_mesh", "ring", "small_world", "random_k", "star"]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Topology comparison (n=8 nodes)", fontsize=13, fontweight="bold")

    for ax, metric, label in [
        (axes[0], "convergence_ratio", "Convergence ratio"),
        (axes[1], "avg_latency_ms", "Avg propagation latency (ms)"),
        (axes[2], "mean_L_steady", "Steady-state L(t)"),
    ]:
        dm = {"avg_latency_ms": "avg_propagation_latency_ms"}.get(metric, metric)
        sim_g = group_mean(sim_t, lambda r: r["params"]["topology"],
                           lambda r, k=metric: r[k])
        dst_g = group_mean(dst_t, lambda r: r["params"]["topology"],
                           lambda r, k=dm: r[k])
        sim_m = [sim_g.get(t, (0, 0, 0))[0] for t in topos]
        sim_e = [sim_g.get(t, (0, 0, 0))[1] for t in topos]
        dst_m = [dst_g.get(t, (0, 0, 0))[0] for t in topos]
        dst_e = [dst_g.get(t, (0, 0, 0))[1] for t in topos]
        x = np.arange(len(topos))
        ax.bar(x - 0.2, sim_m, 0.4, yerr=sim_e, capsize=3, label="sim", color="tab:blue")
        ax.bar(x + 0.2, dst_m, 0.4, yerr=dst_e, capsize=3, label="dist", color="tab:orange")
        ax.set_xticks(x)
        ax.set_xticklabels(topos, rotation=15)
        ax.set_title(label)
        ax.grid(alpha=0.3, axis="y")
        ax.legend()

    plt.tight_layout()
    plt.savefig(PLOTS / "06_topology.png", dpi=150)
    plt.close()


def plot_latency(sim_recs, dist_recs):
    sim_l = [r for r in sim_recs if r.get("category") == "G_latency"]
    dst_l = [r for r in dist_recs if r.get("category") == "K_latency"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, metric, dm, title in [
        (axes[0], "mean_L_steady", "mean_L_steady", "L(t) vs base latency"),
        (axes[1], "convergence_ratio", "convergence_ratio", "Convergence vs base latency"),
    ]:
        sim_g = group_mean(sim_l, lambda r: r["params"]["latency_base_ms"],
                           lambda r, k=metric: r[k])
        dst_g = group_mean(dst_l, lambda r: r["params"]["latency_base_ms"],
                           lambda r, k=dm: r[k])
        _errbar(ax, None, sim_g, "sim", "tab:blue")
        _errbar(ax, None, dst_g, "dist", "tab:orange")
        ax.set_xscale("log")
        ax.set_xlabel("base latency (ms)")
        ax.set_ylabel(metric)
        ax.set_title(title)
        ax.grid(alpha=0.3)
        ax.legend()
    plt.tight_layout()
    plt.savefig(PLOTS / "07_latency.png", dpi=150)
    plt.close()


def plot_scale(sim_recs, dist_recs):
    sim_s = [r for r in sim_recs if r.get("category") == "E_scale"]
    dst_s = [r for r in dist_recs if r.get("category") == "L_scale"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, metric, dm, title in [
        (axes[0], "mean_L_steady", "mean_L_steady", "L(t) vs #nodes"),
        (axes[1], "convergence_ratio", "convergence_ratio", "Convergence vs #nodes"),
    ]:
        sim_g = group_mean(sim_s, lambda r: r["params"]["n_nodes"],
                           lambda r, k=metric: r[k])
        dst_g = group_mean(dst_s, lambda r: r["params"]["n_nodes"],
                           lambda r, k=dm: r[k])
        _errbar(ax, None, sim_g, "sim", "tab:blue")
        _errbar(ax, None, dst_g, "dist", "tab:orange")
        ax.set_xlabel("# nodes")
        ax.set_ylabel(metric)
        ax.set_title(title)
        ax.grid(alpha=0.3)
        ax.legend()
    plt.tight_layout()
    plt.savefig(PLOTS / "08_scale.png", dpi=150)
    plt.close()


def plot_attack(dist_recs):
    attack = [r for r in dist_recs if r.get("category") == "M_attack"]
    if not attack:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    # Issued tx by node_0 (attacker) vs others
    attacker_issued = []
    honest_avg = []
    for r in attack:
        per = r.get("per_node", {})
        iss = per.get("node_0", {}).get("txs_issued", 0)
        attacker_issued.append(iss)
        others = [v.get("txs_issued", 0) for k, v in per.items() if k != "node_0"]
        honest_avg.append(sum(others) / len(others) if others else 0)
    x = np.arange(len(attack))
    ax.bar(x - 0.2, attacker_issued, 0.4, label="attacker (node_0, λ=4)", color="crimson")
    ax.bar(x + 0.2, honest_avg, 0.4, label="honest avg (λ=1)", color="tab:blue")
    ax.set_xticks(x)
    ax.set_xticklabels([f"run {i+1}" for i in range(len(attack))])
    ax.set_ylabel("Transactions issued")
    ax.set_title("Attack scenario — attacker issues 4× rate (7 nodes, tangle-distributed)")
    ax.grid(alpha=0.3, axis="y")
    ax.legend()
    plt.tight_layout()
    plt.savefig(PLOTS / "09_attack.png", dpi=150)
    plt.close()


def plot_sim_vs_dist(sim_recs, dist_recs):
    """Scatter: for matching categories, compare L(t) and convergence."""
    # Use algorithm comparison overlap
    pairs_sim = [(r.get("algo_tag"), r["mean_L_steady"], r["convergence_ratio"])
                 for r in sim_recs if r.get("category") == "B_algorithm"]
    pairs_dst = [(r.get("algo_tag"), r["mean_L_steady"], r["convergence_ratio"])
                 for r in dist_recs if r.get("category") == "I_algorithm"]

    fig, ax = plt.subplots(figsize=(8, 6))
    if pairs_sim and pairs_dst:
        sim_L = [p[1] for p in pairs_sim]
        dst_L = [p[1] for p in pairs_dst]
        # match by algo_tag and seed isn't guaranteed; just scatter all
        ax.scatter(sim_L, [x for _, x, _ in pairs_sim][:len(sim_L)], marker="o",
                   label="sim (L vs L)", alpha=0.6)
        ax.scatter(dst_L, [x for _, x, _ in pairs_dst][:len(dst_L)], marker="^",
                   label="dist (L vs L)", alpha=0.6)
    ax.set_xlabel("L(t) sim")
    ax.set_ylabel("L(t) dist")
    ax.set_title("Sim vs Distributed — cross-validation")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOTS / "10_sim_vs_dist.png", dpi=150)
    plt.close()


def summary_stats(sim_recs, dist_recs):
    """Build a high-level summary JSON."""
    out = {
        "sim_runs": len([r for r in sim_recs if "error" not in r]),
        "dist_runs": len([r for r in dist_recs if "error" not in r]),
        "sim_total_txs": sum(r.get("total_txs", 0) for r in sim_recs),
        "dist_total_txs": sum(r.get("total_transactions", 0) for r in dist_recs),
    }
    # Average convergence per campaign
    sc = [r["convergence_ratio"] for r in sim_recs if "error" not in r]
    dc = [r["convergence_ratio"] for r in dist_recs if "error" not in r]
    out["sim_mean_convergence"] = statistics.mean(sc) if sc else 0
    out["dist_mean_convergence"] = statistics.mean(dc) if dc else 0
    out["sim_mean_L"] = statistics.mean(
        r["mean_L_steady"] for r in sim_recs if "error" not in r) if sim_recs else 0
    out["dist_mean_L"] = statistics.mean(
        r["mean_L_steady"] for r in dist_recs if "error" not in r) if dist_recs else 0

    # alpha sweep means for quick paper comparison
    alpha_sim = defaultdict(list)
    for r in sim_recs:
        if r.get("category") == "A_alpha_sweep":
            alpha_sim[r["params"]["alpha"]].append(r["mean_L_steady"])
    out["sim_alpha_L"] = {str(k): statistics.mean(v) for k, v in alpha_sim.items()}
    alpha_dst = defaultdict(list)
    for r in dist_recs:
        if r.get("category") == "H_alpha":
            alpha_dst[r["params"]["alpha"]].append(r["mean_L_steady"])
    out["dist_alpha_L"] = {str(k): statistics.mean(v) for k, v in alpha_dst.items()}
    return out


def main():
    sim = load(RES / "sim_results.json")
    dist = load(RES / "dist_results.json")
    print(f"Loaded {len(sim)} sim records, {len(dist)} distributed records")

    # CSVs
    write_csv(RES / "sim_summary.csv", SIM_FIELDS, flatten(sim, SIM_FIELDS))
    write_csv(RES / "dist_summary.csv", DIST_FIELDS, flatten(dist, DIST_FIELDS))
    print(f"Wrote CSVs to {RES}")

    # Plots
    plot_alpha_sweep(sim, dist)
    plot_Lt_curves(sim)
    plot_algorithm_comparison(sim, dist)
    plot_lambda_sweep(sim)
    plot_h_sweep(sim)
    plot_topology(sim, dist)
    plot_latency(sim, dist)
    plot_scale(sim, dist)
    plot_attack(dist)
    plot_sim_vs_dist(sim, dist)

    # Summary
    summ = summary_stats(sim, dist)
    (RES / "combined_analysis.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))
    print(f"\n✓ Plots saved to {PLOTS}/")


if __name__ == "__main__":
    main()
