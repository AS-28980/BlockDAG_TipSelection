"""
Scenario loader — reads YAML config files and instantiates the full
simulation setup (nodes, topology, tip selectors, PoW, latency model).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.core.pow import ProofOfWork
from src.core.transaction import Transaction
from src.consensus.random_selection import RandomTipSelector
from src.consensus.mcmc import MCMCTipSelector
from src.consensus.hybrid import HybridTipSelector
from src.consensus.tip_selection import TipSelector
from src.network.topology import NetworkTopology
from src.network.transport import LatencyConfig, DelayModel, Transport, TransportHub
from src.network.gossip import GossipProtocol
from src.network.node import TangleNode

logger = logging.getLogger(__name__)


class ScenarioLoader:
    """Load a simulation scenario from a YAML file."""

    @staticmethod
    def load(path: str | Path) -> dict[str, Any]:
        """Parse YAML and return raw config dict."""
        with open(path, "r") as f:
            return yaml.safe_load(f)

    @classmethod
    def build(cls, config: dict[str, Any]) -> tuple[list[TangleNode], TransportHub, float]:
        """
        Construct the full simulation from a config dict.

        Returns (nodes, hub, duration).
        """
        sim_cfg = config.get("simulation", {})
        duration = sim_cfg.get("duration", 30.0)
        seed = sim_cfg.get("seed", 42)

        # ── Latency model ───────────────────────────────────────────────
        lat_cfg = config.get("network", {}).get("latency", {})
        latency = LatencyConfig(
            model=DelayModel[lat_cfg.get("model", "LOGNORMAL").upper()],
            base_ms=lat_cfg.get("base_ms", 100),
            jitter_ms=lat_cfg.get("jitter_ms", 50),
        )

        # ── Nodes ───────────────────────────────────────────────────────
        nodes_cfg = config.get("nodes", {})
        node_count = nodes_cfg.get("count", 5)
        tx_rate = nodes_cfg.get("tx_rate", 1.0)
        m = nodes_cfg.get("m", 2)

        node_ids = [f"node_{i}" for i in range(node_count)]

        # ── Topology ────────────────────────────────────────────────────
        topo_cfg = config.get("network", {}).get("topology", {})
        topo_type = topo_cfg.get("type", "full_mesh")
        topo_k = topo_cfg.get("k", 3)

        if topo_type == "full_mesh":
            topology = NetworkTopology.full_mesh(node_ids, latency)
        elif topo_type == "ring":
            topology = NetworkTopology.ring(node_ids, latency)
        elif topo_type == "random_k":
            topology = NetworkTopology.random_k(node_ids, k=topo_k, default_latency=latency, seed=seed)
        elif topo_type == "small_world":
            p_rewire = topo_cfg.get("p_rewire", 0.3)
            topology = NetworkTopology.small_world(
                node_ids, k=topo_k, p_rewire=p_rewire,
                default_latency=latency, seed=seed,
            )
        elif topo_type == "star":
            topology = NetworkTopology.star(node_ids, latency)
        else:
            topology = NetworkTopology.full_mesh(node_ids, latency)

        # ── PoW ─────────────────────────────────────────────────────────
        pow_cfg = config.get("pow", {})
        pow_h = pow_cfg.get("h", 1.0)
        pow_diff = pow_cfg.get("difficulty", 0)
        pow_engine = ProofOfWork(h=pow_h, difficulty=pow_diff)

        # ── Shared genesis ──────────────────────────────────────────────
        genesis = Transaction(
            issuer_id="GENESIS",
            parent_ids=[],
            value=0.0,
            sender_address="",
            receiver_address="",
        )
        genesis.pow_complete_time = genesis.timestamp

        # ── Tip selection algorithm ─────────────────────────────────────
        algo_cfg = config.get("tip_selection", {})
        algo_type = algo_cfg.get("algorithm", "hybrid")

        def make_selector(node_seed: int) -> TipSelector:
            if algo_type == "random":
                return RandomTipSelector(seed=node_seed)
            elif algo_type == "mcmc":
                alpha = algo_cfg.get("alpha", 0.01)
                return MCMCTipSelector(alpha=alpha, seed=node_seed)
            elif algo_type == "hybrid":
                return HybridTipSelector(
                    alpha_high=algo_cfg.get("alpha_high", 1.0),
                    alpha_low=algo_cfg.get("alpha_low", 0.001),
                    use_random_swipe=algo_cfg.get("use_random_swipe", False),
                    security_selections=algo_cfg.get("security_selections", 1),
                    seed=node_seed,
                )
            else:
                return HybridTipSelector(seed=node_seed)

        # ── Gossip ──────────────────────────────────────────────────────
        gossip_cfg = config.get("network", {}).get("gossip", {})
        gossip_strategy = gossip_cfg.get("strategy", "flood")
        gossip_k = gossip_cfg.get("k", 3)

        # ── Build transport hub and nodes ───────────────────────────────
        hub = TransportHub()
        nodes: list[TangleNode] = []

        # Check for per-node overrides
        per_node_overrides = nodes_cfg.get("overrides", {})

        for i, nid in enumerate(node_ids):
            transport = Transport(
                node_id=nid,
                latency=latency,
                seed=seed + i,
            )
            hub.register(transport)

            # Per-node override of tx_rate or algorithm
            override = per_node_overrides.get(nid, {})
            node_tx_rate = override.get("tx_rate", tx_rate)

            selector = make_selector(seed + i * 100)
            gossip = GossipProtocol(strategy=gossip_strategy, k=gossip_k, seed=seed + i)

            # Clone genesis for each node (same tx_id but independent object)
            node_genesis = Transaction(
                tx_id=genesis.tx_id,
                issuer_id=genesis.issuer_id,
                parent_ids=genesis.parent_ids,
                value=genesis.value,
                timestamp=genesis.timestamp,
            )
            node_genesis.pow_complete_time = genesis.pow_complete_time

            node = TangleNode(
                node_id=nid,
                transport=transport,
                tip_selector=selector,
                pow=pow_engine,
                tx_rate=node_tx_rate,
                neighbours=topology.neighbours(nid),
                gossip=gossip,
                m=m,
                genesis=node_genesis,
            )
            nodes.append(node)

        logger.info(
            "Scenario built: %d nodes, topology=%s, algo=%s, λ=%.2f, h=%.2f, duration=%.1fs",
            len(nodes), topo_type, algo_type, tx_rate, pow_h, duration,
        )
        return nodes, hub, duration
