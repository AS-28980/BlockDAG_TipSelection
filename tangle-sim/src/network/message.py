"""
Message types exchanged between nodes in the Tangle network.

Nodes communicate via a gossip protocol: when a node creates or receives
a new transaction, it forwards it to its neighbours.  This module defines
the envelope that wraps every inter-node message.

From Živić et al. §II: "IOTA network is also a P2P network of nodes …
which both validate and issue transactions, since before issuing its own
transaction a node must validate two earlier transactions issued by other
nodes.  Furthermore, each node is supported to remain active, i.e. to
propagate new transactions from other nodes through the network."
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class MessageType(Enum):
    """All inter-node message types."""
    TX_BROADCAST = auto()       # A new transaction to be gossiped
    TX_REQUEST = auto()         # Request a specific transaction by ID
    TX_RESPONSE = auto()        # Response containing requested transaction
    TIP_REQUEST = auto()        # Ask a peer for its current tip set
    TIP_RESPONSE = auto()       # Current tip set
    HEARTBEAT = auto()          # Keepalive / peer discovery
    SYNC_REQUEST = auto()       # Request full tangle state (bootstrap)
    SYNC_RESPONSE = auto()      # Full tangle snapshot


@dataclass
class Message:
    """
    Network message envelope.

    Attributes
    ----------
    msg_type : MessageType
    sender_id : str       Node ID of the sender.
    receiver_id : str     Target node (or "*" for broadcast).
    payload : dict        JSON-serialisable body.
    msg_id : str          Unique message identifier.
    timestamp : float     When the message was created.
    ttl : int             Gossip hop limit (decremented at each relay).
    """
    msg_type: MessageType
    sender_id: str
    receiver_id: str = "*"
    payload: dict = field(default_factory=dict)
    msg_id: str = field(default="")
    timestamp: float = field(default_factory=time.time)
    ttl: int = 5

    def __post_init__(self) -> None:
        if not self.msg_id:
            self.msg_id = uuid.uuid4().hex[:12]

    # ── Serialisation for ZMQ transport ─────────────────────────────────
    def serialise(self) -> bytes:
        return json.dumps({
            "msg_type": self.msg_type.name,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "payload": self.payload,
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
        }).encode("utf-8")

    @classmethod
    def deserialise(cls, raw: bytes) -> Message:
        d = json.loads(raw.decode("utf-8"))
        return cls(
            msg_type=MessageType[d["msg_type"]],
            sender_id=d["sender_id"],
            receiver_id=d.get("receiver_id", "*"),
            payload=d.get("payload", {}),
            msg_id=d.get("msg_id", ""),
            timestamp=d.get("timestamp", time.time()),
            ttl=d.get("ttl", 5),
        )

    def __repr__(self) -> str:
        return (
            f"Msg({self.msg_type.name} {self.sender_id}→{self.receiver_id} "
            f"id={self.msg_id[:8]})"
        )
