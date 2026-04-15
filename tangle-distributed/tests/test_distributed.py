"""
Integration test — spawn actual OS processes, verify they converge.

This is the key test: it spawns 3 separate Python processes, lets them
run for a few seconds exchanging transactions over real TCP sockets,
then checks that their tangles converged.
"""

import sys
import json
import time
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from simulation.launcher import launch, wait_all
from simulation.aggregator import aggregate

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDistributed(unittest.TestCase):
    def test_three_node_convergence(self):
        """Spawn 3 real OS processes and check they converge."""
        output_dir = PROJECT_ROOT / "test_output"
        if output_dir.exists():
            shutil.rmtree(output_dir)

        cfg_path = PROJECT_ROOT / "config" / "scenarios" / "small_network.yaml"
        processes = launch(cfg_path, output_dir=str(output_dir), log_level="WARNING")

        self.assertEqual(len(processes), 3)
        # All should have distinct PIDs
        pids = [p.pid for p in processes]
        self.assertEqual(len(set(pids)), 3, "All nodes should be separate PIDs")

        results = wait_all(processes, timeout=60)

        # All should exit cleanly
        for pid, rc in results.items():
            self.assertEqual(rc, 0, f"Process {pid} exited with code {rc}")

        # Check that per-node metric files were written
        nodes_dir = output_dir / "nodes"
        self.assertTrue(nodes_dir.exists())
        node_files = list(nodes_dir.glob("node_*.json"))
        self.assertEqual(len(node_files), 3)

        # Aggregate and check convergence
        agg = aggregate(str(output_dir))
        self.assertGreater(agg["total_transactions"], 1)
        self.assertGreater(agg["convergence_ratio"], 0.5,
                           "Nodes should converge on >50% of transactions")

        # Cleanup
        shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
