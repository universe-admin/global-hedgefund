from hedgefund.agents.analysts import ALL_ANALYSTS
from hedgefund.agents.fund_manager import FundManager
from hedgefund.agents.researchers import ResearchManager
from hedgefund.agents.risk import RiskManager
from hedgefund.agents.trader import Trader
from hedgefund.config import Config


def test_all_seven_analysts_report(snapshot):
    reports = [cls().analyze(snapshot) for cls in ALL_ANALYSTS]
    assert len(reports) == 7
    for r in reports:
        assert -1.0 <= r.score <= 1.0
        assert 0.0 <= r.confidence <= 1.0
        assert r.headline
        assert r.narrative
        assert r.metrics


def test_debate_produces_turns_and_adjudication(snapshot):
    reports = [cls().analyze(snapshot) for cls in ALL_ANALYSTS]
    debate = ResearchManager(rounds=2).run_debate(snapshot, reports)
    # 2 openings + (rounds-1)*2 rebuttals
    assert len(debate.turns) == 4
    assert debate.bull_report.score >= 0
    assert debate.bear_report.score <= 0
    assert debate.manager_report is not None
    assert -1.0 <= debate.manager_report.score <= 1.0


def test_trader_sizes_within_cap(snapshot):
    cfg = Config()
    reports = [cls().analyze(snapshot) for cls in ALL_ANALYSTS]
    research = ResearchManager(rounds=1).run_debate(snapshot, reports).manager_report
    plan = Trader(config=cfg).plan(snapshot, research)
    assert 0.0 <= plan.size_pct_nav <= cfg.max_position_pct + 1e-9
    if plan.action in ("buy", "add"):
        assert plan.stop is not None and plan.stop < snapshot.last_close()
        assert plan.entry_low < plan.entry_high


def test_risk_manager_enforces_gross_cap(snapshot):
    cfg = Config()
    reports = [cls().analyze(snapshot) for cls in ALL_ANALYSTS]
    research = ResearchManager(rounds=1).run_debate(snapshot, reports).manager_report
    plan = Trader(config=cfg).plan(snapshot, research)
    review = RiskManager(config=cfg).review(snapshot, plan,
                                            book_gross_pct=0.99)
    assert review.adjusted_size_pct <= 0.01 + 1e-9


def test_fund_manager_verdict_shape(snapshot):
    cfg = Config()
    reports = [cls().analyze(snapshot) for cls in ALL_ANALYSTS]
    research = ResearchManager(rounds=1).run_debate(snapshot, reports).manager_report
    plan = Trader(config=cfg).plan(snapshot, research)
    review = RiskManager(config=cfg).review(snapshot, plan)
    verdict = FundManager().decide(snapshot, reports, research, plan, review,
                                   lessons=["test lesson"])
    assert verdict.ticker == "NVDA"
    assert 1 <= verdict.conviction <= 10
    assert verdict.action in ("BUY", "ADD", "HOLD", "HOLD / ACCUMULATE",
                              "TRIM", "SELL", "AVOID")
    assert verdict.thesis and verdict.risks
    assert "conviction" in verdict.label()
