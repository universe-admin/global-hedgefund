"""Point-in-time feature extraction for next-day direction prediction.

Every feature for day ``t`` is computed strictly from bars ``[0..t]`` (plus,
for cross-market leads, foreign bars strictly *before* the local date), so
the walk-forward backtest cannot leak the future. Fundamentals, estimates and
news are deliberately excluded here — historical point-in-time versions of
those aren't available, and using today's values in a replay would leak.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from hedgefund.data.base import PriceBar

# Order matters: the model's weight vector is indexed by this list.
FEATURE_NAMES = [
    "bias",
    "ret_1d",        # yesterday->today return, vol-normalized
    "mom_5d",        # 5-day momentum, vol-normalized
    "mom_21d",       # 1-month momentum, vol-normalized
    "sma50_gap",     # price vs 50dma
    "sma200_gap",    # price vs 200dma
    "rsi_centered",  # RSI(14)/100 - 0.5
    "vol_regime",    # 20d vol vs 60d vol - 1
    "lead_ret",      # previous foreign session return, vol-normalized
]


def _clamp(x: float, lim: float = 3.0) -> float:
    return max(-lim, min(lim, x))


def _ret(closes: Sequence[float], t: int, days: int) -> Optional[float]:
    if t - days < 0 or closes[t - days] <= 0:
        return None
    return closes[t] / closes[t - days] - 1.0


def _vol(closes: Sequence[float], t: int, window: int) -> Optional[float]:
    if t - window < 0:
        return None
    rets = []
    for i in range(t - window + 1, t + 1):
        if closes[i - 1] > 0 and closes[i] > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def _rsi(closes: Sequence[float], t: int, window: int = 14) -> Optional[float]:
    if t - window < 0:
        return None
    gains = losses = 0.0
    for i in range(t - window + 1, t + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


WARMUP = 61  # first index with a full feature set (needs 60d vol + 1)


def build_lead_returns(lead_bars: List[PriceBar]) -> Dict[str, float]:
    """date -> that session's close-to-close return, for the lead market."""
    out: Dict[str, float] = {}
    for prev, cur in zip(lead_bars, lead_bars[1:]):
        if prev.close > 0:
            out[cur.date] = cur.close / prev.close - 1.0
    return out


def lead_return_before(lead_rets: Dict[str, float], local_date: str,
                       max_lookback: int = 7) -> Optional[float]:
    """Most recent lead-market session strictly before the local date."""
    candidates = [d for d in lead_rets if d < local_date]
    if not candidates:
        return None
    best = max(candidates)
    # Stale leads (long holidays) are noise, not signal.
    return lead_rets[best] if _date_gap(best, local_date) <= max_lookback else None


def _date_gap(d1: str, d2: str) -> int:
    import datetime as dt
    return (dt.date.fromisoformat(d2) - dt.date.fromisoformat(d1)).days


def features_at(bars: List[PriceBar], t: int,
                lead_rets: Optional[Dict[str, float]] = None
                ) -> Optional[List[float]]:
    """Feature vector for day t, or None inside the warm-up window."""
    if t < WARMUP or t >= len(bars):
        return None
    closes = [b.close for b in bars]
    vol20 = _vol(closes, t, 20)
    vol60 = _vol(closes, t, 60)
    if not vol20 or not vol60 or vol20 <= 0:
        return None

    r1 = _ret(closes, t, 1)
    r5 = _ret(closes, t, 5)
    r21 = _ret(closes, t, 21)
    sma50 = sum(closes[t - 49 : t + 1]) / 50 if t >= 49 else None
    sma200 = sum(closes[t - 199 : t + 1]) / 200 if t >= 199 else None
    rsi = _rsi(closes, t)

    lead = None
    if lead_rets:
        lead = lead_return_before(lead_rets, bars[t].date)

    def norm(r: Optional[float], horizon_days: float) -> float:
        if r is None:
            return 0.0
        return _clamp(r / (vol20 * math.sqrt(horizon_days)))

    return [
        1.0,                                                   # bias
        norm(r1, 1),
        norm(r5, 5),
        norm(r21, 21),
        _clamp((closes[t] / sma50 - 1.0) / (vol20 * 5)) if sma50 else 0.0,
        _clamp((closes[t] / sma200 - 1.0) / (vol20 * 10)) if sma200 else 0.0,
        (rsi / 100.0 - 0.5) * 2.0 if rsi is not None else 0.0,
        _clamp(vol20 / vol60 - 1.0, 1.5),
        norm(lead, 1),
    ]


def label_at(bars: List[PriceBar], t: int) -> Optional[int]:
    """1 if the NEXT session closes up, else 0. None on the last bar."""
    if t + 1 >= len(bars):
        return None
    return 1 if bars[t + 1].close > bars[t].close else 0
