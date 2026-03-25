#!/usr/bin/env python3
"""
Post-hoc analysis of simulation results.

Reads the JSON output and node metrics to produce additional analyses:
    - Compare tip dynamics across different α values
    - Measure tangle convergence over time
    - Identify orphaned transactions
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def analyze(results_path: Path) -> None:
    with open(results_path) as f:
        data = json.load(f)

    print("\n" + "=" * 60)
    print("  POST-HOC ANALYSIS")
    print("=" * 60)

    print(f"\n  Duration:        {data['duration']:.1f}s")
    print(f"  Total txs:       {data['total_txs']}")
    print(f"  Convergence:     {data['convergence_ratio']:.2%}")
    print(f"  Orphan rate:     {data['orphan_rate']:.2%}")
    print(f"  Avg latency:     {data['avg_propagation_latency_ms']:.1f} ms")
    print(f"  Max latency:     {data['max_propagation_latency_ms']:.1f} ms")

    # Per-node analysis
    print("\n  Per-node final state:")
    print(f"  {'Node':<12} {'Tangle':>8} {'Tips':>6} {'Avg Tips':>10}")
    print(f"  {'-'*12} {'-'*8} {'-'*6} {'-'*10}")
    for nid in sorted(data["tangle_sizes"].keys()):
        size = data["tangle_sizes"][nid]
        tips = data["total_tips_final"][nid]
        avg_tips = data["avg_tip_count"].get(nid, 0)
        print(f"  {nid:<12} {size:>8} {tips:>6} {avg_tips:>10.1f}")

    # Compute size variance (measure of divergence)
    sizes = list(data["tangle_sizes"].values())
    if len(sizes) > 1:
        mean_size = sum(sizes) / len(sizes)
        variance = sum((s - mean_size) ** 2 for s in sizes) / len(sizes)
        print(f"\n  Tangle size variance: {variance:.2f}")
        print(f"  Tangle size std-dev:  {variance**0.5:.2f}")
        print(f"  (Lower = more converged between nodes)")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Analyze simulation results")
    parser.add_argument(
        "results", nargs="?",
        default=str(PROJECT_ROOT / "output" / "results.json"),
        help="Path to results.json",
    )
    args = parser.parse_args()

    path = Path(args.results)
    if not path.exists():
        print(f"Results file not found: {path}")
        print("Run the simulation first: python scripts/run_simulation.py")
        sys.exit(1)

    analyze(path)


if __name__ == "__main__":
    main()
