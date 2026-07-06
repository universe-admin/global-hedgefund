"""The written thesis card: DCF + CAPM + Monte Carlo in one artifact.

Reproduces the "FIG. 03 — WRITTEN THESIS" card: 5-yr CAGR, P(gain by
horizon), discount rate, vol, beta, stress floor, and the bear/base/bull
target range, plus strengths & threats distilled from the analyst reports.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Optional

from hedgefund.agents.base import AgentReport
from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketSnapshot
from hedgefund.valuation.dcf import DCFResult, run_dcf
from hedgefund.valuation.monte_carlo import MonteCarloResult, simulate


@dataclass
class ThesisCard:
    ticker: str
    company: str
    as_of: str
    price: float
    horizon_years: int
    implied_cagr: float          # base-target CAGR over the horizon
    prob_gain: float
    discount_rate: float
    volatility: float
    beta: float
    stress_floor: float          # $ bear-case floor from stressed DCF
    target_bear: float
    target_base: float
    target_bull: float
    strengths: List[str] = field(default_factory=list)
    threats: List[str] = field(default_factory=list)
    dcf: Optional[DCFResult] = None
    mc: Optional[MonteCarloResult] = None


def build_thesis(snap: MarketSnapshot,
                 analyst_reports: Optional[List[AgentReport]] = None,
                 config: Config = DEFAULT_CONFIG) -> ThesisCard:
    price = snap.last_close() or 1.0
    dcf = run_dcf(snap, config)
    vol = snap.realized_vol(60) or snap.options.atm_iv_1m or 0.35
    beta = snap.fundamentals.beta or 1.0
    years = config.valuation_horizon_years

    # Drift anchored on intrinsic-value convergence: if the blended DCF says
    # fair value is 1.4x price, drift is the CAGR that closes the gap, capped.
    gap_cagr = dcf.blended_ratio ** (1.0 / years) - 1.0
    drift = max(min(gap_cagr + config.risk_free_rate * 0.5, 0.30), -0.10)

    # Long-horizon vol mean-reverts: shrink the excess over 30% by 60% so a
    # 20d spot vol of 56% doesn't get scaled raw across a 5-year sim.
    sim_vol = vol if vol <= 0.30 else 0.30 + (vol - 0.30) * 0.4

    # Seed from the ticker via sha256 so results are stable across runs
    # (builtin hash() is salted per-process).
    seed = int(hashlib.sha256(snap.ticker.encode()).hexdigest()[:8], 16)
    mc = simulate(price, drift, sim_vol, years,
                  paths=config.monte_carlo_paths, seed=seed)

    # Base target: half intrinsic-value convergence, half simulated median.
    base = round(0.5 * price * dcf.blended_ratio * (1 + drift) ** years
                 + 0.5 * mc.p50, 2)
    implied_cagr = (base / price) ** (1.0 / years) - 1.0 if base > 0 else 0.0

    strengths, threats = _distill(analyst_reports or [])

    return ThesisCard(
        ticker=snap.ticker,
        company=snap.company_name or snap.ticker,
        as_of=snap.as_of,
        price=round(price, 2),
        horizon_years=years,
        implied_cagr=round(implied_cagr, 4),
        prob_gain=mc.prob_gain,
        discount_rate=dcf.discount_rate,
        volatility=round(vol, 3),
        beta=round(beta, 2),
        stress_floor=round(price * dcf.stress_floor_ratio, 2),
        target_bear=mc.p20,
        target_base=base,
        target_bull=mc.p90,
        strengths=strengths,
        threats=threats,
        dcf=dcf,
        mc=mc,
    )


def _distill(reports: List[AgentReport]):
    bulls = sorted((r for r in reports if r.score > 0.1),
                   key=lambda r: r.score * r.confidence, reverse=True)
    bears = sorted((r for r in reports if r.score < -0.1),
                   key=lambda r: r.score * r.confidence)
    strengths = [f"{r.headline} ({r.role.lower()})" for r in bulls[:3]]
    threats = [f"{r.headline} ({r.role.lower()})" for r in bears[:3]]
    if not strengths:
        strengths = ["no strong positive pillars — valuation carries the case"]
    if not threats:
        threats = ["no strong negatives flagged — biggest risk is complacency"]
    return strengths, threats
