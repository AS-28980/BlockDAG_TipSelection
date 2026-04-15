"""
Transaction — the atomic unit of the Tangle.

Identical semantics to the tangle-sim version but fully self-contained
so each OS process can import it without cross-project dependencies.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class TxStatus(Enum):
    PENDING_POW = auto()
    ATTACHED = auto()
    CONFIRMED = auto()


@dataclass
class Transaction:
    issuer: str
    parents: list[str]
    value: float = 0.0
    sender_addr: str = ""
    receiver_addr: str = ""
    timestamp: float = field(default_factory=time.time)
    nonce: int = 0
    status: TxStatus = TxStatus.PENDING_POW
    cumulative_weight: int = 1
    tx_id: str = ""

    def __post_init__(self) -> None:
        if not self.tx_id:
            raw = f"{self.issuer}|{self.parents}|{self.timestamp}|{uuid.uuid4().hex}"
            self.tx_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    # -- wire format -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "issuer": self.issuer,
            "parents": self.parents,
            "value": self.value,
            "sender_addr": self.sender_addr,
            "receiver_addr": self.receiver_addr,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "status": self.status.name,
            "cumulative_weight": self.cumulative_weight,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            tx_id=d["tx_id"],
            issuer=d["issuer"],
            parents=d["parents"],
            value=d.get("value", 0.0),
            sender_addr=d.get("sender_addr", ""),
            receiver_addr=d.get("receiver_addr", ""),
            timestamp=d["timestamp"],
            nonce=d.get("nonce", 0),
            status=TxStatus[d.get("status", "ATTACHED")],
            cumulative_weight=d.get("cumulative_weight", 1),
        )

    def is_genesis(self) -> bool:
        return len(self.parents) == 0

    def __hash__(self) -> int:
        return hash(self.tx_id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Transaction) and self.tx_id == other.tx_id

    def __repr__(self) -> str:
        return f"Tx({self.tx_id[:8]} by={self.issuer} cw={self.cumulative_weight})"
