# Tangle Distributed — Multi-Process Simulation

A true multi-process distributed simulation of the IOTA Tangle.  Unlike the `tangle-sim` benchmark (which uses cooperative async tasks in one process), this version **spawns a separate OS process per node**, each with its own PID, its own memory space, its own asyncio event loop, and its own TCP server.  Nodes communicate exclusively through TCP sockets with injected latency — no shared memory, no coordinator.

## Architecture

```
scripts/run.py (launcher)
    │
    ├── subprocess.Popen ──► python node/node_main.py  (PID 4201, port 9200)
    │                            ├── TCP server :9200
    │                            ├── TCP client → :9201
    │                            ├── TCP client → :9202
    │                            ├── Local Tangle (DAG)
    │                            └── Metrics → output/nodes/node_0.json
    │
    ├── subprocess.Popen ──► python node/node_main.py  (PID 4202, port 9201)
    │                            ├── TCP server :9201
    │                            ├── TCP client → :9200
    │                            ├── TCP client → :9202
    │                            ├── Local Tangle (DAG)
    │                            └── Metrics → output/nodes/node_1.json
    │
    └── subprocess.Popen ──► python node/node_main.py  (PID 4203, port 9202)
                                 ├── TCP server :9202
                                 ├── TCP client → :9200
                                 ├── TCP client → :9201
                                 ├── Local Tangle (DAG)
                                 └── Metrics → output/nodes/node_2.json

         All communication: length-prefixed JSON over TCP with simulated delay
```

## What Makes This Different From tangle-sim

| Aspect | tangle-sim | tangle-distributed |
|--------|-----------|-------------------|
| Node processes | Async tasks in 1 process | Separate OS processes (distinct PIDs) |
| Communication | In-memory queue via TransportHub | Real TCP sockets on localhost |
| Memory isolation | Shared address space | Fully separate (no shared state) |
| Latency injection | asyncio.sleep before queue put | asyncio.sleep before TCP write |
| Coordinator | SimulationEngine orchestrates | Launcher only spawns; nodes are autonomous |
| Metrics | Collected in-process | Each node writes its own JSON file |

## Quick Start

```bash
# Quick test (3 processes, 15s)
python scripts/run.py --quick

# Default config (5 processes, 30s)
python scripts/run.py

# Specific scenario
python scripts/run.py config/scenarios/large_network.yaml

# Run tests
python -m unittest discover tests -v
```

## Scenarios

- `small_network.yaml` — 3 processes, full mesh, 15s
- `large_network.yaml` — 8 processes, small-world topology, 45s
- `mcmc_comparison.yaml` — pure MCMC, study L(t) vs α
- `attack_scenario.yaml` — 7 processes, one attacker at 4× rate

## Wire Protocol

Messages are framed as `[4-byte big-endian length][JSON payload]` over raw TCP streams.  Message types: `TX_BROADCAST`, `TX_REQUEST`, `TX_RESPONSE`, `SYNC_REQUEST`, `SYNC_RESPONSE`, `PEER_HELLO`, `PEER_HELLO_ACK`.

## Output

After a run, `output/` contains:

- `output/nodes/node_X.json` — per-node raw metrics (tip history, latencies, issued txs, full tx ID list, edge list)
- `output/results.json` — aggregated cross-node metrics
- `output/dashboard.png` — 6-panel visualization
- `output/tangle_comparison.png` — per-node tangle side-by-side
- `output/scenario.yaml` — copy of the config used
- `output/node_configs/` — the per-node config JSONs passed to each subprocess

## References

1. Ferraro, King & Shorten — "On the stability of unverified transactions in a DAG-based Distributed Ledger" (2020)
2. Živić et al. — "Directed Acyclic Graph as Tangle: an IoT Alternative to Blockchains" (TELFOR 2019)
3. Popov — "The Tangle" IOTA Whitepaper (2018)
