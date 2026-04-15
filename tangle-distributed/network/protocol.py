"""
Wire protocol — length-prefixed JSON over raw TCP.

Every message is framed as:
    [4 bytes big-endian uint32 = payload length N] [N bytes UTF-8 JSON]

This gives us reliable message boundaries over a TCP stream.
No external dependencies — pure stdlib asyncio + json + struct.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

log = logging.getLogger(__name__)

HEADER_FMT = "!I"          # big-endian uint32
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_MSG_SIZE = 16 * 1024 * 1024   # 16 MB safety limit


class MsgType(Enum):
    TX_BROADCAST = auto()     # a new transaction to gossip
    TX_REQUEST = auto()       # request a tx by id
    TX_RESPONSE = auto()      # response with a tx payload
    SYNC_REQUEST = auto()     # request full tangle snapshot
    SYNC_RESPONSE = auto()    # full tangle snapshot
    PEER_HELLO = auto()       # initial handshake (node_id exchange)
    PEER_HELLO_ACK = auto()   # handshake ack


@dataclass
class Message:
    msg_type: MsgType
    sender: str
    payload: dict = field(default_factory=dict)
    msg_id: str = ""
    ts: float = field(default_factory=time.time)
    ttl: int = 6

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = uuid.uuid4().hex[:12]


# -- encode / decode -------------------------------------------------------

def encode(msg: Message) -> bytes:
    """Serialise a Message into a length-prefixed frame."""
    body = json.dumps({
        "msg_type": msg.msg_type.name,
        "sender": msg.sender,
        "payload": msg.payload,
        "msg_id": msg.msg_id,
        "ts": msg.ts,
        "ttl": msg.ttl,
    }).encode("utf-8")
    return struct.pack(HEADER_FMT, len(body)) + body


def decode(data: bytes) -> Message:
    """Deserialise a JSON body (already stripped of the length header)."""
    d = json.loads(data.decode("utf-8"))
    return Message(
        msg_type=MsgType[d["msg_type"]],
        sender=d["sender"],
        payload=d.get("payload", {}),
        msg_id=d.get("msg_id", ""),
        ts=d.get("ts", 0),
        ttl=d.get("ttl", 6),
    )


# -- stream helpers --------------------------------------------------------

async def read_message(reader: asyncio.StreamReader) -> Optional[Message]:
    """Read one length-prefixed message from a stream."""
    try:
        header = await reader.readexactly(HEADER_SIZE)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    length = struct.unpack(HEADER_FMT, header)[0]
    if length > MAX_MSG_SIZE:
        log.error("Message too large: %d bytes", length)
        return None
    try:
        body = await reader.readexactly(length)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    return decode(body)


async def write_message(writer: asyncio.StreamWriter, msg: Message) -> bool:
    """Write one length-prefixed message to a stream."""
    try:
        writer.write(encode(msg))
        await writer.drain()
        return True
    except (ConnectionError, OSError):
        return False
