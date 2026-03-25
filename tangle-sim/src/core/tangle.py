"""
Tangle — the core DAG data structure.

The Tangle is a DAG where each vertex is a transaction and directed edges
represent approvals (child → parent).  The genesis transaction is the root
with no parents; every other transaction approves exactly m parents.

Key concepts from the papers
----------------------------
* **Tips** – transactions with no approvers yet (leaf vertices).
* **Cumulative weight** – the number of direct + indirect approvers of a
  transaction, plus itself  (Živić et al. §II; Ferraro et al. §II).
* **Pending tips** – tips whose PoW is still in progress (within the delay
  window h).  They are visible but not yet "free" to be selected.
* **Free tips** – tips whose PoW is complete and that have not been
  approved by any subsequent transaction (Ferraro et al. §IV eq. 3-4).

This module is intentionally *single-threaded* – each distributed node
holds its own Tangle instance and mutates it only on its event loop.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Iterable, Optional

from .transaction import Transaction, TransactionStatus

logger = logging.getLogger(__name__)


class Tangle:
    """
    In-memory DAG representing one node's local view of the Tangle.

    Internal storage
    ----------------
    _txs : dict[str, Transaction]
        tx_id  →  Transaction object.
    _children : dict[str, set[str]]
        tx_id  →  set of tx_ids that *approve* (point to) this transaction.
        i.e. reverse adjacency — who approves me.
    _tips : set[str]
        IDs of current tips (no approvers yet).
    """

    def __init__(self, genesis: Optional[Transaction] = None) -> None:
        self._txs: dict[str, Transaction] = {}
        self._children: dict[str, set[str]] = defaultdict(set)
        self._tips: set[str] = set()
        self._genesis_id: str = ""

        if genesis is None:
            genesis = Transaction(
                issuer_id="GENESIS",
                parent_ids=[],
                value=0.0,
                timestamp=time.time(),
                status=TransactionStatus.CONFIRMED,
                nonce=0,
            )
            genesis.pow_complete_time = genesis.timestamp
        self._add_genesis(genesis)

    # ── Genesis ─────────────────────────────────────────────────────────
    def _add_genesis(self, genesis: Transaction) -> None:
        genesis.status = TransactionStatus.CONFIRMED
        genesis.cumulative_weight = 1
        self._txs[genesis.tx_id] = genesis
        self._tips.add(genesis.tx_id)
        self._genesis_id = genesis.tx_id

    @property
    def genesis_id(self) -> str:
        return self._genesis_id

    @property
    def genesis(self) -> Transaction:
        return self._txs[self._genesis_id]

    # ── Read accessors ──────────────────────────────────────────────────
    @property
    def size(self) -> int:
        return len(self._txs)

    @property
    def tips(self) -> set[str]:
        """All current tips (including pending-PoW ones)."""
        return set(self._tips)

    @property
    def free_tips(self) -> set[str]:
        """Tips whose PoW has been completed (available for selection)."""
        return {
            tid for tid in self._tips
            if self._txs[tid].status in (
                TransactionStatus.ATTACHED,
                TransactionStatus.CONFIRMED,
            )
        }

    @property
    def pending_tips(self) -> set[str]:
        """Tips still waiting for PoW."""
        return {
            tid for tid in self._tips
            if self._txs[tid].status == TransactionStatus.PENDING_POW
        }

    def has_tx(self, tx_id: str) -> bool:
        return tx_id in self._txs

    def get_tx(self, tx_id: str) -> Optional[Transaction]:
        return self._txs.get(tx_id)

    def get_all_txs(self) -> dict[str, Transaction]:
        return dict(self._txs)

    def get_children(self, tx_id: str) -> set[str]:
        """Return the set of transactions that approve tx_id."""
        return set(self._children.get(tx_id, set()))

    def get_parents(self, tx_id: str) -> list[str]:
        tx = self._txs.get(tx_id)
        return list(tx.parent_ids) if tx else []

    # ── Mutation ────────────────────────────────────────────────────────
    def attach_transaction(self, tx: Transaction) -> bool:
        """
        Attach a transaction to the local tangle.

        Returns True if successfully attached, False if already present
        or if any parent is missing.
        """
        if tx.tx_id in self._txs:
            return False

        # Validate that all parents exist in our local tangle
        for pid in tx.parent_ids:
            if pid not in self._txs:
                logger.warning(
                    "Cannot attach %s: missing parent %s", tx.tx_id[:8], pid[:8]
                )
                return False

        # Insert
        self._txs[tx.tx_id] = tx
        tx.status = TransactionStatus.ATTACHED

        # Update parent→child reverse index & tip set
        for pid in tx.parent_ids:
            self._children[pid].add(tx.tx_id)
            # Parent is no longer a tip (it now has at least one approver)
            self._tips.discard(pid)

        # The new transaction is itself a tip
        self._tips.add(tx.tx_id)

        # Propagate cumulative weight updates
        self._update_cumulative_weights(tx.tx_id)

        return True

    # ── Cumulative weight ───────────────────────────────────────────────
    def _update_cumulative_weights(self, new_tx_id: str) -> None:
        """
        Recompute cumulative weight for all ancestors of `new_tx_id`.

        Cumulative weight of a transaction = 1 (own weight) + count of all
        transactions that directly or indirectly approve it.

        We do a BFS *backwards* from the new transaction through parents,
        incrementing each ancestor's cumulative weight by 1.
        """
        visited: set[str] = set()
        queue = deque(self._txs[new_tx_id].parent_ids)
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            tx = self._txs.get(current)
            if tx is None:
                continue
            tx.cumulative_weight += 1
            for pid in tx.parent_ids:
                if pid not in visited:
                    queue.append(pid)

    def recompute_all_weights(self) -> None:
        """Full recomputation — expensive but accurate.  Use sparingly."""
        for tx in self._txs.values():
            tx.cumulative_weight = 1

        # Topological order (BFS from genesis)
        order: list[str] = []
        in_degree: dict[str, int] = defaultdict(int)
        for tx in self._txs.values():
            for pid in tx.parent_ids:
                in_degree[pid]  # ensure key exists
            in_degree.setdefault(tx.tx_id, 0)

        # Count reverse in-degree (how many children point to me → already counted)
        # Actually, we want topological sort by *approval time* (newest first)
        # and propagate weights downwards.
        for tx in self._txs.values():
            approver_count = len(self._children.get(tx.tx_id, set()))
            # cumulative weight = 1 + number of ALL direct & indirect approvers
            # Use DFS from each tx upward through children
        for tx in self._txs.values():
            tx.cumulative_weight = self._count_approvers(tx.tx_id)

    def _count_approvers(self, tx_id: str) -> int:
        """Count all direct + indirect approvers of tx_id (including itself)."""
        visited: set[str] = set()
        stack = [tx_id]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for child_id in self._children.get(current, set()):
                if child_id not in visited:
                    stack.append(child_id)
        return len(visited)  # includes tx_id itself

    def get_cumulative_weight(self, tx_id: str) -> int:
        tx = self._txs.get(tx_id)
        return tx.cumulative_weight if tx else 0

    # ── Ancestry / Consistency ──────────────────────────────────────────
    def get_ancestors(self, tx_id: str) -> set[str]:
        """Return all transactions directly or indirectly approved by tx_id."""
        visited: set[str] = set()
        stack = list(self._txs[tx_id].parent_ids) if tx_id in self._txs else []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            tx = self._txs.get(current)
            if tx:
                stack.extend(tx.parent_ids)
        return visited

    def get_approval_path(self, tx_id: str) -> set[str]:
        """
        Full validation path: tx_id + all its ancestors.
        Used for conflict detection during tip selection.
        """
        path = {tx_id}
        path |= self.get_ancestors(tx_id)
        return path

    # ── Graph export (for visualization / NetworkX) ─────────────────────
    def to_edge_list(self) -> list[tuple[str, str]]:
        """Return edges as (child, parent) tuples."""
        edges = []
        for tx in self._txs.values():
            for pid in tx.parent_ids:
                edges.append((tx.tx_id, pid))
        return edges

    def to_networkx(self):
        """Export as a NetworkX DiGraph (requires networkx)."""
        try:
            import networkx as nx
        except ImportError:
            raise ImportError(
                "networkx is required for to_networkx(). "
                "Install it with: pip install networkx"
            )

        G = nx.DiGraph()
        for tx in self._txs.values():
            G.add_node(
                tx.tx_id,
                label=tx.tx_id[:8],
                issuer=tx.issuer_id,
                cw=tx.cumulative_weight,
                timestamp=tx.timestamp,
                is_tip=tx.tx_id in self._tips,
                status=tx.status.name,
            )
        for child_id, tx in self._txs.items():
            for pid in tx.parent_ids:
                G.add_edge(child_id, pid)
        return G

    def to_node_data(self) -> list[dict]:
        """Export node data as plain dicts (no external deps)."""
        return [
            {
                "tx_id": tx.tx_id,
                "label": tx.tx_id[:8],
                "issuer": tx.issuer_id,
                "cw": tx.cumulative_weight,
                "timestamp": tx.timestamp,
                "is_tip": tx.tx_id in self._tips,
                "status": tx.status.name,
                "parent_ids": tx.parent_ids,
            }
            for tx in self._txs.values()
        ]

    # ── Summary ─────────────────────────────────────────────────────────
    def summary(self) -> dict:
        return {
            "size": self.size,
            "tips": len(self._tips),
            "free_tips": len(self.free_tips),
            "pending_tips": len(self.pending_tips),
            "genesis_cw": self.genesis.cumulative_weight,
        }

    def __repr__(self) -> str:
        return f"Tangle(size={self.size}, tips={len(self._tips)})"
