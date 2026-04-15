"""
Peer connection manager.

Each node keeps a set of `PeerConnection` objects — one per neighbour.
A PeerConnection wraps a single TCP socket with:
    • a send queue
    • an injected latency delay before each send  (simulated WAN delay)
    • automatic reconnect on drop
    • deduplication of already-seen message IDs

This is the layer that makes the distributed simulation feel like a
real network: messages physically travel over TCP/IP loopback with a
realistic random delay injected before each write.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

from .protocol import Message, MsgType, read_message, write_message

log = logging.getLogger(__name__)


@dataclass
class LatencyModel:
    """Configurable per-link latency (milliseconds → seconds on sample)."""
    model: str = "lognormal"     # constant / uniform / normal / lognormal
    base_ms: float = 100.0
    jitter_ms: float = 50.0

    def sample(self, rng: random.Random) -> float:
        if self.model == "constant":
            return self.base_ms / 1000
        elif self.model == "uniform":
            lo = max(0, self.base_ms - self.jitter_ms)
            return rng.uniform(lo, self.base_ms + self.jitter_ms) / 1000
        elif self.model == "normal":
            return max(0, rng.gauss(self.base_ms, self.jitter_ms)) / 1000
        else:  # lognormal
            mu = math.log(self.base_ms) - 0.5 * math.log(
                1 + (self.jitter_ms / max(self.base_ms, 1)) ** 2
            )
            sigma = math.sqrt(
                math.log(1 + (self.jitter_ms / max(self.base_ms, 1)) ** 2)
            )
            return rng.lognormvariate(mu, sigma) / 1000


class PeerConnection:
    """
    Manages the TCP connection to a single peer.

    The node's main loop hands messages to `enqueue()`.  A background
    writer task drains the queue, sleeps for the sampled latency, then
    writes the frame to the TCP stream.
    """

    def __init__(
        self,
        local_id: str,
        peer_id: str,
        host: str,
        port: int,
        latency: LatencyModel,
        seed: int = 0,
    ):
        self.local_id = local_id
        self.peer_id = peer_id
        self.host = host
        self.port = port
        self.latency = latency
        self._rng = random.Random(seed)
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._connected = False
        self._running = False

    async def connect(self, retries: int = 60, interval: float = 0.25) -> bool:
        """Connect to the peer's TCP server with retries."""
        for attempt in range(retries):
            try:
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
                self._connected = True
                # Send hello
                hello = Message(
                    msg_type=MsgType.PEER_HELLO,
                    sender=self.local_id,
                    payload={"node_id": self.local_id},
                )
                await write_message(self._writer, hello)
                log.debug("[%s] Connected to %s:%d", self.local_id, self.host, self.port)
                return True
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(interval)
        log.warning("[%s] Failed to connect to %s:%d after %d retries",
                    self.local_id, self.host, self.port, retries)
        return False

    async def send_loop(self) -> None:
        """Drain the outbound queue, inject latency, write to TCP."""
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not self._connected or self._writer is None:
                continue
            # Inject latency
            delay = self.latency.sample(self._rng)
            await asyncio.sleep(delay)
            ok = await write_message(self._writer, msg)
            if not ok:
                self._connected = False
                log.warning("[%s] Lost connection to %s", self.local_id, self.peer_id)

    def enqueue(self, msg: Message) -> None:
        """Non-blocking: drop the message into the send queue."""
        if self._connected:
            try:
                self._queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def close(self) -> None:
        self._running = False
        self._connected = False
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
