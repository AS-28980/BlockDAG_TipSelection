"""
Network topology definitions.

Defines how nodes are connected to each other.  Supports several
graph structures commonly used in P2P network research.

Also allows per-link latency overrides so that certain links can
simulate long-distance WAN hops while others are local.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from .transport import LatencyConfig, DelayModel


@dataclass
class LinkConfig:
    """Per-link override of latency parameters."""
    node_a: str
    node_b: str
    latency: LatencyConfig = field(default_factory=LatencyConfig)


class NetworkTopology:
    """
    Manages the peer graph and per-link latency configuration.

    Supports built-in topologies:
        - "full_mesh":   every node connected to every other
        - "ring":        each node connected to its two neighbours
        - "random_k":    each node connected to k random peers
        - "small_world": Watts-Strogatz small-world graph
        - "star":        one hub connected to all others
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, set[str]] = {}
        self._link_latency: dict[tuple[str, str], LatencyConfig] = {}

    @property
    def nodes(self) -> list[str]:
        return list(self._adjacency.keys())

    def neighbours(self, node_id: str) -> list[str]:
        return list(self._adjacency.get(node_id, set()))

    def add_node(self, node_id: str) -> None:
        if node_id not in self._adjacency:
            self._adjacency[node_id] = set()

    def add_link(
        self, a: str, b: str, latency: LatencyConfig | None = None
    ) -> None:
        self._adjacency.setdefault(a, set()).add(b)
        self._adjacency.setdefault(b, set()).add(a)
        if latency:
            key = tuple(sorted([a, b]))
            self._link_latency[key] = latency

    def get_link_latency(self, a: str, b: str) -> LatencyConfig | None:
        key = tuple(sorted([a, b]))
        return self._link_latency.get(key)

    # ── Factory methods for common topologies ───────────────────────────
    @classmethod
    def full_mesh(
        cls,
        node_ids: list[str],
        default_latency: LatencyConfig | None = None,
    ) -> NetworkTopology:
        topo = cls()
        for nid in node_ids:
            topo.add_node(nid)
        for i, a in enumerate(node_ids):
            for b in node_ids[i + 1:]:
                topo.add_link(a, b, default_latency)
        return topo

    @classmethod
    def ring(
        cls,
        node_ids: list[str],
        default_latency: LatencyConfig | None = None,
    ) -> NetworkTopology:
        topo = cls()
        for nid in node_ids:
            topo.add_node(nid)
        n = len(node_ids)
        for i in range(n):
            topo.add_link(node_ids[i], node_ids[(i + 1) % n], default_latency)
        return topo

    @classmethod
    def random_k(
        cls,
        node_ids: list[str],
        k: int = 3,
        default_latency: LatencyConfig | None = None,
        seed: int | None = None,
    ) -> NetworkTopology:
        rng = random.Random(seed)
        topo = cls()
        for nid in node_ids:
            topo.add_node(nid)
        for nid in node_ids:
            others = [x for x in node_ids if x != nid]
            peers = rng.sample(others, min(k, len(others)))
            for p in peers:
                topo.add_link(nid, p, default_latency)
        return topo

    @classmethod
    def small_world(
        cls,
        node_ids: list[str],
        k: int = 4,
        p_rewire: float = 0.3,
        default_latency: LatencyConfig | None = None,
        seed: int | None = None,
    ) -> NetworkTopology:
        """Watts-Strogatz small-world topology."""
        rng = random.Random(seed)
        topo = cls()
        n = len(node_ids)
        for nid in node_ids:
            topo.add_node(nid)
        # Start with ring lattice with k nearest neighbours
        for i in range(n):
            for j in range(1, k // 2 + 1):
                topo.add_link(
                    node_ids[i], node_ids[(i + j) % n], default_latency
                )
        # Rewire with probability p
        for i in range(n):
            for j in range(1, k // 2 + 1):
                if rng.random() < p_rewire:
                    target = rng.choice(node_ids)
                    while target == node_ids[i] or target in topo.neighbours(node_ids[i]):
                        target = rng.choice(node_ids)
                    # Remove old edge (we keep it — small-world often adds)
                    topo.add_link(node_ids[i], target, default_latency)
        return topo

    @classmethod
    def star(
        cls,
        node_ids: list[str],
        default_latency: LatencyConfig | None = None,
    ) -> NetworkTopology:
        topo = cls()
        for nid in node_ids:
            topo.add_node(nid)
        hub = node_ids[0]
        for nid in node_ids[1:]:
            topo.add_link(hub, nid, default_latency)
        return topo

    def summary(self) -> dict:
        edge_count = sum(len(v) for v in self._adjacency.values()) // 2
        return {
            "nodes": len(self._adjacency),
            "edges": edge_count,
            "avg_degree": (2 * edge_count / len(self._adjacency))
            if self._adjacency
            else 0,
        }

    def __repr__(self) -> str:
        s = self.summary()
        return f"Topology(nodes={s['nodes']}, edges={s['edges']}, avg_deg={s['avg_degree']:.1f})"
