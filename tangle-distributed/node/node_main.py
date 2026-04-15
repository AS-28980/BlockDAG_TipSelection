#!/usr/bin/env python3
"""
Entry point for a SINGLE node process.

The launcher (scripts/launch.py) spawns one of these per node via
    subprocess.Popen(["python", "node/node_main.py", "--config", path])

Each invocation is a fully independent OS process with its own PID,
its own asyncio event loop, its own TCP server, and its own Tangle.

The config JSON passed via --config contains:
    node_id, host, port, peers, tip_selection, pow, tx_rate, m,
    latency, genesis, duration, output_dir, seed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tip_selection import build_selector
from core.pow import PoW
from network.peer import LatencyModel
from node.process import TangleNode


def main() -> None:
    parser = argparse.ArgumentParser(description="Tangle Node Process")
    parser.add_argument("--config", required=True, help="Path to node config JSON")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = json.loads(Path(args.config).read_text())

    selector = build_selector(cfg.get("tip_selection", {}), seed=cfg.get("seed", 0))
    pow_cfg = cfg.get("pow", {})
    pow_engine = PoW(h=pow_cfg.get("h", 1.0), difficulty=pow_cfg.get("difficulty", 0))

    lat_cfg = cfg.get("latency", {})
    latency = LatencyModel(
        model=lat_cfg.get("model", "lognormal"),
        base_ms=lat_cfg.get("base_ms", 100),
        jitter_ms=lat_cfg.get("jitter_ms", 50),
    )

    node = TangleNode(
        node_id=cfg["node_id"],
        host=cfg.get("host", "127.0.0.1"),
        port=cfg["port"],
        peers=cfg.get("peers", []),
        selector=selector,
        pow=pow_engine,
        tx_rate=cfg.get("tx_rate", 1.0),
        m=cfg.get("m", 2),
        latency=latency,
        genesis_dict=cfg["genesis"],
        duration=cfg.get("duration", 30.0),
        output_dir=cfg.get("output_dir", "output"),
        seed=cfg.get("seed", 0),
    )

    asyncio.run(node.run())


if __name__ == "__main__":
    main()
