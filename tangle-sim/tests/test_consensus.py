"""Integration tests — end-to-end simulation with consensus."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import unittest
from src.simulation.engine import SimulationEngine


class TestSimulationIntegration(unittest.TestCase):

    def test_quick_simulation(self):
        """Run a minimal simulation and verify basic invariants."""
        config = {
            "simulation": {"duration": 5.0, "seed": 42},
            "nodes": {"count": 3, "tx_rate": 2.0, "m": 2},
            "tip_selection": {"algorithm": "hybrid", "alpha_high": 1.0, "alpha_low": 0.001},
            "pow": {"h": 0.2, "difficulty": 0},
            "network": {
                "topology": {"type": "full_mesh"},
                "latency": {"model": "CONSTANT", "base_ms": 20, "jitter_ms": 0},
                "gossip": {"strategy": "flood"},
            },
        }
        engine = SimulationEngine.from_dict(config)
        metrics = asyncio.run(engine.run())

        # Basic sanity checks
        self.assertGreater(metrics.total_txs, 1)  # at least genesis + some txs
        self.assertEqual(len(metrics.tangle_sizes), 3)

        # Each node should have at least the genesis
        for size in metrics.tangle_sizes.values():
            self.assertGreaterEqual(size, 1)

    def test_mcmc_algorithm(self):
        """Run with pure MCMC tip selection."""
        config = {
            "simulation": {"duration": 4.0, "seed": 99},
            "nodes": {"count": 2, "tx_rate": 3.0, "m": 2},
            "tip_selection": {"algorithm": "mcmc", "alpha": 0.01},
            "pow": {"h": 0.1, "difficulty": 0},
            "network": {
                "topology": {"type": "full_mesh"},
                "latency": {"model": "CONSTANT", "base_ms": 10, "jitter_ms": 0},
                "gossip": {"strategy": "flood"},
            },
        }
        engine = SimulationEngine.from_dict(config)
        metrics = asyncio.run(engine.run())
        self.assertGreater(metrics.total_txs, 1)

    def test_random_algorithm(self):
        """Run with random tip selection."""
        config = {
            "simulation": {"duration": 4.0, "seed": 55},
            "nodes": {"count": 2, "tx_rate": 3.0, "m": 2},
            "tip_selection": {"algorithm": "random"},
            "pow": {"h": 0.1, "difficulty": 0},
            "network": {
                "topology": {"type": "ring"},
                "latency": {"model": "UNIFORM", "base_ms": 30, "jitter_ms": 10},
                "gossip": {"strategy": "flood"},
            },
        }
        engine = SimulationEngine.from_dict(config)
        metrics = asyncio.run(engine.run())
        self.assertGreater(metrics.total_txs, 1)


if __name__ == "__main__":
    unittest.main()
