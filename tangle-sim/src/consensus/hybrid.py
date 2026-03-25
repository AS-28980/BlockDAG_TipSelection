"""
Hybrid Tip Selection Algorithm.

The principal contribution of Ferraro, King & Shorten (2020 §III):

    "In order to combine the best properties of the two scenarios (large
    and small α), we propose the following hybrid selection algorithm,
    which can be divided conceptually into two steps:

    • **Security Step**: the first set of selections is made using the
      MCMC algorithm with a high value of α.  This is done to protect
      security by ensuring that honest tips get selected preferentially.

    • **Swipe Step**: the set of second selections is performed using a
      different algorithm: it can be a RS or a MCMC with a low value of
      α.  This step serves the purpose of taking care of the older
      transactions that are not likely to be selected by the first step."

    "Roughly speaking, the Security Step takes care of the security of
    the system, whereas the purpose of the Swipe Step is to ensure that
    no tips get left behind by the first, more accurate, selection."

The hybrid guarantees that L(t) (the number of tips) stays bounded —
all transactions are eventually validated in finite time — while
preserving the double-spend resistance of high-α MCMC.
"""

from __future__ import annotations

import random
from typing import Optional

from src.core.tangle import Tangle
from .mcmc import MCMCTipSelector
from .random_selection import RandomTipSelector
from .tip_selection import TipSelector


class HybridTipSelector(TipSelector):
    """
    Hybrid algorithm: first tip via high-α MCMC, second tip via
    low-α MCMC (or pure random).

    Parameters
    ----------
    alpha_high : float
        α for the security step (MCMC walk 1).
    alpha_low : float
        α for the swipe step (MCMC walk 2).  Set to 0 for pure random.
    use_random_swipe : bool
        If True, the swipe step uses uniform random selection instead of
        low-α MCMC.
    security_selections : int
        Number of tips to select in the security step (default 1).
    """

    def __init__(
        self,
        alpha_high: float = 1.0,
        alpha_low: float = 0.001,
        use_random_swipe: bool = False,
        security_selections: int = 1,
        seed: Optional[int] = None,
    ) -> None:
        self.alpha_high = alpha_high
        self.alpha_low = alpha_low
        self.use_random_swipe = use_random_swipe
        self.security_selections = security_selections

        rng_seed = seed
        self._security_selector = MCMCTipSelector(
            alpha=alpha_high, seed=rng_seed
        )

        swipe_seed = (rng_seed + 1) if rng_seed is not None else None
        if use_random_swipe:
            self._swipe_selector: TipSelector = RandomTipSelector(seed=swipe_seed)
        else:
            self._swipe_selector = MCMCTipSelector(
                alpha=alpha_low, seed=swipe_seed
            )

    @property
    def name(self) -> str:
        swipe = "RS" if self.use_random_swipe else f"MCMC(α={self.alpha_low})"
        return f"Hybrid(sec={self.alpha_high}, swipe={swipe})"

    def select_tips(self, tangle: Tangle, m: int = 2) -> list[str]:
        """
        Select m tips using the two-phase hybrid strategy.

        Phase 1 (Security): select `security_selections` tips with high-α MCMC.
        Phase 2 (Swipe):    select the remaining tips with low-α MCMC or RS.
        """
        if m < 1:
            raise ValueError("m must be >= 1")

        n_security = min(self.security_selections, m)
        n_swipe = m - n_security

        tips: list[str] = []

        # Phase 1 — Security step
        security_tips = self._security_selector.select_tips(tangle, n_security)
        tips.extend(security_tips)

        # Phase 2 — Swipe step
        if n_swipe > 0:
            swipe_tips = self._swipe_selector.select_tips(tangle, n_swipe)
            tips.extend(swipe_tips)

        return tips
