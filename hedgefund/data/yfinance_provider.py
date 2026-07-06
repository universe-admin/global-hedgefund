"""yfinance adapter — the free local data path.

Import of ``yfinance`` is guarded so the package works without it installed.
Any field we can't fetch stays ``None`` and the agents degrade gracefully.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

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

try:  # pragma: no cover - exercised only when yfinance is installed
    import yfinance as _yf
except Exception:  # ImportError or any env-specific failure
    _yf = None


def _safe(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def available(self) -> bool:
        return _yf is not None

    def snapshot(self, ticker: str, lookback_days: int = 300) -> MarketSnapshot:  # pragma: no cover
        if _yf is None:
            raise RuntimeError("yfinance is not installed (pip install .[data])")
        t = ticker.upper()
        tk = _yf.Ticker(t)
        hist = tk.history(period=f"{max(lookback_days, 60)}d", auto_adjust=True)
        bars = [
            PriceBar(
                date=str(idx.date()),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
            for idx, row in hist.iterrows()
        ]

        info = {}
        try:
            info = tk.info or {}
        except Exception:
            pass

        fundamentals = Fundamentals(
            market_cap=_safe(info, "marketCap"),
            pe_forward=_safe(info, "forwardPE"),
            pe_trailing=_safe(info, "trailingPE"),
            revenue_growth_yoy=_safe(info, "revenueGrowth"),
            gross_margin=_safe(info, "grossMargins"),
            operating_margin=_safe(info, "operatingMargins"),
            revenue_ttm=_safe(info, "totalRevenue"),
            fcf_ttm=_safe(info, "freeCashflow"),
            beta=_safe(info, "beta"),
        )
        if fundamentals.fcf_ttm and fundamentals.market_cap:
            fundamentals.fcf_yield = fundamentals.fcf_ttm / fundamentals.market_cap

        estimates = Estimates(
            analyst_count=int(info["numberOfAnalystOpinions"])
            if info.get("numberOfAnalystOpinions") else None,
            rating=_safe(info, "recommendationMean"),
            consensus_target=_safe(info, "targetMeanPrice"),
        )

        news = []
        try:
            for item in (tk.news or [])[:8]:
                content = item.get("content", item)
                title = content.get("title") or ""
                date = str(content.get("pubDate", ""))[:10] or str(dt.date.today())
                if title:
                    news.append(NewsItem(date=date, title=title))
        except Exception:
            pass

        ownership = OwnershipSnapshot(
            short_pct_float=(_safe(info, "shortPercentOfFloat") or 0) * 100
            if info.get("shortPercentOfFloat") else None,
            institutional_pct=_safe(info, "heldPercentInstitutions"),
            days_to_cover=_safe(info, "shortRatio"),
        )

        options = OptionsSnapshot()
        try:
            expiries = tk.options
            if expiries:
                chain = tk.option_chain(expiries[0])
                spot = bars[-1].close if bars else _safe(info, "currentPrice")
                if spot:
                    calls, puts = chain.calls, chain.puts
                    atm_call = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
                    if len(atm_call):
                        options.atm_iv_1m = float(atm_call["impliedVolatility"].iloc[0])
                    cv, pv = calls["volume"].sum(), puts["volume"].sum()
                    if pv:
                        options.call_put_volume_ratio = float(cv / pv)
        except Exception:
            pass

        macro = MacroSnapshot()
        try:
            spy = _yf.Ticker("SPY").history(period="40d")["Close"]
            if len(spy) > 21:
                macro.spy_return_1m = float(spy.iloc[-1] / spy.iloc[-22] - 1)
            vix = _yf.Ticker("^VIX").history(period="40d")["Close"]
            if len(vix) > 21:
                macro.vix = float(vix.iloc[-1])
                macro.vix_change_1m = float(vix.iloc[-1] / vix.iloc[-22] - 1)
            tnx = _yf.Ticker("^TNX").history(period="40d")["Close"]
            if len(tnx) > 21:
                macro.ten_year_yield = float(tnx.iloc[-1] / 10)
                macro.ten_year_change_1m = float((tnx.iloc[-1] - tnx.iloc[-22]) / 10)
        except Exception:
            pass

        return MarketSnapshot(
            ticker=t,
            as_of=str(dt.date.today()),
            provider=self.name,
            company_name=info.get("shortName") or info.get("longName"),
            sector=info.get("sector"),
            price=bars[-1].close if bars else _safe(info, "currentPrice"),
            bars=bars,
            fundamentals=fundamentals,
            estimates=estimates,
            news=news,
            options=options,
            ownership=ownership,
            macro=macro,
        )
