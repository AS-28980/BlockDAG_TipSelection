"""
Network transport layer with simulated latency.

Each node binds a ZeroMQ ROUTER socket for receiving and uses DEALER
sockets for sending to peers.  Before delivering a message we inject a
random delay drawn from a configurable distribution to simulate real
network latency.

From Živić et al. §II: "transaction may be issued at any moment by some
node and, after propagation through the network, the transaction reaches
different nodes at different moments."

The delay model supports:
    - Constant delay
    - Uniform random delay
    - Normal (Gaussian) delay
    - Log-normal delay (realistic WAN distribution)
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, Awaitable

from .message import Message

logger = logging.getLogger(__name__)


class DelayModel(Enum):
    CONSTANT = auto()
    UNIFORM = auto()
    NORMAL = auto()
    LOGNORMAL = auto()


@dataclass
class LatencyConfig:
    """
    Configurable network latency model.

    Parameters
    ----------
    model : DelayModel
    base_ms : float        Base / mean latency in milliseconds.
    jitter_ms : float      Range or std-dev depending on model.
    """
    model: DelayModel = DelayModel.LOGNORMAL
    base_ms: float = 100.0
    jitter_ms: float = 50.0

    def sample(self, rng: random.Random | None = None) -> float:
        """Return a single latency sample in *seconds*."""
        r = rng or random.Random()
        if self.model == DelayModel.CONSTANT:
            ms = self.base_ms
        elif self.model == DelayModel.UNIFORM:
            lo = max(0, self.base_ms - self.jitter_ms)
            hi = self.base_ms + self.jitter_ms
            ms = r.uniform(lo, hi)
        elif self.model == DelayModel.NORMAL:
            ms = max(0, r.gauss(self.base_ms, self.jitter_ms))
        elif self.model == DelayModel.LOGNORMAL:
            # μ and σ for underlying normal
            import math
            mu = math.log(self.base_ms) - 0.5 * math.log(
                1 + (self.jitter_ms / self.base_ms) ** 2
            )
            sigma = math.sqrt(math.log(1 + (self.jitter_ms / self.base_ms) ** 2))
            ms = r.lognormvariate(mu, sigma)
        else:
            ms = self.base_ms
        return ms / 1000.0  # seconds


class Transport:
    """
    Async message transport for a single node.

    Instead of raw ZMQ sockets (which require careful lifecycle management
    across processes), this transport uses a shared in-process message bus
    (`TransportHub`) that the simulation engine provides.  Messages are
    delivered after an injected latency delay.

    For true multi-process deployment, swap this out for the ZMQ-backed
    `ZMQTransport` subclass (see bottom of file).
    """

    def __init__(
        self,
        node_id: str,
        latency: LatencyConfig | None = None,
        seed: int | None = None,
    ) -> None:
        self.node_id = node_id
        self.latency = latency or LatencyConfig()
        self._rng = random.Random(seed)
        self._inbox: asyncio.Queue[Message] = asyncio.Queue()
        self._hub: Optional[TransportHub] = None

    def register_hub(self, hub: TransportHub) -> None:
        self._hub = hub

    async def send(self, msg: Message) -> None:
        """Send a message (injecting simulated delay)."""
        if self._hub is None:
            logger.error("Transport for %s has no hub registered", self.node_id)
            return
        delay = self.latency.sample(self._rng)
        # Fire-and-forget delayed delivery
        asyncio.ensure_future(self._delayed_deliver(msg, delay))

    async def _delayed_deliver(self, msg: Message, delay: float) -> None:
        await asyncio.sleep(delay)
        if self._hub:
            await self._hub.route(msg)

    async def recv(self) -> Message:
        """Block until a message arrives in our inbox."""
        return await self._inbox.get()

    def recv_nowait(self) -> Message | None:
        try:
            return self._inbox.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def deliver(self, msg: Message) -> None:
        """Called by the hub to place a message in our inbox."""
        await self._inbox.put(msg)


class TransportHub:
    """
    Central message router that connects all node transports.

    In the simulation, every node registers its Transport here.
    When a node sends a message the hub routes it to the appropriate
    peer(s) after the sender's latency delay has elapsed.
    """

    def __init__(self) -> None:
        self._transports: dict[str, Transport] = {}

    def register(self, transport: Transport) -> None:
        self._transports[transport.node_id] = transport
        transport.register_hub(self)

    async def route(self, msg: Message) -> None:
        """Deliver a message to its intended recipient(s)."""
        if msg.receiver_id == "*":
            # Broadcast to all except sender
            for nid, t in self._transports.items():
                if nid != msg.sender_id:
                    await t.deliver(msg)
        else:
            t = self._transports.get(msg.receiver_id)
            if t:
                await t.deliver(msg)
            else:
                logger.warning(
                    "Hub: no transport for receiver %s", msg.receiver_id
                )

    @property
    def node_ids(self) -> list[str]:
        return list(self._transports.keys())
