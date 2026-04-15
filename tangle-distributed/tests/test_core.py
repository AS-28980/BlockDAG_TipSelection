"""Unit tests for core data structures."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from core.transaction import Transaction, TxStatus
from core.tangle import Tangle
from core.tip_selection import RandomSelector, MCMCSelector, HybridSelector
from core.validation import tips_consistent


class TestTangle(unittest.TestCase):
    def test_genesis(self):
        t = Tangle()
        self.assertEqual(t.size, 1)
        self.assertTrue(t.genesis.is_genesis())

    def test_attach_and_tips(self):
        t = Tangle()
        tx = Transaction(issuer="n", parents=[t.genesis_id])
        self.assertTrue(t.attach(tx))
        self.assertIn(tx.tx_id, t.tips)
        self.assertNotIn(t.genesis_id, t.tips)

    def test_cumulative_weight(self):
        t = Tangle()
        tx1 = Transaction(issuer="n", parents=[t.genesis_id])
        tx2 = Transaction(issuer="n", parents=[t.genesis_id])
        t.attach(tx1)
        t.attach(tx2)
        self.assertEqual(t.genesis.cumulative_weight, 3)
        tx3 = Transaction(issuer="n", parents=[tx1.tx_id, tx2.tx_id])
        t.attach(tx3)
        self.assertEqual(t.genesis.cumulative_weight, 4)

    def test_duplicate_rejected(self):
        t = Tangle()
        tx = Transaction(issuer="n", parents=[t.genesis_id])
        self.assertTrue(t.attach(tx))
        self.assertFalse(t.attach(tx))

    def test_missing_parent_rejected(self):
        t = Tangle()
        tx = Transaction(issuer="n", parents=["nope"])
        self.assertFalse(t.attach(tx))


class TestSelectors(unittest.TestCase):
    def _make_tangle(self):
        t = Tangle()
        tx1 = Transaction(tx_id="aaa", issuer="n", parents=[t.genesis_id])
        tx2 = Transaction(tx_id="bbb", issuer="n", parents=[t.genesis_id])
        t.attach(tx1)
        t.attach(tx2)
        tx3 = Transaction(tx_id="ccc", issuer="n", parents=["aaa", "bbb"])
        t.attach(tx3)
        return t

    def test_random(self):
        t = self._make_tangle()
        s = RandomSelector(seed=42)
        tips = s.select(t, 2)
        self.assertEqual(len(tips), 2)

    def test_mcmc(self):
        t = self._make_tangle()
        s = MCMCSelector(alpha=0.01, seed=42)
        tips = s.select(t, 2)
        self.assertEqual(len(tips), 2)

    def test_hybrid(self):
        t = self._make_tangle()
        s = HybridSelector(seed=42)
        tips = s.select(t, 2)
        self.assertEqual(len(tips), 2)


class TestValidation(unittest.TestCase):
    def test_consistent(self):
        t = Tangle()
        tx1 = Transaction(issuer="n", parents=[t.genesis_id])
        t.attach(tx1)
        self.assertTrue(tips_consistent(t, [tx1.tx_id]))


if __name__ == "__main__":
    unittest.main()
