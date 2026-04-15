"""
TangleNode — a fully autonomous OS-process-ready node.

This is the central module of the distributed version.  When invoked as
a subprocess (via node_main.py), it:

    1. Binds a TCP server on its assigned port.
    2. Connects to each peer's TCP server.
    3. Runs three concurrent loops:
       a) Issuer — generates txs at Poisson rate λ
       b) Inbound handler — reads from every TCP connection
       c) Metrics sampler — records L(t), throughput, latencies
    4. On shutdown writes metrics to a JSON file in the output dir.

There is NO shared memory, NO central coordinator.  Convergence is
achieved solely through TCP gossip — exactly how a real P2P Tangle
network operates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from core.transaction import Transaction, TxStatus
from core.tangle import Tangle
from core.tip_selection import TipSelector, build_selector
from core.pow import PoW
from core.validation import tips_consistent
from network.protocol import (
    Message, MsgType, read_message, write_message,
)
from network.peer import PeerConnection, LatencyModel

log = logging.getLogger(__name__)


class TangleNode:
    def __init__(
        self,
        node_id: str,
        host: str,
        port: int,
        peers: list[dict],          # [{"node_id": ..., "host": ..., "port": ...}]
        selector: TipSelector,
        pow: PoW,
        tx_rate: float,             # λ
        m: int,
        latency: LatencyModel,
        genesis_dict: dict,
        duration: float,
        output_dir: str,
        seed: int = 0,
    ):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.peer_cfgs = peers
        self.selector = selector
        self.pow = pow
        self.tx_rate = tx_rate
        self.m = m
        self.latency = latency
        self.duration = duration
        self.output_dir = output_dir

        # Build genesis and local tangle
        genesis = Transaction.from_dict(genesis_dict)
        genesis.status = TxStatus.CONFIRMED
        self.tangle = Tangle(genesis=genesis)

        self._rng = random.Random(seed)
        self._seen_msgs: set[str] = set()
        self._peer_conns: dict[str, PeerConnection] = {}
        self._inbound_readers: list[tuple[str, asyncio.StreamReader]] = []
        self._server: Optional[asyncio.Server] = None
        self._running = False
        self._tx_count = 0
        self._start_time = 0.0

        # Pending txs buffer — txs we received but whose parents are missing
        self._pending: dict[str, dict] = {}  # tx_id -> tx_dict

        # Metrics
        self._tip_history: list[tuple[float, int]] = []
        self._issued: list[tuple[float, str]] = []
        self._received: list[tuple[float, str, str]] = []  # (time, tx_id, from)
        self._latencies: list[float] = []   # propagation latency ms

    # ==================================================================
    #  LIFECYCLE
    # ==================================================================

    async def run(self) -> None:
        """Full node lifecycle."""
        self._running = True
        self._start_time = time.time()
        pid = os.getpid()
        log.info("[%s pid=%d] Starting on %s:%d  (λ=%.2f, algo=%s, peers=%d)",
                 self.node_id, pid, self.host, self.port,
                 self.tx_rate, self.selector.name, len(self.peer_cfgs))

        # 1. Start TCP server
        self._server = await asyncio.start_server(
            self._handle_inbound, self.host, self.port
        )
        log.info("[%s] TCP server listening on %s:%d", self.node_id, self.host, self.port)

        # 2. Connect to peers (with retries — peers may still be booting)
        connect_tasks = []
        for pcfg in self.peer_cfgs:
            pc = PeerConnection(
                local_id=self.node_id,
                peer_id=pcfg["node_id"],
                host=pcfg["host"],
                port=pcfg["port"],
                latency=self.latency,
                seed=self._rng.randint(0, 2**31),
            )
            self._peer_conns[pcfg["node_id"]] = pc
            connect_tasks.append(pc.connect(retries=80, interval=0.15))

        results = await asyncio.gather(*connect_tasks)
        connected = sum(1 for r in results if r)
        log.info("[%s] Connected to %d/%d peers", self.node_id, connected, len(self.peer_cfgs))

        # 3. Start peer send loops
        send_tasks = [
            asyncio.create_task(pc.send_loop())
            for pc in self._peer_conns.values()
        ]

        # 4. Run main loops
        try:
            await asyncio.gather(
                self._issuer_loop(),
                self._metrics_loop(),
                self._pending_retry_loop(),
                asyncio.sleep(self.duration + 2),  # hard deadline
            )
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

        # 5. Shutdown
        for pc in self._peer_conns.values():
            await pc.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # 6. Dump metrics
        self._write_metrics()
        log.info("[%s pid=%d] Stopped.  tangle=%s",
                 self.node_id, pid, self.tangle.summary())

    # ==================================================================
    #  TCP SERVER — inbound connections from peers
    # ==================================================================

    async def _handle_inbound(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one inbound TCP connection from a peer."""
        peer_id = "unknown"
        try:
            while self._running:
                msg = await read_message(reader)
                if msg is None:
                    break
                if msg.msg_type == MsgType.PEER_HELLO:
                    peer_id = msg.payload.get("node_id", "unknown")
                    ack = Message(msg_type=MsgType.PEER_HELLO_ACK,
                                  sender=self.node_id,
                                  payload={"node_id": self.node_id})
                    await write_message(writer, ack)
                    continue
                if msg.msg_type == MsgType.PEER_HELLO_ACK:
                    continue
                await self._dispatch(msg)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    # ==================================================================
    #  MESSAGE DISPATCH
    # ==================================================================

    async def _dispatch(self, msg: Message) -> None:
        # Deduplication
        if msg.msg_id in self._seen_msgs:
            return
        self._seen_msgs.add(msg.msg_id)

        if msg.msg_type == MsgType.TX_BROADCAST:
            self._handle_tx_broadcast(msg)
        elif msg.msg_type == MsgType.TX_REQUEST:
            self._handle_tx_request(msg)
        elif msg.msg_type == MsgType.TX_RESPONSE:
            self._handle_tx_response(msg)
        elif msg.msg_type == MsgType.SYNC_REQUEST:
            self._handle_sync_request(msg)
        elif msg.msg_type == MsgType.SYNC_RESPONSE:
            self._handle_sync_response(msg)

    # -- TX_BROADCAST ------------------------------------------------------
    def _handle_tx_broadcast(self, msg: Message) -> None:
        tx_data = msg.payload.get("tx")
        if not tx_data:
            return
        tx = Transaction.from_dict(tx_data)
        if self.tangle.has(tx.tx_id):
            return

        # Check parents
        missing = [p for p in tx.parents if not self.tangle.has(p)]
        if missing:
            # Buffer and request missing parents
            self._pending[tx.tx_id] = tx_data
            for pid in missing:
                req = Message(msg_type=MsgType.TX_REQUEST, sender=self.node_id,
                              payload={"tx_id": pid})
                self._broadcast(req, exclude=None)
            return

        ok = self.tangle.attach(tx)
        if ok:
            lat = (time.time() - tx.timestamp) * 1000
            self._received.append((time.time(), tx.tx_id, msg.sender))
            self._latencies.append(lat)
            # Re-gossip to our peers (decrement TTL)
            if msg.ttl > 1:
                fwd = Message(
                    msg_type=MsgType.TX_BROADCAST, sender=self.node_id,
                    payload=msg.payload, msg_id=msg.msg_id,
                    ts=msg.ts, ttl=msg.ttl - 1,
                )
                self._broadcast(fwd, exclude=msg.sender)
            # Try to flush pending
            self._try_flush_pending()

    # -- TX_REQUEST / TX_RESPONSE ------------------------------------------
    def _handle_tx_request(self, msg: Message) -> None:
        tx_id = msg.payload.get("tx_id")
        if not tx_id:
            return
        tx = self.tangle.get(tx_id)
        if tx:
            resp = Message(msg_type=MsgType.TX_RESPONSE, sender=self.node_id,
                           payload={"tx": tx.to_dict()})
            self._send_to(msg.sender, resp)

    def _handle_tx_response(self, msg: Message) -> None:
        tx_data = msg.payload.get("tx")
        if tx_data:
            tx = Transaction.from_dict(tx_data)
            if not self.tangle.has(tx.tx_id):
                self.tangle.attach(tx)
                self._try_flush_pending()

    # -- SYNC --------------------------------------------------------------
    def _handle_sync_request(self, msg: Message) -> None:
        resp = Message(msg_type=MsgType.SYNC_RESPONSE, sender=self.node_id,
                       payload={"txs": self.tangle.all_tx_dicts()})
        self._send_to(msg.sender, resp)

    def _handle_sync_response(self, msg: Message) -> None:
        for td in msg.payload.get("txs", []):
            tx = Transaction.from_dict(td)
            if not self.tangle.has(tx.tx_id):
                self.tangle.attach(tx)

    # -- pending buffer ----------------------------------------------------
    def _try_flush_pending(self) -> None:
        flushed = True
        while flushed:
            flushed = False
            to_remove = []
            for tx_id, tx_data in list(self._pending.items()):
                tx = Transaction.from_dict(tx_data)
                if all(self.tangle.has(p) for p in tx.parents):
                    if self.tangle.attach(tx):
                        lat = (time.time() - tx.timestamp) * 1000
                        self._received.append((time.time(), tx.tx_id, "pending"))
                        self._latencies.append(lat)
                    to_remove.append(tx_id)
                    flushed = True
            for tid in to_remove:
                del self._pending[tid]

    async def _pending_retry_loop(self) -> None:
        """Periodically request any still-missing parents."""
        while self._running and (time.time() - self._start_time < self.duration):
            await asyncio.sleep(2.0)
            for tx_id, tx_data in list(self._pending.items()):
                tx = Transaction.from_dict(tx_data)
                for pid in tx.parents:
                    if not self.tangle.has(pid):
                        req = Message(msg_type=MsgType.TX_REQUEST,
                                      sender=self.node_id,
                                      payload={"tx_id": pid})
                        self._broadcast(req, exclude=None)
            self._try_flush_pending()

    # ==================================================================
    #  GOSSIP HELPERS
    # ==================================================================

    def _broadcast(self, msg: Message, exclude: Optional[str] = None) -> None:
        for pid, pc in self._peer_conns.items():
            if pid != exclude:
                pc.enqueue(msg)

    def _send_to(self, peer_id: str, msg: Message) -> None:
        pc = self._peer_conns.get(peer_id)
        if pc:
            pc.enqueue(msg)
        else:
            # Peer connected inbound but we don't have outbound — broadcast
            self._broadcast(msg, exclude=None)

    # ==================================================================
    #  ISSUER LOOP
    # ==================================================================

    async def _issuer_loop(self) -> None:
        while self._running and (time.time() - self._start_time < self.duration):
            if self.tx_rate > 0:
                interval = self._rng.expovariate(self.tx_rate)
            else:
                interval = self.duration
            await asyncio.sleep(interval)
            if time.time() - self._start_time >= self.duration:
                break
            await self._issue_tx()

    async def _issue_tx(self) -> None:
        # 1. Select tips
        tips = self.selector.select(self.tangle, self.m)

        # 2. Validate
        if not tips_consistent(self.tangle, tips):
            for _ in range(3):
                tips = self.selector.select(self.tangle, self.m)
                if tips_consistent(self.tangle, tips):
                    break
            else:
                return

        # 3. Create tx
        self._tx_count += 1
        tx = Transaction(
            issuer=self.node_id,
            parents=tips,
            value=self._rng.uniform(0, 10),
            sender_addr=f"addr_{self.node_id}",
            receiver_addr=f"addr_peer_{self._rng.randint(0, 99)}",
        )

        # 4. PoW (real async delay)
        tx = await self.pow.run(tx)

        # 5. Attach locally
        if not self.tangle.attach(tx):
            return

        self._issued.append((time.time(), tx.tx_id))
        log.debug("[%s] Issued %s → %s", self.node_id, tx.tx_id[:8],
                  [p[:8] for p in tips])

        # 6. Gossip to all peers
        msg = Message(
            msg_type=MsgType.TX_BROADCAST, sender=self.node_id,
            payload={"tx": tx.to_dict()},
        )
        self._seen_msgs.add(msg.msg_id)
        self._broadcast(msg)

    # ==================================================================
    #  METRICS LOOP
    # ==================================================================

    async def _metrics_loop(self) -> None:
        while self._running and (time.time() - self._start_time < self.duration):
            await asyncio.sleep(0.5)
            elapsed = time.time() - self._start_time
            self._tip_history.append((round(elapsed, 2), len(self.tangle.tips)))

    # ==================================================================
    #  DUMP METRICS TO FILE
    # ==================================================================

    def _write_metrics(self) -> None:
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        data = {
            "node_id": self.node_id,
            "pid": os.getpid(),
            "algorithm": self.selector.name,
            "tangle_summary": self.tangle.summary(),
            "txs_issued": self._tx_count,
            "tip_history": self._tip_history,
            "issued": self._issued,
            "received": [(t, tid, f) for t, tid, f in self._received],
            "latencies": self._latencies,
            "all_tx_ids": list(self.tangle._txs.keys()),
            "pending_remaining": len(self._pending),
            "edges": self.tangle.edge_list(),
        }
        path = out / f"{self.node_id}.json"
        path.write_text(json.dumps(data, indent=2))
        log.info("[%s] Metrics written to %s", self.node_id, path)
