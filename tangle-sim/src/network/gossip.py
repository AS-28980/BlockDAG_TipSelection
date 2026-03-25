"""
Gossip protocol for transaction propagation.

When a node creates or receives a new transaction it gossips it to a
subset of its peers.  The TTL field prevents infinite re-broadcast.

From Živić et al. §II: "each node is supported to remain active, i.e.
to propagate new transactions from other nodes through the network,
although a node perhaps has no more new transactions to issue."

The gossip strategy is configurable:
    - **flood**: forward to ALL neighbours (simplest, most bandwidth)
    - **random_k**: forward to k random neighbours
    - **sqrt_n**: forward to √n neighbours (good balance)
"""

from __future__ import annotations

import math
import random
from typing import Optional

from .message import Message, MessageType


class GossipProtocol:
    """
    Manages which neighbours a node should forward a message to.

    Parameters
    ----------
    strategy : str
        "flood", "random_k", or "sqrt_n".
    k : int
        Number of peers for "random_k".
    seed : int | None
        RNG seed for reproducibility.
    """

    def __init__(
        self,
        strategy: str = "flood",
        k: int = 3,
        seed: Optional[int] = None,
    ) -> None:
        self.strategy = strategy
        self.k = k
        self._rng = random.Random(seed)
        self._seen: set[str] = set()  # msg_ids already processed

    def should_process(self, msg: Message) -> bool:
        """Return True if we haven't seen this message before."""
        if msg.msg_id in self._seen:
            return False
        self._seen.add(msg.msg_id)
        return True

    def select_peers(self, all_peers: list[str], exclude: str = "") -> list[str]:
        """
        Decide which peers to forward a message to.

        Parameters
        ----------
        all_peers : list of neighbour node IDs
        exclude : node ID to exclude (usually the sender)
        """
        candidates = [p for p in all_peers if p != exclude]
        if not candidates:
            return []

        if self.strategy == "flood":
            return candidates
        elif self.strategy == "random_k":
            return self._rng.sample(candidates, min(self.k, len(candidates)))
        elif self.strategy == "sqrt_n":
            n = max(1, int(math.sqrt(len(candidates))))
            return self._rng.sample(candidates, min(n, len(candidates)))
        else:
            return candidates

    def prepare_forward(
        self, original: Message, forwarder_id: str
    ) -> Message | None:
        """
        Prepare a message for re-broadcast.
        Returns None if TTL is exhausted.
        """
        if original.ttl <= 1:
            return None
        return Message(
            msg_type=original.msg_type,
            sender_id=forwarder_id,
            receiver_id="*",
            payload=original.payload,
            msg_id=original.msg_id,   # same ID to prevent loops
            timestamp=original.timestamp,
            ttl=original.ttl - 1,
        )

    def reset(self) -> None:
        """Clear the seen-set (for long-running simulations)."""
        self._seen.clear()
