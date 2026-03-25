"""
Distributed Tangle Node.

Each node runs as an independent async task (conceptually a separate process)
with its own local copy of the Tangle.  Nodes:

    1. Periodically issue new transactions (at a Poisson rate λ).
    2. Select m=2 tips using a configurable tip selection algorithm.
    3. Perform simulated Proof-of-Work (delay h).
    4. Validate the selected tips for consistency / double-spending.
    5. Attach the new transaction to the local tangle.
    6. Gossip the new transaction to neighbours.
    7. Listen for incoming gossip and integrate received transactions.

This mirrors the lifecycle described in both papers:
    - Živić et al. §II, Fig. 4: "Sequence to issue a new transaction"
    - Ferraro et al. §II: "at every time step a random number of transactions
      arrive … and for each one of these transactions the tip selection
      algorithm is performed on the current tips set"

Each node's local tangle may diverge from other nodes' views because of
network delays — exactly as described in Živić et al. §II:
    "any other node at the moment of issuing its own transaction does not
     observe the actual state of a tangle, but the one from several moments ago."
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from typing import Callable, Optional

from src.core.transaction import Transaction, TransactionStatus
from src.core.tangle import Tangle
from src.core.pow import ProofOfWork
from src.consensus.tip_selection import TipSelector
from src.validation.consistency import ConsistencyChecker
from src.validation.double_spend import DoubleSpendDetector
from .message import Message, MessageType
from .transport import Transport
from .gossip import GossipProtocol

logger = logging.getLogger(__name__)


class TangleNode:
    """
    A single node in the distributed Tangle network.

    Parameters
    ----------
    node_id : str
        Unique identifier.
    transport : Transport
        Network transport (with latency).
    tip_selector : TipSelector
        Algorithm for choosing tips (RS, MCMC, or Hybrid).
    pow : ProofOfWork
        PoW simulator (delay h).
    tx_rate : float
        Mean transaction arrival rate λ (transactions per second).
        Transactions are issued at Poisson-distributed intervals.
    neighbours : list[str]
        IDs of directly connected peers.
    gossip : GossipProtocol
        Controls message forwarding strategy.
    wallet_balance : float
        Initial token balance for this node's address.
    m : int
        Number of parents each new transaction must approve.
    genesis : Transaction | None
        Shared genesis transaction (must be identical across nodes).
    """

    def __init__(
        self,
        node_id: str,
        transport: Transport,
        tip_selector: TipSelector,
        pow: ProofOfWork,
        tx_rate: float = 1.0,
        neighbours: list[str] | None = None,
        gossip: GossipProtocol | None = None,
        wallet_balance: float = 1000.0,
        m: int = 2,
        genesis: Transaction | None = None,
    ) -> None:
        self.node_id = node_id
        self.transport = transport
        self.tip_selector = tip_selector
        self.pow = pow
        self.tx_rate = tx_rate
        self.neighbours = neighbours or []
        self.gossip = gossip or GossipProtocol()
        self.wallet_balance = wallet_balance
        self.m = m

        # Local tangle — each node has its own view
        self.tangle = Tangle(genesis=genesis)

        # Double-spend & consistency
        self._consistency = ConsistencyChecker()
        self._double_spend = DoubleSpendDetector()

        # Internal state
        self._running = False
        self._rng = random.Random(hash(node_id))
        self._tx_count = 0  # transactions issued by this node

        # Metrics
        self.metrics: dict[str, list] = {
            "tip_counts": [],       # (time, count)
            "txs_issued": [],       # (time, tx_id)
            "txs_received": [],     # (time, tx_id, from)
            "rejected_txs": [],     # (time, tx_id, reason)
            "latencies": [],        # (time, latency_ms)
        }

        # Event hooks
        self._on_tx_attached: Optional[Callable] = None

    # ── Lifecycle ───────────────────────────────────────────────────────
    async def start(self, duration: float = 60.0) -> None:
        """Run the node for `duration` seconds."""
        self._running = True
        logger.info("[%s] Starting (λ=%.2f, algo=%s)", self.node_id, self.tx_rate, self.tip_selector.name)

        # Run issuer and listener concurrently
        await asyncio.gather(
            self._issuer_loop(duration),
            self._listener_loop(duration),
            self._metrics_loop(duration),
        )
        self._running = False
        logger.info("[%s] Stopped. Tangle: %s", self.node_id, self.tangle.summary())

    async def _issuer_loop(self, duration: float) -> None:
        """Issue transactions at Poisson-distributed intervals."""
        start = time.time()
        while time.time() - start < duration and self._running:
            # Poisson inter-arrival: Exponential(1/λ)
            if self.tx_rate > 0:
                interval = self._rng.expovariate(self.tx_rate)
            else:
                interval = duration  # no issuing
            await asyncio.sleep(interval)

            if time.time() - start >= duration:
                break

            await self._issue_transaction()

    async def _listener_loop(self, duration: float) -> None:
        """Listen for incoming messages from peers."""
        start = time.time()
        while time.time() - start < duration and self._running:
            try:
                msg = await asyncio.wait_for(self.transport.recv(), timeout=0.5)
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue

    async def _metrics_loop(self, duration: float) -> None:
        """Periodically record tip count."""
        start = time.time()
        while time.time() - start < duration and self._running:
            await asyncio.sleep(0.5)
            elapsed = time.time() - start
            self.metrics["tip_counts"].append((elapsed, len(self.tangle.tips)))

    # ── Transaction issuance ────────────────────────────────────────────
    async def _issue_transaction(self) -> None:
        """Full lifecycle: select tips → validate → PoW → attach → gossip."""
        # Step 1: Select m tips
        selected_tips = self.tip_selector.select_tips(self.tangle, self.m)

        # Step 2: Validate consistency of selected tips
        if not self._validate_tip_set(selected_tips):
            # Re-select (up to 3 retries)
            for _ in range(3):
                selected_tips = self.tip_selector.select_tips(self.tangle, self.m)
                if self._validate_tip_set(selected_tips):
                    break
            else:
                logger.debug("[%s] Could not find consistent tips, skipping", self.node_id)
                return

        # Step 3: Create the transaction
        self._tx_count += 1
        value = self._rng.uniform(0, 10)  # small random value transfer
        tx = Transaction(
            issuer_id=self.node_id,
            parent_ids=selected_tips,
            value=value,
            sender_address=f"addr_{self.node_id}",
            receiver_address=f"addr_peer_{self._rng.randint(0, 99)}",
            timestamp=time.time(),
        )

        # Step 4: Proof of Work (simulated delay h)
        tx = await self.pow.perform(tx)

        # Step 5: Attach to local tangle
        attached = self.tangle.attach_transaction(tx)
        if attached:
            self.metrics["txs_issued"].append((time.time(), tx.tx_id))
            logger.debug(
                "[%s] Issued tx %s approving %s",
                self.node_id, tx.tx_id[:8],
                [p[:8] for p in selected_tips],
            )

            # Step 6: Gossip to neighbours
            await self._broadcast_tx(tx)

            if self._on_tx_attached:
                self._on_tx_attached(tx)

    def _validate_tip_set(self, tip_ids: list[str]) -> bool:
        """
        Check that the selected tips are mutually consistent.

        From Živić et al. §IV: "when a node selects two tips … it first
        has to validate them: it checks the tip's signature and makes sure
        that the tip is not in conflict with any of the transactions in
        its validation path."
        """
        # Check tips exist
        for tid in tip_ids:
            if not self.tangle.has_tx(tid):
                return False

        # Check for double-spend conflicts in combined approval paths
        combined_path: set[str] = set()
        for tid in tip_ids:
            path = self.tangle.get_approval_path(tid)
            combined_path |= path

        return self._double_spend.check_path(self.tangle, combined_path)

    # ── Message handling ────────────────────────────────────────────────
    async def _handle_message(self, msg: Message) -> None:
        """Process an incoming network message."""
        if not self.gossip.should_process(msg):
            return  # Already seen

        if msg.msg_type == MessageType.TX_BROADCAST:
            await self._handle_tx_broadcast(msg)
        elif msg.msg_type == MessageType.TX_REQUEST:
            await self._handle_tx_request(msg)
        elif msg.msg_type == MessageType.TX_RESPONSE:
            await self._handle_tx_response(msg)
        elif msg.msg_type == MessageType.SYNC_REQUEST:
            await self._handle_sync_request(msg)
        elif msg.msg_type == MessageType.SYNC_RESPONSE:
            await self._handle_sync_response(msg)

    async def _handle_tx_broadcast(self, msg: Message) -> None:
        """Receive a gossiped transaction and attach it to local tangle."""
        tx_data = msg.payload.get("transaction")
        if not tx_data:
            return

        tx = Transaction.from_dict(tx_data)

        # Check if we already have it
        if self.tangle.has_tx(tx.tx_id):
            return

        # Check parents exist — if not, request them
        missing_parents = [
            pid for pid in tx.parent_ids if not self.tangle.has_tx(pid)
        ]
        if missing_parents:
            # Request missing parents from the sender
            for pid in missing_parents:
                req = Message(
                    msg_type=MessageType.TX_REQUEST,
                    sender_id=self.node_id,
                    receiver_id=msg.sender_id,
                    payload={"tx_id": pid},
                )
                await self.transport.send(req)
            # Buffer this tx and retry later (simplified: just try attaching)
            # In a full implementation we'd have a pending buffer
            # For now, skip if parents are missing
            logger.debug(
                "[%s] Missing parents for %s, dropping", self.node_id, tx.tx_id[:8]
            )
            self.metrics["rejected_txs"].append(
                (time.time(), tx.tx_id, "missing_parents")
            )
            return

        # Validate & attach
        attached = self.tangle.attach_transaction(tx)
        if attached:
            recv_latency = (time.time() - tx.timestamp) * 1000  # ms
            self.metrics["txs_received"].append(
                (time.time(), tx.tx_id, msg.sender_id)
            )
            self.metrics["latencies"].append((time.time(), recv_latency))

            # Forward to our peers (gossip)
            await self._forward_gossip(msg)

    async def _handle_tx_request(self, msg: Message) -> None:
        """Respond to a peer's request for a specific transaction."""
        tx_id = msg.payload.get("tx_id")
        if not tx_id:
            return
        tx = self.tangle.get_tx(tx_id)
        if tx:
            resp = Message(
                msg_type=MessageType.TX_RESPONSE,
                sender_id=self.node_id,
                receiver_id=msg.sender_id,
                payload={"transaction": tx.to_dict()},
            )
            await self.transport.send(resp)

    async def _handle_tx_response(self, msg: Message) -> None:
        """Receive a requested transaction."""
        tx_data = msg.payload.get("transaction")
        if tx_data:
            tx = Transaction.from_dict(tx_data)
            if not self.tangle.has_tx(tx.tx_id):
                self.tangle.attach_transaction(tx)

    async def _handle_sync_request(self, msg: Message) -> None:
        """Send our full tangle to a bootstrapping peer."""
        all_txs = {
            tid: tx.to_dict()
            for tid, tx in self.tangle.get_all_txs().items()
        }
        resp = Message(
            msg_type=MessageType.SYNC_RESPONSE,
            sender_id=self.node_id,
            receiver_id=msg.sender_id,
            payload={"transactions": all_txs},
        )
        await self.transport.send(resp)

    async def _handle_sync_response(self, msg: Message) -> None:
        """Integrate a full tangle snapshot from a peer."""
        txs_data = msg.payload.get("transactions", {})
        # Sort by timestamp to maintain causal order
        sorted_txs = sorted(txs_data.values(), key=lambda d: d["timestamp"])
        for tx_data in sorted_txs:
            tx = Transaction.from_dict(tx_data)
            if not self.tangle.has_tx(tx.tx_id):
                self.tangle.attach_transaction(tx)

    # ── Gossip helpers ──────────────────────────────────────────────────
    async def _broadcast_tx(self, tx: Transaction) -> None:
        """Gossip a new transaction to neighbours."""
        msg = Message(
            msg_type=MessageType.TX_BROADCAST,
            sender_id=self.node_id,
            receiver_id="*",
            payload={"transaction": tx.to_dict()},
        )
        self.gossip._seen.add(msg.msg_id)  # don't re-process our own

        peers = self.gossip.select_peers(self.neighbours)
        for peer_id in peers:
            forward = Message(
                msg_type=msg.msg_type,
                sender_id=self.node_id,
                receiver_id=peer_id,
                payload=msg.payload,
                msg_id=msg.msg_id,
                timestamp=msg.timestamp,
                ttl=msg.ttl,
            )
            await self.transport.send(forward)

    async def _forward_gossip(self, original: Message) -> None:
        """Re-broadcast a received message to our neighbours."""
        fwd = self.gossip.prepare_forward(original, self.node_id)
        if fwd is None:
            return
        peers = self.gossip.select_peers(self.neighbours, exclude=original.sender_id)
        for peer_id in peers:
            fwd_copy = Message(
                msg_type=fwd.msg_type,
                sender_id=self.node_id,
                receiver_id=peer_id,
                payload=fwd.payload,
                msg_id=fwd.msg_id,
                timestamp=fwd.timestamp,
                ttl=fwd.ttl,
            )
            await self.transport.send(fwd_copy)

    # ── Status ──────────────────────────────────────────────────────────
    def summary(self) -> dict:
        return {
            "node_id": self.node_id,
            "tangle": self.tangle.summary(),
            "txs_issued": self._tx_count,
            "algorithm": self.tip_selector.name,
            "neighbours": len(self.neighbours),
        }

    def stop(self) -> None:
        self._running = False
