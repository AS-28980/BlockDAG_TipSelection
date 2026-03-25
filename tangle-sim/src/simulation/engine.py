"""
Simulation engine — orchestrates the distributed Tangle simulation.

Launches all nodes as concurrent async tasks, manages the shared
transport hub, and collects metrics when the simulation completes.

This is the top-level entry point that ties everything together.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from src.network.node import TangleNode
from src.network.transport import TransportHub
from .metrics import MetricsCollector, SimulationMetrics
from .scenario import ScenarioLoader

logger = logging.getLogger(__name__)


class SimulationEngine:
    """
    Orchestrates the full distributed Tangle simulation.

    Usage:
        engine = SimulationEngine.from_config("config/scenarios/small_network.yaml")
        results = asyncio.run(engine.run())
    """

    def __init__(
        self,
        nodes: list[TangleNode],
        hub: TransportHub,
        duration: float = 30.0,
    ) -> None:
        self.nodes = nodes
        self.hub = hub
        self.duration = duration
        self._metrics_collector = MetricsCollector()

    @classmethod
    def from_config(cls, config_path: str | Path) -> "SimulationEngine":
        """Build a simulation from a YAML config file."""
        config = ScenarioLoader.load(config_path)
        nodes, hub, duration = ScenarioLoader.build(config)
        return cls(nodes=nodes, hub=hub, duration=duration)

    @classmethod
    def from_dict(cls, config: dict) -> "SimulationEngine":
        """Build a simulation from a config dictionary."""
        nodes, hub, duration = ScenarioLoader.build(config)
        return cls(nodes=nodes, hub=hub, duration=duration)

    async def run(self) -> SimulationMetrics:
        """
        Run the simulation.

        All nodes start concurrently and run for `self.duration` seconds.
        Each node independently issues transactions, performs PoW, and
        gossips with its peers — just like real distributed nodes.
        """
        logger.info(
            "Starting simulation: %d nodes, duration=%.1fs",
            len(self.nodes), self.duration,
        )

        start_time = time.time()

        # Launch all nodes concurrently
        tasks = [
            asyncio.create_task(node.start(self.duration))
            for node in self.nodes
        ]

        # Also run a progress reporter
        tasks.append(asyncio.create_task(self._progress_loop()))

        # Wait for all nodes to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start_time
        logger.info("Simulation completed in %.1fs", elapsed)

        # Collect and return metrics
        metrics = self._metrics_collector.collect(self.nodes, elapsed)
        return metrics

    async def _progress_loop(self) -> None:
        """Print progress every few seconds."""
        start = time.time()
        interval = max(2.0, self.duration / 10)
        while time.time() - start < self.duration:
            await asyncio.sleep(interval)
            elapsed = time.time() - start
            total_txs = sum(n.tangle.size for n in self.nodes)
            total_tips = sum(len(n.tangle.tips) for n in self.nodes)
            n = len(self.nodes)
            logger.info(
                "[%.0fs/%.0fs] avg_tangle=%.0f avg_tips=%.1f",
                elapsed, self.duration,
                total_txs / n, total_tips / n,
            )

    def print_results(self, metrics: SimulationMetrics) -> None:
        """Print a human-readable report."""
        self._metrics_collector.print_report(metrics)

    def results_json(self, metrics: SimulationMetrics) -> str:
        """Return metrics as JSON string."""
        return self._metrics_collector.to_json(metrics)
