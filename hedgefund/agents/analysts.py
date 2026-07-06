"""The analyst team — seven seats, one snapshot in, one scored report out.

Mirrors the TradingAgents analyst layer: Technical, Fundamentals, Estimates,
News/Sentiment, Flow/Ownership, Options, and Macro. Each seat is a pure
function of the market snapshot plus optional LLM prose on top.
"""

from __future__ import annotations

from hedgefund.agents.base import Analyst, clamp, fmt
from hedgefund.data.base import MarketSnapshot


class TechnicalAnalyst(Analyst):
    name = "technical"
    role = "Technical Analyst"

    def evaluate(self, snap: MarketSnapshot):
        price = snap.last_close()
        sma50, sma200 = snap.sma(50), snap.sma(200)
        rsi = snap.rsi(14)
        r1m, r3m = snap.total_return(21), snap.total_return(63)
        vol = snap.realized_vol(20)

        score, conf = 0.0, 0.5
        if price and sma200:
            score += 0.35 if price > sma200 else -0.35
            conf += 0.15
        if price and sma50:
            score += 0.20 if price > sma50 else -0.20
        if r3m is not None:
            score += clamp(r3m * 2.0, -0.25, 0.25)
        if rsi is not None:
            if rsi > 75:
                score -= 0.20  # overbought
            elif rsi < 30:
                score += 0.15  # washed out

        trend = "uptrend intact" if score > 0.2 else \
                "downtrend / broken trend" if score < -0.2 else "range-bound"
        metrics = {
            "price": fmt(price),
            "sma50": fmt(sma50),
            "sma200": fmt(sma200),
            "rsi(14)": fmt(rsi, digits=1),
            "1m return": fmt(r1m, pct=True, signed=True),
            "3m return": fmt(r3m, pct=True, signed=True),
            "realized vol (20d, ann.)": fmt(vol, pct=True),
        }
        return score, conf, trend, metrics


class FundamentalsAnalyst(Analyst):
    name = "fundamentals"
    role = "Fundamentals Analyst"

    def evaluate(self, snap: MarketSnapshot):
        f = snap.fundamentals
        score, conf = 0.0, 0.45
        if f.revenue_growth_yoy is not None:
            score += clamp((f.revenue_growth_yoy - 0.08) * 2.0, -0.4, 0.4)
            conf += 0.15
        if f.gross_margin is not None:
            score += clamp((f.gross_margin - 0.40) * 0.8, -0.2, 0.25)
        if f.fcf_yield is not None:
            score += clamp((f.fcf_yield - 0.02) * 8.0, -0.2, 0.2)
        if f.pe_forward is not None:
            growth = f.revenue_growth_yoy or 0.05
            fair_pe = 12 + growth * 60  # crude growth-adjusted anchor
            score += clamp((fair_pe - f.pe_forward) / fair_pe * 0.5, -0.3, 0.3)
            conf += 0.1

        headline = (
            "quality compounder at a defensible multiple" if score > 0.3
            else "deteriorating or expensive fundamentals" if score < -0.3
            else "fundamentals mixed"
        )
        metrics = {
            "fwd P/E": fmt(f.pe_forward, digits=1),
            "rev growth YoY": fmt(f.revenue_growth_yoy, pct=True, signed=True),
            "gross margin": fmt(f.gross_margin, pct=True),
            "op margin": fmt(f.operating_margin, pct=True),
            "FCF yield": fmt(f.fcf_yield, pct=True),
        }
        return score, conf, headline, metrics


class EstimatesAnalyst(Analyst):
    name = "estimates"
    role = "Estimates Analyst"

    def evaluate(self, snap: MarketSnapshot):
        e = snap.estimates
        price = snap.last_close()
        score, conf = 0.0, 0.4
        upside = None
        if e.consensus_target and price:
            upside = e.consensus_target / price - 1.0
            score += clamp(upside * 2.5, -0.5, 0.5)
            conf += 0.2
        if e.rating is not None:
            score += clamp((2.5 - e.rating) * 0.35, -0.4, 0.5)
        if e.analyst_count:
            conf += min(e.analyst_count / 100.0, 0.2)

        headline = (
            "street is on board with upside to target" if score > 0.25
            else "street skeptical / limited upside" if score < -0.25
            else "consensus lukewarm"
        )
        metrics = {
            "analysts": str(e.analyst_count or "n/a"),
            "rating (1=SB..5=S)": fmt(e.rating, digits=2),
            "consensus tgt": fmt(e.consensus_target),
            "upside to tgt": fmt(upside, pct=True, signed=True),
            "next earnings": e.next_earnings_date or "n/a",
        }
        return score, conf, headline, metrics


