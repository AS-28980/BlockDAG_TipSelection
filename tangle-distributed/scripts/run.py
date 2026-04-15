#!/usr/bin/env python3
"""
Main entry point — spawn distributed Tangle simulation.

Usage:
    python scripts/run.py                                      # default config
    python scripts/run.py config/scenarios/small_network.yaml   # specific scenario
    python scripts/run.py --quick                               # 3-node quick test
"""

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.launcher import launch, wait_all, load_scenario
from simulation.aggregator import aggregate, print_report
from viz.dashboard import generate_dashboard, generate_tangle_viz


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Distributed Tangle Simulator — multi-process"
    )
    parser.add_argument(
        "config", nargs="?",
        default=str(PROJECT_ROOT / "config" / "default.yaml"),
        help="Path to scenario YAML",
    )
    parser.add_argument("--quick", action="store_true",
                        help="Quick 15s run with 3 nodes")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--no-viz", action="store_true")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("launcher")

    if args.quick:
        cfg_path = PROJECT_ROOT / "config" / "scenarios" / "small_network.yaml"
    else:
        cfg_path = Path(args.config)

    output_dir = PROJECT_ROOT / args.output_dir
    cfg = load_scenario(cfg_path)
    sim = cfg.get("simulation", {})
    n_nodes = cfg.get("nodes", {}).get("count", 5)
    duration = sim.get("duration", 30)
    algo = cfg.get("tip_selection", {}).get("algorithm", "hybrid")

    log.info("=" * 65)
    log.info("  DISTRIBUTED TANGLE SIMULATOR  (multi-process)")
    log.info("  Config:    %s", cfg_path.name)
    log.info("  Nodes:     %d separate OS processes", n_nodes)
    log.info("  Duration:  %.0fs", duration)
    log.info("  Algorithm: %s", algo)
    log.info("  Transport: TCP sockets with simulated latency")
    log.info("=" * 65)

    start = time.time()

    # 1. Spawn all node processes
    processes = launch(cfg_path, output_dir=str(output_dir),
                       log_level=args.log_level)
    log.info("All %d processes spawned.  PIDs: %s",
             len(processes), [p.pid for p in processes])

    # 2. Wait for all to finish
    log.info("Waiting for simulation to complete (≈%.0fs)...", duration + 5)
    results = wait_all(processes, timeout=duration + 30)
    elapsed = time.time() - start

    failed = sum(1 for rc in results.values() if rc != 0)
    if failed:
        log.warning("%d/%d processes exited with errors", failed, len(results))

    log.info("All processes finished in %.1fs", elapsed)

    # 3. Aggregate
    log.info("Aggregating per-node metrics...")
    agg = aggregate(str(output_dir))
    if agg:
        print_report(agg)

    # 4. Visualise
    if not args.no_viz and agg:
        log.info("Generating visualisations...")
        generate_dashboard(agg, str(output_dir),
                           title=f"Distributed Tangle — {n_nodes} processes, {algo}")
        generate_tangle_viz(agg, str(output_dir))
        log.info("Visualisations saved to %s/", output_dir)

    log.info("Done in %.1fs total", elapsed)


if __name__ == "__main__":
    main()
