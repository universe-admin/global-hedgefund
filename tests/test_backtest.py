import math
import random

from hedgefund.backtest.engine import predict_next_day, run_backtest
from hedgefund.backtest.features import (
    WARMUP,
    build_lead_returns,
    features_at,
    label_at,
    lead_return_before,
)
from hedgefund.backtest.model import OnlineLogit
from hedgefund.data.base import PriceBar
from hedgefund.data.offline_provider import OfflineProvider


def _bars(closes, start_year=2024):
    import datetime as dt
    d = dt.date(start_year, 1, 1)
    bars = []
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        bars.append(PriceBar(str(d), c, c * 1.01, c * 0.99, c, 1e6))
        d += dt.timedelta(days=1)
    return bars


def test_no_lookahead():
    """Features at day t must be identical no matter what happens after t."""
    rng = random.Random(1)
    closes = [100.0]
    for _ in range(200):
        closes.append(closes[-1] * math.exp(rng.gauss(0, 0.02)))
    t = 150
    future_a = _bars(closes[: t + 1] + [closes[t] * 2] * 30)
    future_b = _bars(closes[: t + 1] + [closes[t] * 0.5] * 30)
    assert features_at(future_a, t) == features_at(future_b, t)


def test_labels():
    bars = _bars([100, 101, 99, 99])
    assert label_at(bars, 0) == 1
    assert label_at(bars, 1) == 0
    assert label_at(bars, 2) == 0  # 99 -> 99 is not up
    assert label_at(bars, 3) is None


def test_model_learns_persistent_trend():
    """On a persistently trending tape the model must beat a coin flip."""
    rng = random.Random(7)
    closes = [100.0]
    trend = 1
    for i in range(1200):
        if i % 60 == 0:
            trend *= -1  # regime flips, momentum persists within regimes
        closes.append(closes[-1] * math.exp(trend * 0.004 + rng.gauss(0, 0.004)))
    bars = _bars(closes)
    model = OnlineLogit(9)
    hits = total = 0
    for t in range(WARMUP, len(bars)):
        x = features_at(bars, t)
        y = label_at(bars, t)
        if x is None or y is None:
            continue
        p = model.predict_proba(x)
        if model.n_updates >= 120:
            hits += int((p >= 0.5) == (y == 1))
            total += 1
        model.update(x, y)
    assert total > 500
    assert hits / total > 0.60


def test_lead_alignment_strictly_before():
    lead = _bars([100, 101, 102, 103])
    rets = build_lead_returns(lead)
    # a local date equal to a lead date must NOT see that same day's return
    same_day = lead[2].date
    r = lead_return_before(rets, same_day)
    assert r is not None
    assert abs(r - (101 / 100 - 1)) < 1e-9  # uses the *prior* session


def test_run_backtest_offline_nse():
    provider = OfflineProvider()
    report = run_backtest("nse", provider, lookback_days=500)
    assert report.results, "universe produced no results"
    assert report.n_scored > 500
    assert 0.0 <= report.pooled_accuracy <= 1.0
    assert 0.0 <= report.pooled_brier <= 1.0
    assert report.calibration
    for r in report.results:
        assert r.ticker.endswith(".NS") or r.ticker.startswith("^")


def test_predict_next_day_shapes():
    provider = OfflineProvider()
    report, preds = predict_next_day("nse", provider, lookback_days=500)
    assert preds
    for p in preds:
        assert 0.0 <= p.prob_up <= 1.0
        assert p.direction in ("UP", "DOWN", "FLAT/NO-EDGE")
        assert p.n_backtest_days > 0
    # sorted by conviction (distance from 0.5)
    dists = [abs(p.prob_up - 0.5) for p in preds]
    assert dists == sorted(dists, reverse=True)


def test_cli_backtest_and_predict(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HEDGEFUND_HOME", str(tmp_path / ".hedgefund"))
    monkeypatch.setenv("HEDGEFUND_DATA", "offline")
    monkeypatch.setenv("HEDGEFUND_LLM", "off")
    from hedgefund import cli
    assert cli.main(["backtest", "nse", "--days", "450"]) == 0
    out = capsys.readouterr().out
    assert "WALK-FORWARD BACKTEST — NSE" in out
    assert "CALIBRATION" in out
    assert cli.main(["predict", "nse", "--days", "450"]) == 0
    out = capsys.readouterr().out
    assert "NEXT-SESSION OUTLOOK — NSE" in out
    assert "not financial advice" in out
