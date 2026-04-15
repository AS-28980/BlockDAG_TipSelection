"""
Tangle — in-memory DAG held by a single OS process.

Each node process creates exactly one Tangle instance.  There is NO
shared state between processes — convergence happens only through TCP
gossip, exactly as described in Živić et al. §II:

    "the versions on different nodes are not necessarily exactly the same:
     different nodes may see different sets of transactions at any moment."
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Optional

from .transaction import Transaction, TxStatus

log = logging.getLogger(__name__)


class Tangle:
    def __init__(self, genesis: Optional[Transaction] = None) -> None:
        self._txs: dict[str, Transaction] = {}
        self._children: dict[str, set[str]] = defaultdict(set)
        self._tips: set[str] = set()
        self._genesis_id: str = ""

        if genesis is None:
            import time
            genesis = Transaction(
                issuer="GENESIS", parents=[], value=0.0,
                timestamp=time.time(), status=TxStatus.CONFIRMED,
            )
        self._put_genesis(genesis)

    def _put_genesis(self, g: Transaction) -> None:
        g.status = TxStatus.CONFIRMED
        g.cumulative_weight = 1
        self._txs[g.tx_id] = g
        self._tips.add(g.tx_id)
        self._genesis_id = g.tx_id

    # -- read --------------------------------------------------------------
    @property
    def genesis_id(self) -> str:
        return self._genesis_id

    @property
    def genesis(self) -> Transaction:
        return self._txs[self._genesis_id]

    @property
    def size(self) -> int:
        return len(self._txs)

    @property
    def tips(self) -> set[str]:
        return set(self._tips)

    @property
    def free_tips(self) -> set[str]:
        return {
            t for t in self._tips
            if self._txs[t].status in (TxStatus.ATTACHED, TxStatus.CONFIRMED)
        }

    def has(self, tx_id: str) -> bool:
        return tx_id in self._txs

    def get(self, tx_id: str) -> Optional[Transaction]:
        return self._txs.get(tx_id)

    def children_of(self, tx_id: str) -> set[str]:
        return set(self._children.get(tx_id, set()))

    def weight(self, tx_id: str) -> int:
        tx = self._txs.get(tx_id)
        return tx.cumulative_weight if tx else 0

    # -- mutate ------------------------------------------------------------
    def attach(self, tx: Transaction) -> bool:
        if tx.tx_id in self._txs:
            return False
        for pid in tx.parents:
            if pid not in self._txs:
                return False
        self._txs[tx.tx_id] = tx
        tx.status = TxStatus.ATTACHED
        for pid in tx.parents:
            self._children[pid].add(tx.tx_id)
            self._tips.discard(pid)
        self._tips.add(tx.tx_id)
        self._propagate_weight(tx.tx_id)
        return True

    def _propagate_weight(self, new_id: str) -> None:
        visited: set[str] = set()
        q = deque(self._txs[new_id].parents)
        while q:
            cur = q.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            tx = self._txs.get(cur)
            if tx is None:
                continue
            tx.cumulative_weight += 1
            for pid in tx.parents:
                if pid not in visited:
                    q.append(pid)

    # -- ancestry (for validation) -----------------------------------------
    def approval_path(self, tx_id: str) -> set[str]:
        path = {tx_id}
        stack = list(self._txs[tx_id].parents) if tx_id in self._txs else []
        while stack:
            cur = stack.pop()
            if cur in path:
                continue
            path.add(cur)
            tx = self._txs.get(cur)
            if tx:
                stack.extend(tx.parents)
        return path

    # -- bulk export (for sync / viz) --------------------------------------
    def all_tx_dicts(self) -> list[dict]:
        return sorted(
            [tx.to_dict() for tx in self._txs.values()],
            key=lambda d: d["timestamp"],
        )

    def edge_list(self) -> list[tuple[str, str]]:
        out = []
        for tx in self._txs.values():
            for pid in tx.parents:
                out.append((tx.tx_id, pid))
        return out

    def summary(self) -> dict:
        return {
            "size": self.size,
            "tips": len(self._tips),
            "free_tips": len(self.free_tips),
            "genesis_cw": self.genesis.cumulative_weight,
        }
