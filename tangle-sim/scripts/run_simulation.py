#!/usr/bin/env python3
"""
Main entry point — run a full distributed Tangle simulation.

Usage:
    python scripts/run_simulation.py                          # default config
    python scripts/run_simulation.py config/scenarios/large_network.yaml
    python scripts/run_simulation.py --quick                  # 10s quick run
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.simulation.engine import SimulationEngine
from src.visualization.tangle_viz import TangleVisualizer
from src.visualization.dashboard import MetricsDashboard


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tangle Distributed Ledger Simulator")
    parser.add_argument(
        "config", nargs="?",
        default=str(PROJECT_ROOT / "config" / "default.yaml"),
        help="Path to YAML config file",
    )
    parser.add_argument("--quick", action="store_true", help="Quick 10s run with 3 nodes")
    parser.add_argument("--no-viz", action="store_true", help="Skip visualisation output")
    parser.add_argument("--output-dir", default="output", help="Directory for output files")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger("main")

    # Prepare output directory
    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build simulation
    if args.quick:
        config_path = PROJECT_ROOT / "config" / "scenarios" / "small_network.yaml"
    else:
        config_path = Path(args.config)

    logger.info("Loading config from %s", config_path)
    engine = SimulationEngine.from_config(config_path)

    # Run
    logger.info("=" * 60)
    logger.info("  TANGLE DISTRIBUTED LEDGER SIMULATOR")
    logger.info("  Nodes: %d | Duration: %.1fs", len(engine.nodes), engine.duration)
    logger.info("  Algorithm: %s", engine.nodes[0].tip_selector.name if engine.nodes else "N/A")
    logger.info("=" * 60)

    start = time.time()
    metrics = asyncio.run(engine.run())
    elapsed = time.time() - start

    # Print results
    engine.print_results(metrics)

    # Save JSON results
    results_path = output_dir / "results.json"
    results_path.write_text(engine.results_json(metrics))
    logger.info("Results saved to %s", results_path)

    # Generate visualisations
    if not args.no_viz:
        logger.info("Generating visualisations...")

        viz = TangleVisualizer()

        # Render first node's tangle
        if engine.nodes:
            viz.render(
                engine.nodes[0].tangle,
                output_path=output_dir / "tangle_node0.png",
                title=f"Tangle — {engine.nodes[0].node_id}",
            )

            # Render comparison of all nodes
            tangles = {n.node_id: n.tangle for n in engine.nodes}
            viz.render_comparison(
                tangles,
                output_path=output_dir / "tangle_comparison.png",
            )

        # Metrics dashboard
        dashboard = MetricsDashboard()
        dashboard.render(
            engine.nodes, metrics,
            output_path=output_dir / "dashboard.png",
            title=f"Tangle Simulation — {len(engine.nodes)} nodes, "
                  f"{engine.nodes[0].tip_selector.name if engine.nodes else 'N/A'}",
        )

        logger.info("All visualisations saved to %s/", output_dir)

    logger.info("Done in %.1fs", elapsed)


if __name__ == "__main__":
    main()