class NewsSentimentAnalyst(Analyst):
    name = "news"
    role = "News & Sentiment Analyst"

    _POS = ("beat", "beats", "raise", "raised", "record", "strong", "buyback",
            "upgrade", "hike", "hikes", "wins", "ahead", "expand", "expanded")
    _NEG = ("miss", "cuts", "cut", "probe", "lawsuit", "recall", "weak",
            "downgrade", "scrutiny", "pressure", "constraint", "constraints",
            "selling", "clouds", "weighs")

    def evaluate(self, snap: MarketSnapshot):
        if not snap.news:
            return 0.0, 0.15, "no news flow", {"headlines": "0"}
        scored = []
        for item in snap.news:
            if item.sentiment is not None:
                scored.append(item.sentiment)
                continue
            title = item.title.lower()
            s = sum(w in title for w in self._POS) - sum(w in title for w in self._NEG)
            scored.append(clamp(s * 0.4))
        avg = sum(scored) / len(scored)
        pos = sum(1 for s in scored if s > 0.1)
        neg = sum(1 for s in scored if s < -0.1)
        headline = (
            "tape is constructive" if avg > 0.15
            else "narrative turning against the name" if avg < -0.15
            else "news flow balanced"
        )
        metrics = {
            "headlines scanned": str(len(scored)),
            "positive / negative": f"{pos} / {neg}",
            "avg sentiment": fmt(avg, digits=2),
            "latest": snap.news[0].title[:70],
        }
        return clamp(avg * 1.6), 0.35 + min(len(scored), 8) * 0.03, headline, metrics


class FlowOwnershipAnalyst(Analyst):
    name = "flow"
    role = "Flow & Ownership Analyst"

    def evaluate(self, snap: MarketSnapshot):
        o = snap.ownership
        score, conf = 0.0, 0.35
        if o.short_pct_float is not None:
            if o.short_pct_float > 15:
                score -= 0.35  # crowded short = controversy (and squeeze fuel)
            elif o.short_pct_float < 3:
                score += 0.20
            conf += 0.15
        if o.institutional_pct is not None:
            score += clamp((o.institutional_pct - 0.5) * 0.4, -0.15, 0.2)
        if o.insider_net_buys_3m is not None:
            score += clamp(o.insider_net_buys_3m * 0.06, -0.25, 0.25)
            conf += 0.1

        headline = (
            "ownership base supportive, no crowding" if score > 0.2
            else "positioning is a headwind" if score < -0.2
            else "positioning neutral"
        )
        metrics = {
            "short % float": fmt(o.short_pct_float, digits=1),
            "institutional %": fmt(o.institutional_pct, pct=True),
            "days to cover": fmt(o.days_to_cover, digits=1),
            "insider net buys (3m)": str(o.insider_net_buys_3m
                                         if o.insider_net_buys_3m is not None else "n/a"),
        }
        return score, conf, headline, metrics


class OptionsAnalyst(Analyst):
    name = "options"
    role = "Options Analyst"

    def evaluate(self, snap: MarketSnapshot):
        op = snap.options
        rv = snap.realized_vol(20)
        score, conf = 0.0, 0.3
        vol_premium = None
        if op.atm_iv_1m is not None and rv:
            vol_premium = op.atm_iv_1m - rv
            # rich IV vs realized = market braced for a move; mild negative
            score += clamp(-vol_premium * 1.5, -0.2, 0.2)
            conf += 0.15
        if op.call_put_volume_ratio is not None:
            score += clamp((op.call_put_volume_ratio - 1.0) * 0.3, -0.3, 0.3)
            conf += 0.1
        if op.skew_25d is not None:
            score += clamp(-op.skew_25d * 4.0, -0.2, 0.1)

        headline = (
            "options market leaning bullish" if score > 0.15
            else "downside hedging demand elevated" if score < -0.15
            else "vol surface unremarkable"
        )
        metrics = {
            "ATM IV (1m)": fmt(op.atm_iv_1m, pct=True),
            "IV - realized": fmt(vol_premium, pct=True, signed=True),
            "call/put volume": fmt(op.call_put_volume_ratio, digits=2),
            "25d skew": fmt(op.skew_25d, pct=True, signed=True),
        }
        return score, conf, headline, metrics


class MacroAnalyst(Analyst):
    name = "macro"
    role = "Macro Analyst"

    def evaluate(self, snap: MarketSnapshot):
        m = snap.macro
        beta = snap.fundamentals.beta or 1.0
        score, conf = 0.0, 0.3
        if m.spy_return_1m is not None:
            score += clamp(m.spy_return_1m * 6.0, -0.3, 0.3)
            conf += 0.1
        if m.vix is not None:
            if m.vix < 17:
                score += 0.15
            elif m.vix > 25:
                score -= 0.3
            conf += 0.1
        if m.ten_year_change_1m is not None:
            # rising rates hurt long-duration/high-beta names more
            score += clamp(-m.ten_year_change_1m * 2.0 * beta, -0.3, 0.2)
        if m.sector_return_1m is not None and m.spy_return_1m is not None:
            score += clamp((m.sector_return_1m - m.spy_return_1m) * 5.0, -0.2, 0.2)

        headline = (
            "macro tailwind for risk assets" if score > 0.2
            else "macro regime hostile" if score < -0.2
            else "macro neutral for the name"
        )
        metrics = {
            "10y yield": (fmt(m.ten_year_yield, digits=2) + "%") if m.ten_year_yield is not None else "n/a",
            "10y chg (1m)": (f"{m.ten_year_change_1m:+.2f}pp") if m.ten_year_change_1m is not None else "n/a",
            "VIX": fmt(m.vix, digits=1),
            "SPY 1m": fmt(m.spy_return_1m, pct=True, signed=True),
            "sector 1m": fmt(m.sector_return_1m, pct=True, signed=True),
            "beta": fmt(beta, digits=2),
        }
        return score, conf, headline, metrics


ALL_ANALYSTS = [
    TechnicalAnalyst,
    FundamentalsAnalyst,
    EstimatesAnalyst,
    NewsSentimentAnalyst,
    FlowOwnershipAnalyst,
    OptionsAnalyst,
    MacroAnalyst,
]
