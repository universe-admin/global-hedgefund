"""Walk-forward backtest + calibrated next-day prediction.

Protocol per ticker, per day t (prequential, zero look-ahead):

    1. build features from bars[0..t] (+ lead-market bars strictly before t)
    2. model predicts P(up tomorrow)
    3. after a burn-in, the prediction is scored against the realized label
    4. only then does the model update on (features_t, label_t)

The same trained model then emits tomorrow's probability, and the report
maps it to the *backtested* hit rate of that probability bucket — so every
prediction ships with the accuracy it actually earned, not a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from hedgefund.backtest.features import (
    FEATURE_NAMES,
    WARMUP,
    build_lead_returns,
    features_at,
    label_at,
)
from hedgefund.backtest.model import OnlineLogit
from hedgefund.backtest.universes import UNIVERSES
from hedgefund.data.base import MarketDataProvider

BURN_IN = 120        # model must have learned this many days before scoring
LONG_TH, SHORT_TH = 0.55, 0.45


@dataclass
class TickerResult:
    ticker: str
    n_scored: int
    accuracy: float           # directional hit rate at 0.5 threshold
    baseline: float           # always-predict-up hit rate (the bar to beat)
    brier: float              # mean squared prob error (lower = better)
    strategy_return: float    # long>0.55 / short<0.45 next-day compounding
    buy_hold_return: float    # same window, always long
    prob_up_tomorrow: Optional[float] = None
    expected_move_pct: Optional[float] = None  # ~1 sigma next-day move
    last_date: Optional[str] = None


@dataclass
class BacktestReport:
    exchange: str
    results: List[TickerResult] = field(default_factory=list)
    calibration: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pooled_accuracy: float = 0.0
    pooled_baseline: float = 0.0
    pooled_brier: float = 0.0
    n_scored: int = 0

    def bucket_hit_rate(self, prob: float) -> Optional[float]:
        b = _bucket(prob)
        stats = self.calibration.get(b)
        return stats["realized_up_rate"] if stats else None


@dataclass
class Prediction:
    ticker: str
    as_of: str
    prob_up: float
    direction: str            # UP | DOWN | FLAT/NO-EDGE
    expected_move_pct: float
    backtested_bucket_hit_rate: Optional[float]
    n_backtest_days: int


def _bucket(p: float) -> str:
    lo = int(p * 10) * 10
    return f"{lo}-{lo + 10}%"


def _run_single(bars, lead_rets, collect_calib: Dict[str, List[int]]):
    """Walk one tape; returns (scored list, trained model, last feature x)."""
    model = OnlineLogit(len(FEATURE_NAMES))
    scored = []  # (prob, label, next_ret)
    closes = [b.close for b in bars]
    last_x = None
    for t in range(WARMUP, len(bars)):
        x = features_at(bars, t, lead_rets)
        if x is None:
            continue
        last_x = x
        label = label_at(bars, t)
        if label is None:
            break  # last bar: features exist but tomorrow doesn't yet
        p = model.predict_proba(x)
        if model.n_updates >= BURN_IN:
            next_ret = closes[t + 1] / closes[t] - 1.0
            scored.append((p, label, next_ret))
            collect_calib.setdefault(_bucket(p), []).append(label)
        model.update(x, label)
    return scored, model, last_x


def _summarize(ticker, bars, scored, model, last_x) -> TickerResult:
    n = len(scored)
    if n:
        acc = sum(1 for p, y, _ in scored if (p >= 0.5) == (y == 1)) / n
        base = sum(y for _, y, _ in scored) / n
        brier = sum((p - y) ** 2 for p, y, _ in scored) / n
        strat = bh = 1.0
        for p, _, r in scored:
            bh *= 1 + r
            if p > LONG_TH:
                strat *= 1 + r
            elif p < SHORT_TH:
                strat *= 1 - r
    else:
        acc = base = brier = 0.0
        strat = bh = 1.0

    prob = model.predict_proba(last_x) if last_x is not None else None
    exp_move = None
    if len(bars) > 21:
        closes = [b.close for b in bars]
        rets = [abs(closes[i] / closes[i - 1] - 1.0)
                for i in range(len(closes) - 20, len(closes))]
        exp_move = sum(rets) / len(rets)

    return TickerResult(
        ticker=ticker,
        n_scored=n,
        accuracy=round(acc, 4),
        baseline=round(max(base, 1 - base), 4),
        brier=round(brier, 4),
        strategy_return=round(strat - 1, 4),
        buy_hold_return=round(bh - 1, 4),
        prob_up_tomorrow=round(prob, 4) if prob is not None else None,
        expected_move_pct=round(exp_move, 4) if exp_move is not None else None,
        last_date=bars[-1].date if bars else None,
    )


def run_backtest(exchange: str, provider: MarketDataProvider,
                 lookback_days: int = 900,
                 tickers: Optional[List[str]] = None) -> BacktestReport:
    uni = UNIVERSES.get(exchange)
    if uni is None and tickers is None:
        raise ValueError(f"unknown exchange {exchange!r}; "
                         f"pick from {sorted(UNIVERSES)}")
    symbols = tickers or uni["tickers"]
    lead_symbol = uni["lead"] if uni else None

    lead_rets = None
    if lead_symbol:
        lead_bars = provider.snapshot(lead_symbol, lookback_days).bars
        lead_rets = build_lead_returns(lead_bars)

    report = BacktestReport(exchange=exchange)
    calib: Dict[str, List[int]] = {}
    all_scored = []
    for sym in symbols:
        bars = provider.snapshot(sym, lookback_days).bars
        if len(bars) < WARMUP + BURN_IN + 20:
            continue
        scored, model, last_x = _run_single(bars, lead_rets, calib)
        all_scored.extend(scored)
        report.results.append(_summarize(sym, bars, scored, model, last_x))

    n = len(all_scored)
    if n:
        report.n_scored = n
        report.pooled_accuracy = round(
            sum(1 for p, y, _ in all_scored if (p >= 0.5) == (y == 1)) / n, 4)
        up = sum(y for _, y, _ in all_scored) / n
        report.pooled_baseline = round(max(up, 1 - up), 4)
        report.pooled_brier = round(
            sum((p - y) ** 2 for p, y, _ in all_scored) / n, 4)
    for bucket, labels in sorted(calib.items()):
        report.calibration[bucket] = {
            "n": len(labels),
            "realized_up_rate": round(sum(labels) / len(labels), 4),
        }
    return report


def predict_next_day(exchange: str, provider: MarketDataProvider,
                     lookback_days: int = 900,
                     tickers: Optional[List[str]] = None
                     ) -> (BacktestReport, List[Prediction]):
    """Backtest first, then emit tomorrow's calibrated view per ticker."""
    report = run_backtest(exchange, provider, lookback_days, tickers)
    preds = []
    for r in report.results:
        if r.prob_up_tomorrow is None:
            continue
        p = r.prob_up_tomorrow
        direction = "UP" if p > LONG_TH else "DOWN" if p < SHORT_TH \
            else "FLAT/NO-EDGE"
        preds.append(Prediction(
            ticker=r.ticker,
            as_of=r.last_date or "",
            prob_up=p,
            direction=direction,
            expected_move_pct=r.expected_move_pct or 0.0,
            backtested_bucket_hit_rate=report.bucket_hit_rate(p),
            n_backtest_days=r.n_scored,
        ))
    preds.sort(key=lambda x: abs(x.prob_up - 0.5), reverse=True)
    return report, preds
