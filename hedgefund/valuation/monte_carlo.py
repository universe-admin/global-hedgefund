"""Monte Carlo price-path engine (GBM), pure Python.

Simulates N multi-year paths and reports the bear/base/bull target range and
the probability of a gain by the horizon — the numbers on the written thesis
card ("5-year target range, blended DCF · exit-multiple · Monte Carlo").
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List


@dataclass
class MonteCarloResult:
    paths: int
    horizon_years: int
    p05: float   # tail bear (5th percentile terminal price)
    p20: float   # bear case (20th percentile)
    p50: float   # base (median)
    p90: float   # bull case (90th percentile)
    p95: float   # tail bull (95th percentile)
    prob_gain: float  # P(terminal > spot)


def simulate(spot: float, drift: float, vol: float, years: int,
             paths: int = 20_000, seed: int = 7) -> MonteCarloResult:
    """GBM terminal-price distribution.

    drift/vol are annualized; simulation uses one step per year on the exact
    lognormal solution, so no discretization error and it stays fast in pure
    Python even at 20k paths.
    """
    rng = random.Random(seed)
    mu = drift - 0.5 * vol * vol
    sqrt_t = math.sqrt(years)
    terminals: List[float] = [
        spot * math.exp(mu * years + vol * sqrt_t * rng.gauss(0, 1))
        for _ in range(paths)
    ]
    terminals.sort()

    def pct(q: float) -> float:
        idx = min(int(q * paths), paths - 1)
        return terminals[idx]

    gains = sum(1 for t in terminals if t > spot)
    return MonteCarloResult(
        paths=paths,
        horizon_years=years,
        p05=round(pct(0.05), 2),
        p20=round(pct(0.20), 2),
        p50=round(pct(0.50), 2),
        p90=round(pct(0.90), 2),
        p95=round(pct(0.95), 2),
        prob_gain=round(gains / paths, 3),
    )
