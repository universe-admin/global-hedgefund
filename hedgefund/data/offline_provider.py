"""Deterministic offline market data.

Used for demos, CI, and as the last-resort fallback when neither OpenBB nor
yfinance is available. Prices are generated with a seeded geometric random
walk so the same ticker always produces the same tape; a handful of large
names carry curated, plausible fundamentals so demo runs read realistically.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import random
from typing import Dict

from hedgefund.data.base import (
    Estimates,
    Fundamentals,
    MacroSnapshot,
    MarketDataProvider,
    MarketSnapshot,
    NewsItem,
    OptionsSnapshot,
    OwnershipSnapshot,
    PriceBar,
)

# Curated anchor profiles: price, drift, vol, and fundamental colour.
_PROFILES: Dict[str, dict] = {
    "NVDA": dict(price=193.0, drift=0.35, vol=0.50, name="NVIDIA Corporation",
                 sector="Semiconductors", pe_f=32.0, rev_yoy=0.62, gm=0.74,
                 fcf_yield=0.019, beta=2.2, rating=1.30, tgt_prem=0.09,
                 analysts=56, short=1.7, inst=0.78, sent=0.35),
    "AAPL": dict(price=232.0, drift=0.10, vol=0.24, name="Apple Inc.",
                 sector="Consumer Electronics", pe_f=28.0, rev_yoy=0.06, gm=0.46,
                 fcf_yield=0.031, beta=1.2, rating=2.0, tgt_prem=0.06,
                 analysts=44, short=0.8, inst=0.62, sent=0.10),
    "MSFT": dict(price=470.0, drift=0.14, vol=0.24, name="Microsoft Corporation",
                 sector="Software", pe_f=31.0, rev_yoy=0.15, gm=0.69,
                 fcf_yield=0.024, beta=1.1, rating=1.5, tgt_prem=0.10,
                 analysts=55, short=0.7, inst=0.74, sent=0.25),
    "GOOG": dict(price=199.0, drift=0.13, vol=0.28, name="Alphabet Inc.",
                 sector="Internet", pe_f=21.0, rev_yoy=0.13, gm=0.58,
                 fcf_yield=0.033, beta=1.1, rating=1.6, tgt_prem=0.11,
                 analysts=50, short=0.9, inst=0.80, sent=0.15),
    "MU":   dict(price=95.5, drift=0.12, vol=0.55, name="Micron Technology",
                 sector="Semiconductors", pe_f=11.0, rev_yoy=0.55, gm=0.35,
                 fcf_yield=0.020, beta=1.6, rating=1.7, tgt_prem=0.20,
                 analysts=38, short=2.8, inst=0.81, sent=0.05),
    "TSLA": dict(price=315.0, drift=0.05, vol=0.62, name="Tesla, Inc.",
                 sector="Automobiles", pe_f=95.0, rev_yoy=0.02, gm=0.18,
                 fcf_yield=0.006, beta=2.1, rating=2.8, tgt_prem=-0.08,
                 analysts=45, short=2.9, inst=0.47, sent=-0.05),
}

_HEADLINES_POS = [
    "{t} beats consensus on datacenter demand; guidance raised",
    "{t} announces expanded buyback and capacity ramp",
    "Sell-side hikes {t} targets after strong channel checks",
    "{t} unveils next-gen product cycle ahead of schedule",
]
_HEADLINES_NEG = [
    "{t} flags supply constraints into next quarter",
    "Regulatory scrutiny weighs on {t} shares",
    "Competitor pricing pressure clouds {t} margin outlook",
    "{t} insider selling picks up after rally",
]


def _seed_for(ticker: str) -> int:
    return int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:8], 16)


class OfflineProvider(MarketDataProvider):
    name = "offline"

    def available(self) -> bool:
        return True

    def snapshot(self, ticker: str, lookback_days: int = 300) -> MarketSnapshot:
        t = ticker.upper()
        rng = random.Random(_seed_for(t))
        prof = _PROFILES.get(t) or self._generic_profile(t, rng)

        today = dt.date(2026, 7, 3)  # fixed anchor: fully deterministic tape
        bars = self._walk(prof, rng, today, lookback_days)
        price = bars[-1].close

        f = Fundamentals(
            market_cap=price * rng.uniform(0.5e9, 3.0e9),
            pe_forward=prof["pe_f"],
            pe_trailing=prof["pe_f"] * rng.uniform(1.05, 1.35),
            revenue_growth_yoy=prof["rev_yoy"],
            revenue_growth_qoq=prof["rev_yoy"] / 4 * rng.uniform(0.6, 1.4),
            gross_margin=prof["gm"],
            operating_margin=max(0.02, prof["gm"] - rng.uniform(0.15, 0.30)),
            fcf_yield=prof["fcf_yield"],
            net_debt_to_ebitda=rng.uniform(-1.5, 1.5),
            beta=prof["beta"],
        )
        f.revenue_ttm = f.market_cap / max(prof["pe_f"], 5.0) * rng.uniform(2.5, 4.0)
        f.fcf_ttm = f.market_cap * prof["fcf_yield"]

        est = Estimates(
            analyst_count=prof["analysts"],
            rating=prof["rating"],
            consensus_target=round(price * (1 + prof["tgt_prem"]), 2),
            eps_next_year_growth=prof["rev_yoy"] * rng.uniform(0.8, 1.4),
            next_earnings_date=str(today + dt.timedelta(days=rng.randint(10, 60))),
        )

        news = []
        for i in range(6):
            pos = rng.random() < 0.5 + prof["sent"] / 2
            pool = _HEADLINES_POS if pos else _HEADLINES_NEG
            news.append(
                NewsItem(
                    date=str(today - dt.timedelta(days=i * 2 + rng.randint(0, 1))),
                    title=rng.choice(pool).format(t=t),
                    sentiment=round(
                        (1 if pos else -1) * rng.uniform(0.2, 0.8), 2
                    ),
                )
            )

        opts = OptionsSnapshot(
            atm_iv_1m=prof["vol"] * rng.uniform(0.9, 1.2),
            call_put_volume_ratio=rng.uniform(0.7, 1.8) + prof["sent"] * 0.5,
            open_interest_change_1w=rng.uniform(-0.1, 0.25),
            skew_25d=rng.uniform(-0.01, 0.06),
        )
        own = OwnershipSnapshot(
            short_pct_float=prof["short"],
            institutional_pct=prof["inst"],
            days_to_cover=round(rng.uniform(1.0, 4.0), 1),
            insider_net_buys_3m=rng.randint(-6, 4),
        )
        macro = MacroSnapshot(
            ten_year_yield=4.37,
            ten_year_change_1m=-0.02,
            vix=15.8,
            vix_change_1m=0.12,
            spy_return_1m=0.021,
            sector_return_1m=0.021 + prof["sent"] * 0.02,
            dxy_return_1m=-0.018,
        )

        return MarketSnapshot(
            ticker=t,
            as_of=str(today),
            provider=self.name,
            company_name=prof["name"],
            sector=prof["sector"],
            price=price,
            bars=bars,
            fundamentals=f,
            estimates=est,
            news=news,
            options=opts,
            ownership=own,
            macro=macro,
        )

    # ---- internals ----

    @staticmethod
    def _generic_profile(t: str, rng: random.Random) -> dict:
        sent = rng.uniform(-0.3, 0.4)
        return dict(
            price=rng.uniform(15, 400),
            drift=rng.uniform(-0.05, 0.25),
            vol=rng.uniform(0.22, 0.60),
            name=f"{t} Corp.",
            sector=rng.choice(
                ["Software", "Semiconductors", "Healthcare",
                 "Industrials", "Energy", "Financials", "Consumer"]
            ),
            pe_f=rng.uniform(9, 45),
            rev_yoy=rng.uniform(-0.05, 0.45),
            gm=rng.uniform(0.25, 0.75),
            fcf_yield=rng.uniform(0.005, 0.06),
            beta=rng.uniform(0.7, 2.2),
            rating=rng.uniform(1.3, 3.2),
            tgt_prem=rng.uniform(-0.10, 0.25),
            analysts=rng.randint(4, 45),
            short=rng.uniform(0.5, 12.0),
            inst=rng.uniform(0.3, 0.9),
            sent=sent,
        )

    @staticmethod
    def _walk(prof: dict, rng: random.Random, today, days: int):
        daily_drift = prof["drift"] / 252
        daily_vol = prof["vol"] / math.sqrt(252)
        # Walk backwards from the anchor price so the last close matches.
        closes = [prof["price"]]
        for _ in range(days - 1):
            shock = rng.gauss(daily_drift, daily_vol)
            closes.append(closes[-1] / math.exp(shock))
        closes.reverse()

        bars = []
        d = today - dt.timedelta(days=int(days * 1.45))
        i = 0
        while i < len(closes):
            if d.weekday() < 5:  # trading days only
                c = closes[i]
                o = c * math.exp(rng.gauss(0, daily_vol / 2))
                hi = max(o, c) * (1 + abs(rng.gauss(0, daily_vol / 2)))
                lo = min(o, c) * (1 - abs(rng.gauss(0, daily_vol / 2)))
                vol = rng.uniform(0.5, 2.0) * 1e7
                bars.append(PriceBar(str(d), round(o, 2), round(hi, 2),
                                     round(lo, 2), round(c, 2), round(vol)))
                i += 1
            d += dt.timedelta(days=1)
        # Ensure the tape ends exactly on the anchor date/price.
        bars[-1].date = str(today)
        bars[-1].close = round(prof["price"], 2)
        return bars
