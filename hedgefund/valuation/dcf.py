"""Blended intrinsic value: FCF-based DCF with a CAPM discount rate,
cross-checked with an exit-multiple approach.

Pure Python, no dependencies. All inputs come off the market snapshot with
conservative defaults where data is missing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketSnapshot


@dataclass
class DCFResult:
    discount_rate: float
    growth_rate: float           # blended 5-yr FCF growth assumption
    terminal_growth: float
    dcf_value_per_share_ratio: float   # intrinsic value / current price
    exit_multiple_ratio: float         # exit-multiple value / current price
    blended_ratio: float               # 60/40 blend
    stress_floor_ratio: float          # bear-case floor / current price


def capm_rate(beta: Optional[float], config: Config = DEFAULT_CONFIG) -> float:
    b = beta if beta is not None else 1.0
    rate = config.risk_free_rate + b * config.equity_risk_premium
    return max(0.06, min(rate, 0.20))


def growth_assumption(snap: MarketSnapshot) -> float:
    """Blend recent revenue growth with mean reversion to GDP-ish growth."""
    g = snap.fundamentals.revenue_growth_yoy
    if g is None:
        g = snap.estimates.eps_next_year_growth
    if g is None:
        g = 0.06
    # Fade: year-1 growth decays 15%/yr toward 4% — averaged over 5 years.
    total, cur = 0.0, max(min(g, 0.60), -0.10)
    for _ in range(5):
        total += cur
        cur = cur * 0.85 + 0.04 * 0.15
    return total / 5


def run_dcf(snap: MarketSnapshot, config: Config = DEFAULT_CONFIG) -> DCFResult:
    price = snap.last_close() or 1.0
    r = capm_rate(snap.fundamentals.beta, config)
    g = growth_assumption(snap)
    g_term = 0.025

    fcf_yield = snap.fundamentals.fcf_yield
    if fcf_yield is None or fcf_yield <= 0:
        fcf_yield = 0.02  # conservative default for a growth name
    fcf0 = fcf_yield * price  # per "share" of current price

    horizon = config.valuation_horizon_years
    pv = 0.0
    fcf = fcf0
    for year in range(1, horizon + 1):
        fcf *= (1 + g)
        pv += fcf / (1 + r) ** year
    terminal = fcf * (1 + g_term) / max(r - g_term, 0.02)
    pv += terminal / (1 + r) ** horizon
    dcf_ratio = pv / price

    # Exit multiple: today's forward P/E faded 20% toward market (~18x),
    # applied to year-5 earnings power grown at g.
    pe = snap.fundamentals.pe_forward or 18.0
    exit_pe = pe * 0.8 + 18.0 * 0.2
    eps_ratio_now = 1.0 / pe if pe > 0 else 1 / 18.0
    eps_5 = eps_ratio_now * (1 + g) ** horizon
    exit_ratio = (eps_5 * exit_pe) / (1 + r) ** horizon

    blended = 0.6 * dcf_ratio + 0.4 * exit_ratio

    # Stress floor: zero growth, discount rate +300bp, terminal at 2%.
    r_s = r + 0.03
    pv_s = sum(fcf0 / (1 + r_s) ** y for y in range(1, horizon + 1))
    pv_s += (fcf0 * 1.02 / max(r_s - 0.02, 0.03)) / (1 + r_s) ** horizon
    stress = max(pv_s / price, 0.15)

    return DCFResult(
        discount_rate=round(r, 4),
        growth_rate=round(g, 4),
        terminal_growth=g_term,
        dcf_value_per_share_ratio=round(dcf_ratio, 3),
        exit_multiple_ratio=round(exit_ratio, 3),
        blended_ratio=round(blended, 3),
        stress_floor_ratio=round(stress, 3),
    )
