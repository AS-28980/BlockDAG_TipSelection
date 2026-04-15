"""
Process launcher — reads a scenario YAML config and spawns one
independent OS process per node via subprocess.Popen.

Architecture:
    launcher.py  ──spawn──►  node_main.py (PID 1001, port 9001)
                 ──spawn──►  node_main.py (PID 1002, port 9002)
                 ──spawn──►  node_main.py (PID 1003, port 9003)
                    ...

The launcher does NOT participate in the simulation.  It:
    1. Generates a shared genesis transaction.
    2. Assigns ports and builds peer lists from the topology config.
    3. Writes a per-node config JSON file.
    4. Spawns each node as `python node/node_main.py --config <file>`.
    5. Waits for all subprocesses to exit.
    6. Calls the aggregator to combine per-node metrics.

This is a true multi-process setup: every node is a separate PID
with its own memory space, its own asyncio event loop, and
communicates with peers only through TCP sockets.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from core.transaction import Transaction, TxStatus

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_scenario(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_topology(node_ids: list[str], topo_cfg: dict) -> dict[str, list[str]]:
    """Return adjacency: node_id → list of neighbour node_ids."""
    ttype = topo_cfg.get("type", "full_mesh")
    n = len(node_ids)
    adj: dict[str, set[str]] = {nid: set() for nid in node_ids}

    if ttype == "full_mesh":
        for i, a in enumerate(node_ids):
            for b in node_ids[i + 1:]:
                adj[a].add(b)
                adj[b].add(a)

    elif ttype == "ring":
        for i in range(n):
            adj[node_ids[i]].add(node_ids[(i + 1) % n])
            adj[node_ids[(i + 1) % n]].add(node_ids[i])

    elif ttype == "star":
        hub = node_ids[0]
        for nid in node_ids[1:]:
            adj[hub].add(nid)
            adj[nid].add(hub)

    elif ttype == "random_k":
        import random
        k = topo_cfg.get("k", 3)
        rng = random.Random(topo_cfg.get("seed", 42))
        for nid in node_ids:
            others = [x for x in node_ids if x != nid]
            peers = rng.sample(others, min(k, len(others)))
            for p in peers:
                adj[nid].add(p)
                adj[p].add(nid)

    elif ttype == "small_world":
        import random
        k = topo_cfg.get("k", 4)
        p_rewire = topo_cfg.get("p_rewire", 0.3)
        rng = random.Random(topo_cfg.get("seed", 42))
        for i in range(n):
            for j in range(1, k // 2 + 1):
                adj[node_ids[i]].add(node_ids[(i + j) % n])
                adj[node_ids[(i + j) % n]].add(node_ids[i])
        for i in range(n):
            for j in range(1, k // 2 + 1):
                if rng.random() < p_rewire:
                    target = rng.choice(node_ids)
                    while target == node_ids[i] or target in adj[node_ids[i]]:
                        target = rng.choice(node_ids)
                    adj[node_ids[i]].add(target)
                    adj[target].add(node_ids[i])

    return {nid: list(neighbours) for nid, neighbours in adj.items()}


def launch(scenario_path: str | Path, output_dir: str = "output",
           log_level: str = "INFO") -> list[subprocess.Popen]:
    """
    Parse config → spawn one OS process per node → return Popen handles.
    """
    cfg = load_scenario(scenario_path)
    sim = cfg.get("simulation", {})
    duration = sim.get("duration", 30.0)
    seed = sim.get("seed", 42)

    nodes_cfg = cfg.get("nodes", {})
    count = nodes_cfg.get("count", 5)
    tx_rate = nodes_cfg.get("tx_rate", 1.0)
    m = nodes_cfg.get("m", 2)
    base_port = nodes_cfg.get("base_port", 9100)

    node_ids = [f"node_{i}" for i in range(count)]
    ports = {nid: base_port + i for i, nid in enumerate(node_ids)}

    topo_cfg = cfg.get("network", {}).get("topology", {})
    topo_cfg.setdefault("seed", seed)
    adjacency = build_topology(node_ids, topo_cfg)

    # Shared genesis
    genesis = Transaction(issuer="GENESIS", parents=[], value=0.0,
                          timestamp=time.time())
    genesis.status = TxStatus.CONFIRMED
    genesis_dict = genesis.to_dict()

    lat_cfg = cfg.get("network", {}).get("latency", {})
    tip_cfg = cfg.get("tip_selection", {})
    pow_cfg = cfg.get("pow", {})
    overrides = nodes_cfg.get("overrides", {})

    # Prepare output & temp config dir
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg_dir = out / "node_configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # Save the scenario for reference
    (out / "scenario.yaml").write_text(yaml.dump(cfg, default_flow_style=False))

    processes: list[subprocess.Popen] = []
    python = sys.executable

    for i, nid in enumerate(node_ids):
        # Per-node overrides
        ovr = overrides.get(nid, {})
        node_rate = ovr.get("tx_rate", tx_rate)

        peers = [
            {"node_id": pid, "host": "127.0.0.1", "port": ports[pid]}
            for pid in adjacency[nid]
        ]

        node_cfg = {
            "node_id": nid,
            "host": "127.0.0.1",
            "port": ports[nid],
            "peers": peers,
            "tip_selection": tip_cfg,
            "pow": pow_cfg,
            "tx_rate": node_rate,
            "m": m,
            "latency": lat_cfg,
            "genesis": genesis_dict,
            "duration": duration,
            "output_dir": str(out / "nodes"),
            "seed": seed + i * 137,
        }

        cfg_path = cfg_dir / f"{nid}.json"
        cfg_path.write_text(json.dumps(node_cfg, indent=2))

        # Spawn the process
        proc = subprocess.Popen(
            [python, str(PROJECT_ROOT / "node" / "node_main.py"),
             "--config", str(cfg_path),
             "--log-level", log_level],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        processes.append(proc)
        log.info("Spawned %s  pid=%d  port=%d  peers=%s",
                 nid, proc.pid, ports[nid],
                 [p["node_id"] for p in peers])

    return processes


def wait_all(processes: list[subprocess.Popen], timeout: float = 300) -> dict[int, int]:
    """Wait for all subprocesses and return pid→returncode map."""
    start = time.time()
    results = {}
    for proc in processes:
        remaining = max(1, timeout - (time.time() - start))
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            log.warning("Process pid=%d timed out, killing", proc.pid)
            proc.kill()
            proc.wait()
        results[proc.pid] = proc.returncode

        # Capture stdout/stderr
        if proc.stdout:
            output = proc.stdout.read().decode(errors="replace")
            if output.strip():
                for line in output.strip().split("\n")[-15:]:
                    log.info("  [pid=%d] %s", proc.pid, line)

    return results
