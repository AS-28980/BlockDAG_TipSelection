"""
Simulated Proof of Work — async delay of h seconds.
Ferraro et al. parameter h: "the PoW for the approval procedure of a
tip takes h time steps to complete."
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from .transaction import Transaction, TxStatus


class PoW:
    def __init__(self, h: float = 1.0, difficulty: int = 0):
        self.h = h
        self.difficulty = difficulty

    async def run(self, tx: Transaction) -> Transaction:
        tx.status = TxStatus.PENDING_POW
        await asyncio.sleep(self.h)
        if self.difficulty > 0:
            prefix = "0" * self.difficulty
            base = f"{tx.tx_id}{tx.timestamp}"
            nonce = 0
            while True:
                h = hashlib.sha256(f"{base}{nonce}".encode()).hexdigest()
                if h.startswith(prefix):
                    tx.nonce = nonce
                    break
                nonce += 1
        tx.status = TxStatus.ATTACHED
        return tx
