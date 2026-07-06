"""The Trader: turns the research stance into an executable plan.

Sizing is volatility-targeted (position vol contribution ~= config target,
scaled by conviction) and capped by the single-name limit. Entry band, price
targets and stop come off the live tape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from hedgefund.agents.base import AgentReport, clamp
from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketSnapshot
from hedgefund.llm.client import LLMClient


@dataclass
class TradePlan:
    action: str                 # buy | add | hold | trim | sell | avoid
    direction: str              # long | flat
    size_pct_nav: float         # proposed position size, fraction of NAV
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    target_base: Optional[float] = None
    target_stretch: Optional[float] = None
    stop: Optional[float] = None
    catalyst: Optional[str] = None
    rationale: str = ""
    metrics: Dict[str, str] = field(default_factory=dict)


class Trader:
    role = "Trader"

    def __init__(self, llm: Optional[LLMClient] = None,
                 config: Config = DEFAULT_CONFIG):
        self.llm = llm
        self.config = config

    def plan(self, snap: MarketSnapshot, research: AgentReport,
             held_pct_nav: float = 0.0) -> TradePlan:
        price = snap.last_close() or 0.0
        vol = snap.realized_vol(20) or 0.35
        score = research.score

        # Vol-targeted sizing: size * vol ~= target vol contribution,
        # scaled by conviction, capped by the single-name limit.
        conviction = abs(score)
        raw = (self.config.target_position_vol / max(vol, 0.10)) * conviction
        size = clamp(raw, 0.0, self.config.max_position_pct)

        if score > 0.15:
            action = "add" if held_pct_nav > 0.0 else "buy"
            direction = "long"
        elif score < -0.35:
            action = "sell" if held_pct_nav > 0.0 else "avoid"
            direction, size = "flat", 0.0
        elif score < -0.15 and held_pct_nav > 0.0:
            action, direction = "trim", "long"
            size = max(held_pct_nav / 2, 0.0)
        else:
            action = "hold"
            direction = "long" if held_pct_nav > 0 else "flat"
            size = held_pct_nav

        daily_move = price * vol / 16  # ~1 stdev daily move (vol/sqrt(252))
        entry_low = round(price - daily_move, 2) if price else None
        entry_high = round(price + daily_move * 0.5, 2) if price else None
        tgt = snap.estimates.consensus_target
        target_base = round(tgt, 2) if tgt else (
            round(price * (1 + clamp(score, 0, 1) * 0.25), 2) if price else None)
        target_stretch = round((target_base or price) * 1.12, 2) if price else None
        stop = round(price * (1 - self.config.stop_loss_pct), 2) if price else None
        catalyst = (f"earnings {snap.estimates.next_earnings_date}"
                    if snap.estimates.next_earnings_date else None)

        metrics = {
            "action": action,
            "size (% NAV)": f"{size * 100:.1f}%",
            "entry band": f"{entry_low} - {entry_high}",
            "targets": f"{target_base} / {target_stretch}",
            "stop": str(stop),
            "catalyst": catalyst or "none scheduled",
        }
        rationale = self._explain(snap, research, action, size, metrics)
        return TradePlan(
            action=action, direction=direction, size_pct_nav=round(size, 4),
            entry_low=entry_low, entry_high=entry_high,
            target_base=target_base, target_stretch=target_stretch,
            stop=stop, catalyst=catalyst, rationale=rationale, metrics=metrics,
        )

    def _explain(self, snap, research, action, size, metrics) -> str:
        if self.llm and self.llm.enabled:
            out = self.llm.complete(
                "You are the execution trader at a hedge fund. Given the "
                "research stance and your computed plan, explain the trade in "
                "2-3 sentences: sizing logic, entry discipline, and what "
                "invalidates it. No preamble.",
                f"Ticker {snap.ticker}. Research: {research.headline} "
                f"(score {research.score:+.2f}).\nPlan: "
                + "; ".join(f"{k}={v}" for k, v in metrics.items()),
            )
            if out:
                return out
        return (f"{action.upper()} {snap.ticker} at {size*100:.1f}% of NAV, "
                f"vol-targeted off research score {research.score:+.2f}; work the "
                f"entry band {metrics['entry band']}, stop at {metrics['stop']}.")
