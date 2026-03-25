"""Tests for the core Tangle DAG data structure."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from src.core.transaction import Transaction, TransactionStatus
from src.core.tangle import Tangle


class TestTangle(unittest.TestCase):

    def test_genesis_creation(self):
        tangle = Tangle()
        self.assertEqual(tangle.size, 1)
        self.assertEqual(len(tangle.tips), 1)
        self.assertTrue(tangle.genesis.is_genesis())
        self.assertEqual(tangle.genesis.cumulative_weight, 1)

    def test_attach_transaction(self):
        tangle = Tangle()
        gid = tangle.genesis_id

        tx = Transaction(issuer_id="node_0", parent_ids=[gid])
        result = tangle.attach_transaction(tx)

        self.assertTrue(result)
        self.assertEqual(tangle.size, 2)
        # Genesis should no longer be a tip
        self.assertNotIn(gid, tangle.tips)
        # New tx should be a tip
        self.assertIn(tx.tx_id, tangle.tips)

    def test_cumulative_weight_update(self):
        tangle = Tangle()
        gid = tangle.genesis_id

        # tx1 approves genesis
        tx1 = Transaction(issuer_id="n", parent_ids=[gid])
        tangle.attach_transaction(tx1)

        # tx2 approves genesis
        tx2 = Transaction(issuer_id="n", parent_ids=[gid])
        tangle.attach_transaction(tx2)

        # Genesis now has 3 approvers (itself + tx1 + tx2)
        self.assertEqual(tangle.genesis.cumulative_weight, 3)

        # tx3 approves tx1 and tx2
        tx3 = Transaction(issuer_id="n", parent_ids=[tx1.tx_id, tx2.tx_id])
        tangle.attach_transaction(tx3)

        # Genesis: itself + tx1 + tx2 + tx3 = 4
        self.assertEqual(tangle.genesis.cumulative_weight, 4)
        # tx1: itself + tx3 = 2
        self.assertEqual(tangle.get_tx(tx1.tx_id).cumulative_weight, 2)

    def test_tips_management(self):
        tangle = Tangle()
        gid = tangle.genesis_id

        tx1 = Transaction(issuer_id="n", parent_ids=[gid])
        tx2 = Transaction(issuer_id="n", parent_ids=[gid])
        tangle.attach_transaction(tx1)
        tangle.attach_transaction(tx2)

        # Both tx1 and tx2 are tips, genesis is not
        self.assertEqual(len(tangle.tips), 2)
        self.assertIn(tx1.tx_id, tangle.tips)
        self.assertIn(tx2.tx_id, tangle.tips)
        self.assertNotIn(gid, tangle.tips)

    def test_duplicate_attach_rejected(self):
        tangle = Tangle()
        tx = Transaction(issuer_id="n", parent_ids=[tangle.genesis_id])
        self.assertTrue(tangle.attach_transaction(tx))
        self.assertFalse(tangle.attach_transaction(tx))  # duplicate

    def test_missing_parent_rejected(self):
        tangle = Tangle()
        tx = Transaction(issuer_id="n", parent_ids=["nonexistent_id"])
        self.assertFalse(tangle.attach_transaction(tx))

    def test_ancestors(self):
        tangle = Tangle()
        gid = tangle.genesis_id

        tx1 = Transaction(issuer_id="n", parent_ids=[gid])
        tangle.attach_transaction(tx1)
        tx2 = Transaction(issuer_id="n", parent_ids=[tx1.tx_id])
        tangle.attach_transaction(tx2)

        ancestors = tangle.get_ancestors(tx2.tx_id)
        self.assertIn(tx1.tx_id, ancestors)
        self.assertIn(gid, ancestors)

    def test_edge_list(self):
        tangle = Tangle()
        gid = tangle.genesis_id
        tx1 = Transaction(issuer_id="n", parent_ids=[gid])
        tangle.attach_transaction(tx1)

        edges = tangle.to_edge_list()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0], (tx1.tx_id, gid))


if __name__ == "__main__":
    unittest.main()
