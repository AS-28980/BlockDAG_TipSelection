# Tangle Distributed Ledger Simulator

A fully distributed simulation of the IOTA Tangle (DAG-based DLT) implementing the tip selection algorithms from two research papers:

1. **Živić et al.** — *"Directed Acyclic Graph as Tangle: an IoT Alternative to Blockchains"* (TELFOR 2019)
2. **Ferraro, King & Shorten** — *"On the stability of unverified transactions in a DAG-based Distributed Ledger"* (IEEE 2020)

## Architecture

Each node runs as an independent async process with its own local Tangle view, communicating via message-passing with simulated network delays — faithfully modelling the asynchronous, eventually-consistent nature of the real IOTA network.

```
┌──────────┐    gossip+delay    ┌──────────┐    gossip+delay    ┌──────────┐
│  Node 0  │◄──────────────────►│  Node 1  │◄──────────────────►│  Node 2  │
│          │                    │          │                    │          │
│ ┌──────┐ │                    │ ┌──────┐ │                    │ ┌──────┐ │
│ │Tangle│ │                    │ │Tangle│ │                    │ │Tangle│ │
│ │ (DAG)│ │                    │ │ (DAG)│ │                    │ │ (DAG)│ │
│ └──────┘ │                    │ └──────┘ │                    │ └──────┘ │
│ ┌──────┐ │                    │ ┌──────┐ │                    │ ┌──────┐ │
│ │ Tip  │ │                    │ │ Tip  │ │                    │ │ Tip  │ │
│ │Select│ │                    │ │Select│ │                    │ │Select│ │
│ └──────┘ │                    │ └──────┘ │                    │ └──────┘ │
└──────────┘                    └──────────┘                    └──────────┘
```

### Key Components

- **`src/core/`** — Transaction data structure, Tangle DAG, cumulative weight computation, simulated Proof-of-Work
- **`src/consensus/`** — Three tip selection algorithms: Random Selection, MCMC (Markov Chain Monte Carlo), and the Hybrid algorithm
- **`src/network/`** — Distributed node process, message types, transport layer with configurable latency models (constant, uniform, normal, log-normal), gossip protocol (flood, random-k, √n), and network topologies (full mesh, ring, random-k, small-world, star)
- **`src/validation/`** — Consistency checking and double-spend detection
- **`src/simulation/`** — Simulation engine, scenario loader (YAML configs), metrics collection
- **`src/visualization/`** — Tangle DAG renderer and multi-panel metrics dashboard

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run default simulation (5 nodes, 30s, hybrid algorithm)
python scripts/run_simulation.py

# Quick test run (3 nodes, 15s)
python scripts/run_simulation.py --quick

# Run with a specific scenario
python scripts/run_simulation.py config/scenarios/large_network.yaml

# Run single-node mode (no network, study tip dynamics)
python scripts/run_single_node.py --algo mcmc --alpha 0.01 --rate 5 --duration 30

# Analyze results
python scripts/analyze_results.py output/results.json

# Run tests
python -m pytest tests/ -v
```

## Tip Selection Algorithms

### Random Selection (RS)
Each tip has equal probability `1/L(t)` of being selected. Simple but vulnerable to double-spending attacks. (Ferraro et al. §IV-A, eq. 7)

### MCMC (Markov Chain Monte Carlo)
A biased random walk from the genesis through the DAG. At each step, the walker transitions to a child with probability proportional to `exp(α · cumulative_weight)`. Higher α favours heavier branches (more secure, but orphans old tips). (Ferraro et al. §II-A; Popov whitepaper)

### Hybrid Algorithm (Paper's Main Contribution)
Combines both approaches in two phases:
- **Security Step**: Select first tip via high-α MCMC (ensures double-spend resistance)
- **Swipe Step**: Select second tip via low-α MCMC or random selection (ensures all tips eventually get approved)

This guarantees that `L(t)` stays bounded — all transactions are validated in finite time. (Ferraro et al. §III)

## Configuration

All parameters are configurable via YAML files. See `config/default.yaml` for the full list. Key parameters from the papers:

| Parameter | Paper Symbol | Description |
|-----------|-------------|-------------|
| `tx_rate` | λ | Poisson arrival rate of new transactions |
| `pow.h` | h | Proof-of-Work delay (time steps) |
| `tip_selection.alpha` | α | MCMC bias parameter |
| `nodes.m` | m | Number of parents per transaction (default 2) |

## Scenarios

- **`small_network.yaml`** — 3 nodes, 15s, quick test
- **`large_network.yaml`** — 10 nodes, 60s, small-world topology
- **`attack_scenario.yaml`** — 7 nodes with one attacker flooding at 4× rate
- **`mcmc_comparison.yaml`** — Pure MCMC for studying L(t) dynamics vs α

## Network Simulation

The simulator models realistic distributed system behaviour:

- **Simulated latency**: Configurable delay models (log-normal recommended for WAN realism) injected on every inter-node message
- **Gossip protocol**: Transactions propagate via configurable gossip (flood, random-k, √n)
- **Partial views**: Each node maintains its own tangle — nodes may have different views at any moment, exactly as described in the papers
- **Network topologies**: Full mesh, ring, random-k, Watts-Strogatz small-world, star

## Output

The simulator produces:

- `output/results.json` — Full metrics (tip counts, latencies, convergence, orphan rate)
- `output/tangle_node0.png` — Visualisation of one node's Tangle DAG
- `output/tangle_comparison.png` — Side-by-side comparison of all nodes' tangles
- `output/dashboard.png` — Multi-panel dashboard with L(t) plot, latency histogram, weight distribution, throughput, and convergence heatmap

## References

1. N. Živić, E. Kadušić, K. Kadušić — "Directed Acyclic Graph as Tangle: an IoT Alternative to Blockchains", 27th TELFOR, 2019
2. P. Ferraro, C. King, R. Shorten — "On the stability of unverified transactions in a DAG-based Distributed Ledger", IEEE, 2020
3. S. Popov — "The Tangle", IOTA Whitepaper, 2018
