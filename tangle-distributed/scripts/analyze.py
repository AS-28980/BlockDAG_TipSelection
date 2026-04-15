#!/usr/bin/env python3
"""
Post-hoc analysis — read results.json and print a report.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="?",
                        default=str(PROJECT_ROOT / "output" / "results.json"))
    args = parser.parse_args()

    path = Path(args.results)
    if not path.exists():
        print(f"Not found: {path}")
        print("Run the simulation first: python scripts/run.py")
        sys.exit(1)

    data = json.loads(path.read_text())

    print("\n" + "=" * 65)
    print("  DISTRIBUTED TANGLE — POST-HOC ANALYSIS")
    print("=" * 65)
    print(f"  Total transactions:      {data['total_transactions']}")
    print(f"  Total issued:            {data['total_issued']}")
    print(f"  Convergence:             {data['convergence_ratio']:.2%}")
    print(f"  Orphan rate:             {data['orphan_rate']:.2%}")
    print(f"  Avg latency:             {data['avg_propagation_latency_ms']:.1f} ms")
    print(f"  Max latency:             {data['max_propagation_latency_ms']:.1f} ms")

    pn = data.get("per_node", {})
    sizes = [info["tangle_size"] for info in pn.values()]
    if len(sizes) > 1:
        mean_s = sum(sizes) / len(sizes)
        var = sum((s - mean_s) ** 2 for s in sizes) / len(sizes)
        print(f"\n  Tangle size mean:        {mean_s:.1f}")
        print(f"  Tangle size std-dev:     {var**0.5:.2f}")
        print(f"  (lower = more converged)")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
