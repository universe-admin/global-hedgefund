from hedgefund.config import Config
from hedgefund.valuation.dcf import capm_rate, run_dcf
from hedgefund.valuation.monte_carlo import simulate
from hedgefund.valuation.thesis import build_thesis


def test_capm_rate_bounds():
    cfg = Config()
    assert capm_rate(None, cfg) == cfg.risk_free_rate + cfg.equity_risk_premium
    assert capm_rate(10.0, cfg) <= 0.20
    assert capm_rate(-5.0, cfg) >= 0.06


def test_dcf_sane(snapshot):
    res = run_dcf(snapshot)
    assert 0.06 <= res.discount_rate <= 0.20
    assert res.blended_ratio > 0
    assert 0 < res.stress_floor_ratio < 1.5


def test_monte_carlo_percentiles_ordered():
    r = simulate(spot=100, drift=0.08, vol=0.30, years=5, paths=5000, seed=42)
    assert r.p05 < r.p50 < r.p95
    assert 0.0 <= r.prob_gain <= 1.0
    # positive drift over 5y should mean better-than-even odds of a gain
    assert r.prob_gain > 0.5


def test_monte_carlo_deterministic_with_seed():
    a = simulate(100, 0.1, 0.4, 5, paths=2000, seed=7)
    b = simulate(100, 0.1, 0.4, 5, paths=2000, seed=7)
    assert (a.p05, a.p50, a.p95) == (b.p05, b.p50, b.p95)


def test_thesis_card(snapshot):
    cfg = Config(monte_carlo_paths=4000)
    card = build_thesis(snapshot, config=cfg)
    assert card.ticker == "NVDA"
    assert card.target_bear < card.target_base < card.target_bull
    assert card.stress_floor > 0
    assert card.strengths and card.threats
    assert 0 <= card.prob_gain <= 1
