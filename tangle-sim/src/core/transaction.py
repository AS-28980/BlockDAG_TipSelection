"""
Transaction data structure for the Tangle DAG.

Each transaction (site/vertex) in the Tangle approves m parent transactions.
A transaction's cumulative weight is the total number of transactions that
directly or indirectly approve it (including itself).

Reference: Ferraro et al. §II — "each vertex or site represents a transaction ...
before being added to the tangle, a new transaction must first approve m
(normally two) transactions in the tangle."
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class TransactionStatus(Enum):
    """Lifecycle states of a transaction in the Tangle."""
    PENDING_POW = auto()      # Created, PoW not yet complete
    PENDING_ATTACH = auto()   # PoW done, waiting to be gossiped
    ATTACHED = auto()         # Attached to local tangle
    CONFIRMED = auto()        # Cumulative weight exceeds threshold


@dataclass
class Transaction:
    """
    A single transaction (vertex / site) in the Tangle DAG.

    Attributes
    ----------
    tx_id : str
        Unique identifier (simulated hash).
    issuer_id : str
        The node that created this transaction.
    parent_ids : list[str]
        IDs of the m approved parent transactions (edges point child -> parent).
    value : float
        Token value transferred (can be zero for data-only txs).
    sender_address : str
        Sender wallet address (simplified).
    receiver_address : str
        Receiver wallet address (simplified).
    timestamp : float
        Wall-clock time the transaction was created.
    pow_complete_time : float | None
        Time at which the simulated PoW finished.
    nonce : int
        Simulated proof-of-work nonce.
    status : TransactionStatus
        Current lifecycle state.
    cumulative_weight : int
        Number of transactions that directly or indirectly approve this one,
        plus one for itself.  Updated lazily by the Tangle.
    """

    issuer_id: str
    parent_ids: list[str]
    value: float = 0.0
    sender_address: str = ""
    receiver_address: str = ""
    timestamp: float = field(default_factory=time.time)
    pow_complete_time: Optional[float] = None
    nonce: int = 0
    status: TransactionStatus = TransactionStatus.PENDING_POW
    cumulative_weight: int = 1  # counts itself
    tx_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.tx_id:
            raw = f"{self.issuer_id}{self.parent_ids}{self.timestamp}{uuid.uuid4().hex}"
            self.tx_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Serialisation (for network transport) ───────────────────────────
    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "issuer_id": self.issuer_id,
            "parent_ids": self.parent_ids,
            "value": self.value,
            "sender_address": self.sender_address,
            "receiver_address": self.receiver_address,
            "timestamp": self.timestamp,
            "pow_complete_time": self.pow_complete_time,
            "nonce": self.nonce,
            "status": self.status.name,
            "cumulative_weight": self.cumulative_weight,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Transaction:
        tx = cls(
            tx_id=d["tx_id"],
            issuer_id=d["issuer_id"],
            parent_ids=d["parent_ids"],
            value=d.get("value", 0.0),
            sender_address=d.get("sender_address", ""),
            receiver_address=d.get("receiver_address", ""),
            timestamp=d["timestamp"],
            pow_complete_time=d.get("pow_complete_time"),
            nonce=d.get("nonce", 0),
            status=TransactionStatus[d.get("status", "ATTACHED")],
            cumulative_weight=d.get("cumulative_weight", 1),
        )
        return tx

    # ── Helpers ──────────────────────────────────────────────────────────
    @property
    def age(self) -> float:
        """Seconds since the transaction was created."""
        return time.time() - self.timestamp

    def is_genesis(self) -> bool:
        return len(self.parent_ids) == 0

    def __hash__(self) -> int:
        return hash(self.tx_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Transaction):
            return NotImplemented
        return self.tx_id == other.tx_id

    def __repr__(self) -> str:
        return (
            f"Tx({self.tx_id[:8]}… issuer={self.issuer_id} "
            f"parents={[p[:8] for p in self.parent_ids]} "
            f"cw={self.cumulative_weight} status={self.status.name})"
        )
