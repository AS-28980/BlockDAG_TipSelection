#!/usr/bin/env python3
"""
Run a single Tangle node in isolation (no network).

Useful for testing tip selection algorithms and studying the local
tangle growth dynamics without network effects.

Reproduces the simulation setup from Ferraro et al. §II:
    "at each time step a random number of transactions arrive, and for
     each one of these transactions the tip selection algorithm is
     performed on the current tips set in order to generate graph
     structures equivalent to the ones presented in detail in Section II."

Usage:
    python scripts/run_single_node.py --algo mcmc --alpha 0.01 --rate 5 --duration 30
    python scripts/run_single_node.py --algo hybrid --duration 20
    python scripts/run_single_node.py --algo random --rate 10 --duration 60
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.tangle import Tangle
from src.core.transaction import Transaction
from src.core.pow import ProofOfWork
from src.consensus.random_selection import RandomTipSelector
from src.consensus.mcmc import MCMCTipSelector
from src.consensus.hybrid import HybridTipSelector
from src.visualization.tangle_viz import TangleVisualizer


async def run_single_node(
    algo: str,
    alpha: float,
    alpha_high: float,
    alpha_low: float,
    rate: float,
    duration: float,
    pow_h: float,
    m: int,
    seed: int,
    output_dir: Path,
) -> None:
    import random as rng_mod
    rng = rng_mod.Random(seed)

    # Create tip selector
    if algo == "random":
        selector = RandomTipSelector(seed=seed)
    elif algo == "mcmc":
        selector = MCMCTipSelector(alpha=alpha, seed=seed)
    else:
        selector = HybridTipSelector(
            alpha_high=alpha_high, alpha_low=alpha_low, seed=seed
        )

    # Create tangle and PoW
    tangle = Tangle()
    pow_engine = ProofOfWork(h=pow_h)

    # Track L(t)
    tip_history: list[tuple[float, int]] = []
    start = time.time()
    tx_count = 0

    print(f"Running single-node simulation: algo={selector.name}, λ={rate}, h={pow_h}, duration={duration}s")
    print("-" * 60)

    while time.time() - start < duration:
        # Poisson inter-arrival
        interval = rng.expovariate(rate) if rate > 0 else duration
        await asyncio.sleep(interval)

        if time.time() - start >= duration:
            break

        # Select tips
        tips = selector.select_tips(tangle, m)

        # Create transaction
        tx = Transaction(
            issuer_id="solo_node",
            parent_ids=tips,
            value=rng.uniform(0, 5),
            sender_address="addr_solo",
            receiver_address=f"addr_{rng.randint(0,99)}",
        )

        # PoW
        tx = await pow_engine.perform(tx)

        # Attach
        tangle.attach_transaction(tx)
        tx_count += 1

        # Record L(t)
        elapsed = time.time() - start
        tip_history.append((elapsed, len(tangle.tips)))

        if tx_count % 20 == 0:
            print(f"  t={elapsed:.1f}s  txs={tx_count}  tips={len(tangle.tips)}  tangle_size={tangle.size}")

    print("-" * 60)
    print(f"Final: txs={tx_count}, tangle_size={tangle.size}, tips={len(tangle.tips)}")
    print(f"Genesis cumulative weight: {tangle.genesis.cumulative_weight}")

    # Visualise
    output_dir.mkdir(parents=True, exist_ok=True)

    viz = TangleVisualizer()
    viz.render(
        tangle,
        output_path=output_dir / "single_node_tangle.png",
        title=f"Single Node — {selector.name} (λ={rate}, h={pow_h})",
    )

    # Plot L(t)
    if tip_history:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        times, counts = zip(*tip_history)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(times, counts, color="#5C6BC0", linewidth=1.5)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("L(t) — Number of Tips")
        ax.set_title(f"Tip Count L(t) — {selector.name}")
        ax.grid(True, alpha=0.3)
        fig.savefig(output_dir / "single_node_Lt.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    print(f"Output saved to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Single-node Tangle simulation")
    parser.add_argument("--algo", default="hybrid", choices=["random", "mcmc", "hybrid"])
    parser.add_argument("--alpha", type=float, default=0.01, help="α for MCMC")
    parser.add_argument("--alpha-high", type=float, default=1.0, help="α_high for Hybrid")
    parser.add_argument("--alpha-low", type=float, default=0.001, help="α_low for Hybrid")
    parser.add_argument("--rate", type=float, default=5.0, help="λ: tx arrival rate")
    parser.add_argument("--duration", type=float, default=20.0, help="Simulation duration (s)")
    parser.add_argument("--pow-h", type=float, default=0.5, help="PoW delay h (s)")
    parser.add_argument("--m", type=int, default=2, help="Tips per transaction")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="output/single_node")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    asyncio.run(run_single_node(
        algo=args.algo,
        alpha=args.alpha,
        alpha_high=args.alpha_high,
        alpha_low=args.alpha_low,
        rate=args.rate,
        duration=args.duration,
        pow_h=args.pow_h,
        m=args.m,
        seed=args.seed,
        output_dir=Path(args.output_dir),
    ))


if __name__ == "__main__":
    main()
