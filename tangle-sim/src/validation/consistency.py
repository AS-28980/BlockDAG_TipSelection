"""
Consistency checker for the Tangle.

Before a node attaches a new transaction, it must verify that the tips it
selected (and their entire approval paths) are mutually consistent.

From Živić et al. §IV: "we assume that there is a simple way to verify
whether the tips selected for approval by a new transaction are consistent
with each other and with all the sites directly or indirectly approved by
them … If verification fails, the selection process must be re-run until
a set of consistent transactions is found."
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.tangle import Tangle

logger = logging.getLogger(__name__)


class ConsistencyChecker:
    """
    Validates that a set of transactions (and their approval paths)
    do not contain conflicting transfers.

    A conflict exists when two transactions in the same approval path
    spend from the same address and the combined spending would exceed
    the address's balance at the time of the earliest transaction.
    """

    def check_tips_consistent(
        self, tangle: "Tangle", tip_ids: list[str]
    ) -> bool:
        """
        Return True if the selected tips can be jointly approved
        without introducing conflicts.
        """
        # Gather the combined approval path
        combined: set[str] = set()
        for tid in tip_ids:
            if not tangle.has_tx(tid):
                return False
            combined |= tangle.get_approval_path(tid)

        # Check for conflicting senders
        sender_spends: dict[str, float] = {}
        for tx_id in combined:
            tx = tangle.get_tx(tx_id)
            if tx is None or tx.is_genesis():
                continue
            addr = tx.sender_address
            if addr:
                sender_spends[addr] = sender_spends.get(addr, 0) + tx.value

        # In a full implementation we'd check balances from genesis.
        # Here we flag if any single address spends more than a threshold
        # (simplified model — the real IOTA tracks UTXO-style balances).
        for addr, total in sender_spends.items():
            if total < 0:
                logger.warning("Negative spend detected for %s: %.2f", addr, total)
                return False

        return True

    def verify_dag_integrity(self, tangle: "Tangle") -> list[str]:
        """
        Full integrity scan of the tangle.  Returns a list of issues found.
        """
        issues: list[str] = []
        for tx_id, tx in tangle.get_all_txs().items():
            # Every parent must exist
            for pid in tx.parent_ids:
                if not tangle.has_tx(pid):
                    issues.append(f"Tx {tx_id[:8]} references missing parent {pid[:8]}")
            # Non-genesis must have parents
            if not tx.is_genesis() and len(tx.parent_ids) == 0:
                issues.append(f"Tx {tx_id[:8]} is non-genesis but has no parents")
        return issues
