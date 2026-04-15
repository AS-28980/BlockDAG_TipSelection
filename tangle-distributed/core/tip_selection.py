"""
All three tip selection algorithms in one file.

    1. Random Selection  (Ferraro et al. §IV-A eq.7)
    2. MCMC random walk  (Ferraro et al. §II-A, Popov whitepaper)
    3. Hybrid            (Ferraro et al. §III — security step + swipe step)

Kept in a single file so every node process has one import.
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from typing import Optional

from .tangle import Tangle


class TipSelector(ABC):
    @abstractmethod
    def select(self, tangle: Tangle, m: int = 2) -> list[str]: ...
    @property
    @abstractmethod
    def name(self) -> str: ...


class RandomSelector(TipSelector):
    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return "Random"

    def select(self, tangle: Tangle, m: int = 2) -> list[str]:
        pool = list(tangle.free_tips) or list(tangle.tips) or [tangle.genesis_id]
        return [self._rng.choice(pool) for _ in range(m)]


class MCMCSelector(TipSelector):
    """
    Biased random walk from genesis → tip.
    Transition probability to child c ∝ exp(α · cumulative_weight(c)).
    """

    def __init__(self, alpha: float = 0.01, seed: Optional[int] = None):
        self.alpha = alpha
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return f"MCMC(α={self.alpha})"

    def select(self, tangle: Tangle, m: int = 2) -> list[str]:
        return [self._walk(tangle) for _ in range(m)]

    def _walk(self, tangle: Tangle) -> str:
        cur = tangle.genesis_id
        for _ in range(tangle.size + 10):
            kids = [c for c in tangle.children_of(cur) if tangle.has(c)]
            if not kids:
                return cur
            ws = [math.exp(self.alpha * tangle.weight(c)) for c in kids]
            total = sum(ws)
            if total == 0:
                cur = self._rng.choice(kids)
            else:
                cur = self._rng.choices(kids, weights=ws, k=1)[0]
        return cur


class HybridSelector(TipSelector):
    """
    Ferraro et al. §III:
      • Security step — high-α MCMC  (1st tip)
      • Swipe step   — low-α MCMC or pure random  (2nd tip)
    """

    def __init__(
        self,
        alpha_high: float = 1.0,
        alpha_low: float = 0.001,
        use_random_swipe: bool = False,
        seed: Optional[int] = None,
    ):
        self._sec = MCMCSelector(alpha=alpha_high, seed=seed)
        s2 = (seed + 1) if seed is not None else None
        self._swp: TipSelector = (
            RandomSelector(seed=s2)
            if use_random_swipe
            else MCMCSelector(alpha=alpha_low, seed=s2)
        )
        self._ah = alpha_high
        self._al = alpha_low
        self._rs = use_random_swipe

    @property
    def name(self) -> str:
        sw = "RS" if self._rs else f"MCMC(α={self._al})"
        return f"Hybrid(sec={self._ah},swipe={sw})"

    def select(self, tangle: Tangle, m: int = 2) -> list[str]:
        tips = self._sec.select(tangle, 1)
        if m > 1:
            tips += self._swp.select(tangle, m - 1)
        return tips


def build_selector(cfg: dict, seed: int = 0) -> TipSelector:
    """Factory — builds a selector from a config dict."""
    algo = cfg.get("algorithm", "hybrid")
    if algo == "random":
        return RandomSelector(seed=seed)
    elif algo == "mcmc":
        return MCMCSelector(alpha=cfg.get("alpha", 0.01), seed=seed)
    else:
        return HybridSelector(
            alpha_high=cfg.get("alpha_high", 1.0),
            alpha_low=cfg.get("alpha_low", 0.001),
            use_random_swipe=cfg.get("use_random_swipe", False),
            seed=seed,
        )
