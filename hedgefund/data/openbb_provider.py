"""OpenBB Platform adapter — the "open-source Bloomberg Terminal" path.

Uses the OpenBB Platform Python API (``from openbb import obb``) when the
``openbb`` extra is installed. Every call is individually guarded: OpenBB
routes to many upstream providers and any one of them can fail or require a
key, so we take what we can get and leave the rest ``None``.
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

try:  # pragma: no cover - exercised only when openbb is installed
    from openbb import obb as _obb
except Exception:
    _obb = None


def _first(results) -> Optional[object]:
    try:
        rows = results.results
        return rows[0] if rows else None
    except Exception:
        return None


def _get(obj, attr: str) -> Optional[float]:
    v = getattr(obj, attr, None)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class OpenBBProvider(MarketDataProvider):
    name = "openbb"

    def available(self) -> bool:
        return _obb is not None

    def snapshot(self, ticker: str, lookback_days: int = 300) -> MarketSnapshot:  # pragma: no cover
        if _obb is None:
            raise RuntimeError("openbb is not installed (pip install .[openbb])")
        t = ticker.upper()
        today = dt.date.today()
        start = today - dt.timedelta(days=int(lookback_days * 1.5))

        bars = []
        try:
            hist = _obb.equity.price.historical(
                symbol=t, start_date=str(start), interval="1d"
            ).results
            for row in hist:
                bars.append(
                    PriceBar(
                        date=str(getattr(row, "date", ""))[:10],
                        open=_get(row, "open") or 0.0,
                        high=_get(row, "high") or 0.0,
                        low=_get(row, "low") or 0.0,
                        close=_get(row, "close") or 0.0,
                        volume=_get(row, "volume") or 0.0,
                    )
                )
        except Exception:
            pass

        fundamentals = Fundamentals()
        company_name = sector = None
        try:
            prof = _first(_obb.equity.profile(symbol=t))
            if prof is not None:
                company_name = getattr(prof, "name", None)
                sector = getattr(prof, "sector", None)
                fundamentals.market_cap = _get(prof, "market_cap")
                fundamentals.beta = _get(prof, "beta")
        except Exception:
            pass
        try:
            m = _first(_obb.equity.fundamental.metrics(symbol=t))
            if m is not None:
                fundamentals.pe_forward = _get(m, "forward_pe") or _get(m, "pe_ratio")
                fundamentals.pe_trailing = _get(m, "pe_ratio")
                fundamentals.fcf_yield = _get(m, "free_cash_flow_yield")
                fundamentals.revenue_growth_yoy = _get(m, "revenue_growth")
                fundamentals.gross_margin = _get(m, "gross_margin")
                fundamentals.operating_margin = _get(m, "operating_margin")
        except Exception:
            pass

        estimates = Estimates()
        try:
            pt = _first(_obb.equity.estimates.consensus(symbol=t))
            if pt is not None:
                estimates.consensus_target = _get(pt, "target_consensus")
                estimates.analyst_count = (
                    int(getattr(pt, "target_number", 0) or 0) or None
                )
        except Exception:
            pass

        news = []
        try:
            for row in _obb.news.company(symbol=t, limit=8).results:
                title = getattr(row, "title", None)
                if title:
                    news.append(
                        NewsItem(date=str(getattr(row, "date", ""))[:10], title=title)
                    )
        except Exception:
            pass

        ownership = OwnershipSnapshot()
        try:
            sh = _first(_obb.equity.shorts.short_interest(symbol=t))
            if sh is not None:
                ownership.short_pct_float = _get(sh, "short_percent_of_float")
                ownership.days_to_cover = _get(sh, "days_to_cover")
        except Exception:
            pass
        try:
            rows = _obb.equity.ownership.insider_trading(symbol=t, limit=50).results
            buys = sum(
                1 for r in rows
                if "buy" in str(getattr(r, "transaction_type", "")).lower()
            )
            sells = sum(
                1 for r in rows
                if "sale" in str(getattr(r, "transaction_type", "")).lower()
            )
            ownership.insider_net_buys_3m = buys - sells
        except Exception:
            pass

        options = OptionsSnapshot()
        try:
            chain = _obb.derivatives.options.chains(symbol=t).results
            spot = bars[-1].close if bars else None
            if chain and spot:
                near = [
                    r for r in chain
                    if abs((_get(r, "strike") or 0) - spot) / spot < 0.03
                ]
                ivs = [
                    _get(r, "implied_volatility")
                    for r in near
                    if _get(r, "implied_volatility")
                ]
                if ivs:
                    options.atm_iv_1m = sum(ivs) / len(ivs)
                cv = sum((_get(r, "volume") or 0) for r in chain
                         if str(getattr(r, "option_type", "")).lower() == "call")
                pv = sum((_get(r, "volume") or 0) for r in chain
                         if str(getattr(r, "option_type", "")).lower() == "put")
                if pv:
                    options.call_put_volume_ratio = cv / pv
        except Exception:
            pass

        macro = MacroSnapshot()
        try:
            spy = _obb.equity.price.historical(
                symbol="SPY", start_date=str(today - dt.timedelta(days=45))
            ).results
            if len(spy) > 21:
                macro.spy_return_1m = float(spy[-1].close / spy[-22].close - 1)
        except Exception:
            pass

        return MarketSnapshot(
            ticker=t,
            as_of=str(today),
            provider=self.name,
            company_name=company_name,
            sector=sector,
            price=bars[-1].close if bars else None,
            bars=bars,
            fundamentals=fundamentals,
            estimates=estimates,
            news=news,
            options=options,
            ownership=ownership,
            macro=macro,
        )
