"""
Simulated Proof of Work.

In the real IOTA protocol, PoW prevents spam by requiring computational effort
before a transaction can be attached to the Tangle.  The PoW introduces a
fixed delay *h* time-steps (Ferraro et al. §II: "the PoW for the approval
procedure of a tip takes h time steps to complete").

In our simulation we model this as an async delay rather than actual hashing,
but we also provide an optional lightweight hash-based PoW for realism.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from .transaction import Transaction, TransactionStatus


class ProofOfWork:
    """
    Configurable PoW simulator.

    Parameters
    ----------
    h : float
        Simulated PoW delay in seconds.  Maps to the *h* parameter from
        Ferraro et al.  During this time the transaction sits in
        PENDING_POW status and its approved tips remain "pending tips"
        that are visible but not yet free.
    difficulty : int
        Number of leading hex zeros required (0 = no real hashing, pure delay).
    """

    def __init__(self, h: float = 1.0, difficulty: int = 0) -> None:
        self.h = h
        self.difficulty = difficulty

    async def perform(self, tx: Transaction) -> Transaction:
        """
        Execute the simulated PoW on *tx*.

        1. Mark the transaction as PENDING_POW.
        2. Sleep for *h* seconds  (simulating computational work).
        3. Optionally find a nonce that satisfies the difficulty target.
        4. Mark PENDING_ATTACH and record the completion time.
        """
        tx.status = TransactionStatus.PENDING_POW

        # ── Simulated delay ─────────────────────────────────────────────
        await asyncio.sleep(self.h)

        # ── Optional lightweight hash puzzle ────────────────────────────
        if self.difficulty > 0:
            prefix = "0" * self.difficulty
            base = f"{tx.tx_id}{tx.timestamp}"
            nonce = 0
            while True:
                candidate = hashlib.sha256(f"{base}{nonce}".encode()).hexdigest()
                if candidate.startswith(prefix):
                    tx.nonce = nonce
                    break
                nonce += 1

        tx.pow_complete_time = time.time()
        tx.status = TransactionStatus.PENDING_ATTACH
        return tx
