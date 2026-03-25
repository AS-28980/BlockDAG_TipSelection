"""
Random Tip Selection (RS) algorithm.

The simplest strategy: each of the *m* tips is chosen uniformly at random
from the set of free tips.

Reference: Ferraro et al. §IV-A eq.(7):
    Q_b^{(ran)}(t) = 1 / L(t)
i.e. every tip has equal probability 1/L(t) of being selected.

Pros: all tips are eventually approved (Theorem 3 in Ferraro et al.)
Cons: vulnerable to double-spending attacks because the attacker's branch
      has the same probability of being selected as honest branches.
"""

from __future__ import annotations

import random
from typing import Optional

from src.core.tangle import Tangle
from .tip_selection import TipSelector


class RandomTipSelector(TipSelector):
    """Uniform random tip selection."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return "RandomSelection"

    def select_tips(self, tangle: Tangle, m: int = 2) -> list[str]:
        free = list(tangle.free_tips)
        if not free:
            # Fall back to all tips if no free tips yet
            free = list(tangle.tips)
        if not free:
            return [tangle.genesis_id] * m

        # Select m tips (with replacement allowed to handle small tip sets)
        selected: list[str] = []
        for _ in range(m):
            selected.append(self._rng.choice(free))
        return selected
