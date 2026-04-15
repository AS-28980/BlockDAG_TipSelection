"""Unit tests for the TCP wire protocol."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import unittest
from network.protocol import (
    Message, MsgType, encode, decode,
    read_message, write_message, HEADER_SIZE,
)


class TestProtocol(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        msg = Message(msg_type=MsgType.TX_BROADCAST, sender="node_0",
                      payload={"tx": {"id": "abc"}})
        raw = encode(msg)
        self.assertGreater(len(raw), HEADER_SIZE)
        decoded = decode(raw[HEADER_SIZE:])
        self.assertEqual(decoded.msg_type, MsgType.TX_BROADCAST)
        self.assertEqual(decoded.sender, "node_0")
        self.assertEqual(decoded.payload["tx"]["id"], "abc")

    def test_stream_roundtrip(self):
        async def _test():
            # Create an in-process TCP pair
            server_ready = asyncio.Event()
            received = []

            async def handler(reader, writer):
                msg = await read_message(reader)
                if msg:
                    received.append(msg)
                writer.close()

            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            addr = server.sockets[0].getsockname()

            reader, writer = await asyncio.open_connection(addr[0], addr[1])
            msg = Message(msg_type=MsgType.PEER_HELLO, sender="test",
                          payload={"hello": True})
            await write_message(writer, msg)
            writer.close()
            await writer.wait_closed()

            await asyncio.sleep(0.1)
            server.close()
            await server.wait_closed()

            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].msg_type, MsgType.PEER_HELLO)
            self.assertEqual(received[0].payload["hello"], True)

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
