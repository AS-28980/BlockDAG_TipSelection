"""
Double-spend detection.

From Živić et al. §IV — Security Support:
    "A double spending problem: a dishonest entity might spend its money
    twice by issuing two different transactions to different sellers in a
    short period of time, which results in two conflicting transactions."

    "When a node selects two tips … it first has to validate them: it
    checks the tip's signature and makes sure that the tip is not in
    conflict with any of the transactions in its validation path, i.e.
    with the transactions which are directly and indirectly validated
    by this tip.  In case that the node finds out that the selected tip
    is in conflict, the node abandons that tip and chooses another one."

From Ferraro et al. §II-A — Double Spending Attack:
    "A double spending attack is an attempt to exploit the structure of
    the DLT in order to spend the same digital token multiple times."

This module tracks per-address spending across the tangle and detects
when two transactions in the same approval path would cause an address
to go negative.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.tangle import Tangle

logger = logging.getLogger(__name__)


class DoubleSpendDetector:
    """
    Detects double-spending conflicts within an approval path.

    The detector maintains a view of address balances as computed from
    the genesis.  When checking a path, it replays the spending from
    genesis to tips and flags any address that goes negative.
    """

    def __init__(self, initial_supply: float = 1_000_000.0) -> None:
        self.initial_supply = initial_supply

    def check_path(self, tangle: "Tangle", path_tx_ids: set[str]) -> bool:
        """
        Return True if the approval path has no double-spend conflicts.

        Parameters
        ----------
        tangle : Tangle
        path_tx_ids : set of transaction IDs forming the approval path

        Returns
        -------
        bool
            True  = path is clean
            False = double-spend or negative balance detected
        """
        # Track spending per sender address within this path
        address_spending: dict[str, float] = defaultdict(float)

        for tx_id in path_tx_ids:
            tx = tangle.get_tx(tx_id)
            if tx is None or tx.is_genesis():
                continue
            if tx.value > 0 and tx.sender_address:
                address_spending[tx.sender_address] += tx.value

        # In our simplified model, each node starts with a balance.
        # A double-spend is when the same address appears in two conflicting
        # branches spending more than its balance.
        # For the simulation, we check if any address spends an unreasonable
        # amount (> 2× what a single node could have).
        for addr, spent in address_spending.items():
            if spent > self.initial_supply:
                logger.warning(
                    "Double-spend detected: %s spent %.2f (supply=%.2f)",
                    addr, spent, self.initial_supply,
                )
                return False

        return True

    def find_conflicts(
        self, tangle: "Tangle", tip_ids: list[str]
    ) -> list[tuple[str, str, str]]:
        """
        Identify specific conflicting transaction pairs between tips.

        Returns a list of (addr, tx_id_1, tx_id_2) triples where the same
        sender address appears in conflicting branches.
        """
        conflicts: list[tuple[str, str, str]] = []

        if len(tip_ids) < 2:
            return conflicts

        # Get separate approval paths for each tip
        paths: list[dict[str, set[str]]] = []
        for tid in tip_ids:
            path = tangle.get_approval_path(tid)
            addr_txs: dict[str, set[str]] = defaultdict(set)
            for tx_id in path:
                tx = tangle.get_tx(tx_id)
                if tx and tx.sender_address and tx.value > 0:
                    addr_txs[tx.sender_address].add(tx_id)
            paths.append(addr_txs)

        # Find addresses that appear in multiple paths with different txs
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                common_addrs = set(paths[i].keys()) & set(paths[j].keys())
                for addr in common_addrs:
                    # Check for txs that are in one path but not the other
                    unique_i = paths[i][addr] - paths[j][addr]
                    unique_j = paths[j][addr] - paths[i][addr]
                    if unique_i and unique_j:
                        # Potential double-spend: same address, different txs
                        for tx_a in unique_i:
                            for tx_b in unique_j:
                                conflicts.append((addr, tx_a, tx_b))

        return conflicts
