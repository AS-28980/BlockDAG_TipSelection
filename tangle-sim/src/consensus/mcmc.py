"""
Markov Chain Monte Carlo (MCMC) tip selection algorithm.

A biased random walk starts at the genesis and moves forward through
the DAG following directed edges (parent → child).  At each step the
walker transitions to a child with probability proportional to
    exp( -α · (W_j - W_k) )
where W_j is the cumulative weight of the current node and W_k is the
cumulative weight of the candidate child.

Actually, more precisely from Ferraro et al. §II-A & the original Popov
whitepaper: the walk starts at the genesis and at each branching point
chooses the next transaction proportional to
    f( -α · ( ϑ_j - ϑ_k ) )
where f is a monotonic increasing function (exponential), α is a positive
constant, and ϑ_i is the cumulative weight.

The walk terminates when it reaches a tip (a node with no children that
have been added to the tangle yet).

Parameters
----------
α (alpha) : float
    Controls the bias.  High α → walks prefer heavy branches (more
    secure, but orphans old tips).  Low α → more uniform (less secure,
    but fewer orphans).  α → 0 degenerates to uniform random; α → ∞
    degenerates to greedy heaviest-branch.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from src.core.tangle import Tangle
from .tip_selection import TipSelector


class MCMCTipSelector(TipSelector):
    """
    MCMC (weighted random walk) tip selection.

    Each call to `select_tips` performs *m* independent random walks
    from the genesis to a tip, yielding *m* tips.
    """

    def __init__(self, alpha: float = 0.01, seed: Optional[int] = None) -> None:
        self.alpha = alpha
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return f"MCMC(α={self.alpha})"

    # ── Public interface ────────────────────────────────────────────────
    def select_tips(self, tangle: Tangle, m: int = 2) -> list[str]:
        tips: list[str] = []
        for _ in range(m):
            tip = self._random_walk(tangle)
            tips.append(tip)
        return tips

    # ── Random walk ─────────────────────────────────────────────────────
    def _random_walk(self, tangle: Tangle) -> str:
        """
        Perform one MCMC random walk from genesis to a tip.

        At each node we look at its *children* (transactions that approve it)
        and transition to one of them with probability proportional to
        exp( α · W_child ).  (Equivalently, heavier children are preferred.)

        We stop when the current node has no children — it is a tip.
        """
        current = tangle.genesis_id
        max_steps = tangle.size + 10  # safety bound

        for _ in range(max_steps):
            children = tangle.get_children(current)
            if not children:
                # current is a tip — walk complete
                return current

            # Filter to only attached/confirmed children
            valid_children = [
                cid for cid in children if tangle.has_tx(cid)
            ]
            if not valid_children:
                return current

            # Compute transition probabilities
            weights: list[float] = []
            for cid in valid_children:
                cw = tangle.get_cumulative_weight(cid)
                weights.append(math.exp(self.alpha * cw))

            # Normalise and sample
            total = sum(weights)
            if total == 0:
                current = self._rng.choice(valid_children)
            else:
                probs = [w / total for w in weights]
                current = self._rng.choices(valid_children, weights=probs, k=1)[0]

        # Fallback: return whatever we landed on
        return current
