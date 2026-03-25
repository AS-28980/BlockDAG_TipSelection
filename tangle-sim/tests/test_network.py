"""Tests for the network layer."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import unittest
from src.network.message import Message, MessageType
from src.network.transport import Transport, TransportHub, LatencyConfig, DelayModel
from src.network.gossip import GossipProtocol
from src.network.topology import NetworkTopology


class TestTransport(unittest.TestCase):

    def test_hub_routing(self):
        async def _test():
            hub = TransportHub()
            t1 = Transport("node_0", LatencyConfig(DelayModel.CONSTANT, base_ms=10))
            t2 = Transport("node_1", LatencyConfig(DelayModel.CONSTANT, base_ms=10))
            hub.register(t1)
            hub.register(t2)

            msg = Message(
                msg_type=MessageType.HEARTBEAT,
                sender_id="node_0",
                receiver_id="node_1",
                payload={"hello": True},
            )
            await t1.send(msg)
            received = await asyncio.wait_for(t2.recv(), timeout=2.0)
            self.assertEqual(received.msg_type, MessageType.HEARTBEAT)
            self.assertEqual(received.payload["hello"], True)

        asyncio.run(_test())

    def test_broadcast(self):
        async def _test():
            hub = TransportHub()
            nodes = [Transport(f"node_{i}", LatencyConfig(DelayModel.CONSTANT, base_ms=5)) for i in range(3)]
            for t in nodes:
                hub.register(t)

            msg = Message(
                msg_type=MessageType.TX_BROADCAST,
                sender_id="node_0",
                receiver_id="*",
                payload={"tx": "test"},
            )
            await nodes[0].send(msg)

            r1 = await asyncio.wait_for(nodes[1].recv(), timeout=2.0)
            r2 = await asyncio.wait_for(nodes[2].recv(), timeout=2.0)
            self.assertEqual(r1.msg_type, MessageType.TX_BROADCAST)
            self.assertEqual(r2.msg_type, MessageType.TX_BROADCAST)

        asyncio.run(_test())


class TestGossip(unittest.TestCase):

    def test_deduplication(self):
        gossip = GossipProtocol()
        msg = Message(msg_type=MessageType.TX_BROADCAST, sender_id="a")
        self.assertTrue(gossip.should_process(msg))
        self.assertFalse(gossip.should_process(msg))  # duplicate

    def test_ttl_decrement(self):
        gossip = GossipProtocol()
        msg = Message(msg_type=MessageType.TX_BROADCAST, sender_id="a", ttl=2)
        fwd = gossip.prepare_forward(msg, "b")
        self.assertIsNotNone(fwd)
        self.assertEqual(fwd.ttl, 1)

    def test_ttl_expired(self):
        gossip = GossipProtocol()
        msg = Message(msg_type=MessageType.TX_BROADCAST, sender_id="a", ttl=1)
        fwd = gossip.prepare_forward(msg, "b")
        self.assertIsNone(fwd)

    def test_peer_selection_flood(self):
        gossip = GossipProtocol(strategy="flood")
        peers = gossip.select_peers(["a", "b", "c", "d"], exclude="a")
        self.assertEqual(set(peers), {"b", "c", "d"})

    def test_peer_selection_random_k(self):
        gossip = GossipProtocol(strategy="random_k", k=2, seed=42)
        peers = gossip.select_peers(["a", "b", "c", "d", "e"], exclude="a")
        self.assertEqual(len(peers), 2)


class TestTopology(unittest.TestCase):

    def test_full_mesh(self):
        ids = ["a", "b", "c"]
        topo = NetworkTopology.full_mesh(ids)
        self.assertEqual(len(topo.neighbours("a")), 2)
        self.assertIn("b", topo.neighbours("a"))
        self.assertIn("c", topo.neighbours("a"))

    def test_ring(self):
        ids = ["a", "b", "c", "d"]
        topo = NetworkTopology.ring(ids)
        # Each node connected to 2 neighbours
        for nid in ids:
            self.assertEqual(len(topo.neighbours(nid)), 2)

    def test_star(self):
        ids = ["hub", "a", "b", "c"]
        topo = NetworkTopology.star(ids)
        self.assertEqual(len(topo.neighbours("hub")), 3)
        self.assertEqual(len(topo.neighbours("a")), 1)

    def test_small_world(self):
        ids = [f"n{i}" for i in range(10)]
        topo = NetworkTopology.small_world(ids, k=4, seed=42)
        # Should have reasonable connectivity
        for nid in ids:
            self.assertGreaterEqual(len(topo.neighbours(nid)), 2)


if __name__ == "__main__":
    unittest.main()
