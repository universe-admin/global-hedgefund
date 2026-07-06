"""Data-layer contracts: the typed snapshot every agent consumes.

A provider (OpenBB, yfinance, offline) fills in whatever it can; agents are
written to degrade gracefully when a field is ``None``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PriceBar:
    date: str  # ISO date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Fundamentals:
    market_cap: Optional[float] = None
    pe_forward: Optional[float] = None
    pe_trailing: Optional[float] = None
    revenue_growth_qoq: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    fcf_yield: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    revenue_ttm: Optional[float] = None
    fcf_ttm: Optional[float] = None
    beta: Optional[float] = None


@dataclass
class Estimates:
    analyst_count: Optional[int] = None
    rating: Optional[float] = None          # 1 = strong buy .. 5 = sell
    consensus_target: Optional[float] = None
    eps_next_year_growth: Optional[float] = None
    next_earnings_date: Optional[str] = None


@dataclass
class NewsItem:
    date: str
    title: str
    sentiment: Optional[float] = None  # -1 .. 1


@dataclass
class OptionsSnapshot:
    atm_iv_1m: Optional[float] = None
    call_put_volume_ratio: Optional[float] = None
    open_interest_change_1w: Optional[float] = None
    skew_25d: Optional[float] = None  # put IV minus call IV; >0 = downside fear


@dataclass
class OwnershipSnapshot:
    short_pct_float: Optional[float] = None
    institutional_pct: Optional[float] = None
    days_to_cover: Optional[float] = None
    insider_net_buys_3m: Optional[int] = None  # buy tx minus sell tx


@dataclass
class MacroSnapshot:
    ten_year_yield: Optional[float] = None
    ten_year_change_1m: Optional[float] = None
    vix: Optional[float] = None
    vix_change_1m: Optional[float] = None
    spy_return_1m: Optional[float] = None
    sector_return_1m: Optional[float] = None
    dxy_return_1m: Optional[float] = None


@dataclass
class MarketSnapshot:
    """Everything the desk knows about one ticker at one moment."""

    ticker: str
    as_of: str
    provider: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    price: Optional[float] = None
    bars: List[PriceBar] = field(default_factory=list)  # daily, oldest first
    fundamentals: Fundamentals = field(default_factory=Fundamentals)
    estimates: Estimates = field(default_factory=Estimates)
    news: List[NewsItem] = field(default_factory=list)
    options: OptionsSnapshot = field(default_factory=OptionsSnapshot)
    ownership: OwnershipSnapshot = field(default_factory=OwnershipSnapshot)
    macro: MacroSnapshot = field(default_factory=MacroSnapshot)

    # ---- derived series helpers (pure, no numpy needed) ----

    def closes(self) -> List[float]:
        return [b.close for b in self.bars]

    def last_close(self) -> Optional[float]:
        if self.price is not None:
            return self.price
        return self.bars[-1].close if self.bars else None

    def sma(self, window: int) -> Optional[float]:
        c = self.closes()
        if len(c) < window:
            return None
        return sum(c[-window:]) / window

    def total_return(self, days: int) -> Optional[float]:
        c = self.closes()
        if len(c) <= days:
            return None
        past, now = c[-1 - days], c[-1]
        return now / past - 1.0 if past else None

    def rsi(self, window: int = 14) -> Optional[float]:
        c = self.closes()
        if len(c) < window + 1:
            return None
        gains = losses = 0.0
        for prev, cur in zip(c[-window - 1 : -1], c[-window:]):
            d = cur - prev
            if d >= 0:
                gains += d
            else:
                losses -= d
        if losses == 0:
            return 100.0
        rs = (gains / window) / (losses / window)
        return 100.0 - 100.0 / (1.0 + rs)

    def realized_vol(self, window: int = 20) -> Optional[float]:
        """Annualized close-to-close volatility."""
        c = self.closes()
        if len(c) < window + 1:
            return None
        rets = [
            math.log(cur / prev)
            for prev, cur in zip(c[-window - 1 : -1], c[-window:])
            if prev > 0 and cur > 0
        ]
        if len(rets) < 2:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(var) * math.sqrt(252)

    def high_water_mark(self, days: int = 252) -> Optional[float]:
        c = self.closes()
        if not c:
            return None
        return max(c[-days:])


class MarketDataProvider:
    """Interface every data adapter implements."""

    name = "abstract"

    def available(self) -> bool:
        raise NotImplementedError

    def snapshot(self, ticker: str, lookback_days: int = 300) -> MarketSnapshot:
        raise NotImplementedError
