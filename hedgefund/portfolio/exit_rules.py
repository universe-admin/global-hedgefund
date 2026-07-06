"""Exit-Rule Engine: every open position is checked against pre-set rules.

Rules (all armed by default):
  1. hard stop        — price below the position's stop
  2. trailing stop    — drawdown from high-water mark beyond policy
  3. trend break      — close below the 200-day moving average
  4. time stop        — position older than policy with negative P&L
  5. target reached   — stretch target hit (take-profit review)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketSnapshot
from hedgefund.portfolio.book import Position


@dataclass
class ExitSignal:
    rule: str
    triggered: bool
    detail: str
    severity: str = "info"  # info | warn | exit


@dataclass
class ExitCheck:
    ticker: str
    price: float
    signals: List[ExitSignal] = field(default_factory=list)

    @property
    def exits_triggered(self) -> List[ExitSignal]:
        return [s for s in self.signals if s.triggered and s.severity == "exit"]

    @property
    def warnings(self) -> List[ExitSignal]:
        return [s for s in self.signals if s.triggered and s.severity == "warn"]

    def status(self) -> str:
        if self.exits_triggered:
            return "EXIT"
        if self.warnings:
            return "ON WATCH"
        return "HOLD"


class ExitRuleEngine:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    def check(self, position: Position, snap: MarketSnapshot) -> ExitCheck:
        price = snap.last_close() or position.entry_price
        out = ExitCheck(ticker=position.ticker, price=price)

        # 1. hard stop
        if position.stop is not None:
            hit = price <= position.stop
            out.signals.append(ExitSignal(
                "hard stop", hit,
                f"price {price:.2f} vs stop {position.stop:.2f}",
                "exit" if hit else "info"))

        # 2. trailing stop from the position's own high-water mark since
        # entry (maintained by Book.mark) — NOT the stock's 52-week high,
        # which would instantly stop out anything bought below a prior peak.
        hwm = max(filter(None, [position.high_water_mark,
                                position.entry_price, price]))
        dd = 1.0 - price / hwm if hwm else 0.0
        trail_hit = dd >= self.config.trailing_stop_pct
        out.signals.append(ExitSignal(
            "trailing stop", trail_hit,
            f"{dd*100:.1f}% off HWM {hwm:.2f} "
            f"(limit {self.config.trailing_stop_pct*100:.0f}%)",
            "exit" if trail_hit else ("warn" if dd >= self.config.trailing_stop_pct * 0.6
                                      else "info")))
        # keep the flag honest: a warn-level drawdown is "triggered" as a warning
        if not trail_hit and dd >= self.config.trailing_stop_pct * 0.6:
            out.signals[-1].triggered = True

        # 3. trend break (200-day MA)
        sma200 = snap.sma(200)
        if sma200:
            below = price < sma200
            out.signals.append(ExitSignal(
                "trend break (200dma)", below,
                f"price {price:.2f} vs 200dma {sma200:.2f}",
                "warn" if below else "info"))

        # 4. time stop
        age = position.age_days()
        pnl = position.unrealized_return(price)
        stale = age > self.config.time_stop_days and pnl < 0
        out.signals.append(ExitSignal(
            "time stop", stale,
            f"{age}d old, P&L {pnl*100:+.1f}% "
            f"(limit {self.config.time_stop_days}d if negative)",
            "exit" if stale else "info"))

        # 5. stretch target reached — review, don't auto-dump
        if position.target_stretch:
            hit = price >= position.target_stretch
            out.signals.append(ExitSignal(
                "stretch target", hit,
                f"price {price:.2f} vs stretch {position.target_stretch:.2f}",
                "warn" if hit else "info"))

        return out
