"""
Consistency check and double-spend detection.

Živić et al. §IV: "when a node selects two tips … it first has to
validate them: it checks the tip's signature and makes sure that the
tip is not in conflict with any of the transactions in its validation
path."
"""

from __future__ import annotations

from collections import defaultdict

from .tangle import Tangle


def tips_consistent(tangle: Tangle, tip_ids: list[str]) -> bool:
    """Return True if selected tips can be jointly approved."""
    combined: set[str] = set()
    for tid in tip_ids:
        if not tangle.has(tid):
            return False
        combined |= tangle.approval_path(tid)

    # Check no sender double-spends within this path
    spending: dict[str, float] = defaultdict(float)
    for tx_id in combined:
        tx = tangle.get(tx_id)
        if tx is None or tx.is_genesis():
            continue
        if tx.sender_addr and tx.value > 0:
            spending[tx.sender_addr] += tx.value

    # Flag clearly excessive spending (simplified model)
    for addr, total in spending.items():
        if total > 1_000_000:
            return False
    return True
