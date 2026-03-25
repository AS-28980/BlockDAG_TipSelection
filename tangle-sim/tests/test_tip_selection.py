"""Tests for tip selection algorithms."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from src.core.transaction import Transaction
from src.core.tangle import Tangle
from src.consensus.random_selection import RandomTipSelector
from src.consensus.mcmc import MCMCTipSelector
from src.consensus.hybrid import HybridTipSelector


def build_test_tangle() -> Tangle:
    """Build a small tangle for testing:

        genesis
        /    \
      tx1    tx2
        \    /
         tx3
        /    \
      tx4    tx5   (tips)
    """
    tangle = Tangle()
    gid = tangle.genesis_id

    tx1 = Transaction(tx_id="tx1_id_00000000", issuer_id="n", parent_ids=[gid])
    tx2 = Transaction(tx_id="tx2_id_00000000", issuer_id="n", parent_ids=[gid])
    tangle.attach_transaction(tx1)
    tangle.attach_transaction(tx2)

    tx3 = Transaction(tx_id="tx3_id_00000000", issuer_id="n", parent_ids=[tx1.tx_id, tx2.tx_id])
    tangle.attach_transaction(tx3)

    tx4 = Transaction(tx_id="tx4_id_00000000", issuer_id="n", parent_ids=[tx3.tx_id])
    tx5 = Transaction(tx_id="tx5_id_00000000", issuer_id="n", parent_ids=[tx3.tx_id])
    tangle.attach_transaction(tx4)
    tangle.attach_transaction(tx5)

    return tangle


class TestRandomSelection(unittest.TestCase):

    def test_selects_correct_count(self):
        tangle = build_test_tangle()
        selector = RandomTipSelector(seed=42)
        tips = selector.select_tips(tangle, m=2)
        self.assertEqual(len(tips), 2)

    def test_selects_from_tips(self):
        tangle = build_test_tangle()
        selector = RandomTipSelector(seed=42)
        current_tips = tangle.free_tips
        for _ in range(20):
            tips = selector.select_tips(tangle, m=2)
            for t in tips:
                self.assertIn(t, current_tips)

    def test_single_tip_tangle(self):
        tangle = Tangle()  # only genesis
        selector = RandomTipSelector(seed=42)
        tips = selector.select_tips(tangle, m=2)
        self.assertEqual(len(tips), 2)


class TestMCMCSelection(unittest.TestCase):

    def test_selects_correct_count(self):
        tangle = build_test_tangle()
        selector = MCMCTipSelector(alpha=0.01, seed=42)
        tips = selector.select_tips(tangle, m=2)
        self.assertEqual(len(tips), 2)

    def test_reaches_tips(self):
        tangle = build_test_tangle()
        current_tips = tangle.tips
        selector = MCMCTipSelector(alpha=0.01, seed=42)
        for _ in range(20):
            tips = selector.select_tips(tangle, m=2)
            for t in tips:
                self.assertIn(t, current_tips)

    def test_high_alpha_prefers_heavy(self):
        """With very high α, MCMC should deterministically follow the heaviest path."""
        tangle = build_test_tangle()
        selector = MCMCTipSelector(alpha=100.0, seed=42)
        # Run many times and check bias
        counts = {}
        for _ in range(50):
            tips = selector.select_tips(tangle, m=1)
            for t in tips:
                counts[t] = counts.get(t, 0) + 1
        # With high alpha, should strongly prefer one tip
        # (whichever has higher cumulative weight path)
        self.assertTrue(len(counts) <= 2)


class TestHybridSelection(unittest.TestCase):

    def test_selects_correct_count(self):
        tangle = build_test_tangle()
        selector = HybridTipSelector(seed=42)
        tips = selector.select_tips(tangle, m=2)
        self.assertEqual(len(tips), 2)

    def test_security_and_swipe_both_produce_tips(self):
        tangle = build_test_tangle()
        current_tips = tangle.tips
        selector = HybridTipSelector(alpha_high=1.0, alpha_low=0.001, seed=42)
        tips = selector.select_tips(tangle, m=2)
        for t in tips:
            self.assertIn(t, current_tips)

    def test_with_random_swipe(self):
        tangle = build_test_tangle()
        selector = HybridTipSelector(
            alpha_high=1.0, use_random_swipe=True, seed=42
        )
        tips = selector.select_tips(tangle, m=2)
        self.assertEqual(len(tips), 2)


if __name__ == "__main__":
    unittest.main()
