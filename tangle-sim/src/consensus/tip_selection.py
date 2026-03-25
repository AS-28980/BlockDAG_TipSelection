"""
Abstract base class for tip selection algorithms.

All tip selectors must implement `select_tips(tangle, m)` which returns
exactly *m* tip transaction IDs for a new transaction to approve.

Reference: Ferraro et al. §II-A — "The first of these is a random selection
algorithm … The second algorithm is based on a random walk from the interior
of the graph (the DAG) to the unvalidated transactions; this is the Markov
Chain Monte Carlo (MCMC) selection method."
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.tangle import Tangle


class TipSelector(ABC):
    """Interface for all tip selection strategies."""

    @abstractmethod
    def select_tips(self, tangle: Tangle, m: int = 2) -> list[str]:
        """
        Select *m* tips from the tangle for a new transaction to approve.

        Parameters
        ----------
        tangle : Tangle
            The node's local view of the DAG.
        m : int
            Number of tips to select (default 2 per the IOTA protocol).

        Returns
        -------
        list[str]
            Exactly *m* transaction IDs (tips).
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable algorithm name."""
        ...
