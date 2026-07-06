"""The Fund Manager: final verdict, conviction 1-10, and the paper trail.

The PM sees everything — analyst reports, the debate, the trade plan, the
risk review, and Hermes' lessons from past decisions — and issues the
committee's verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from hedgefund.agents.base import AgentReport, clamp
from hedgefund.agents.risk import RiskReview
from hedgefund.agents.trader import TradePlan
from hedgefund.data.base import MarketSnapshot
from hedgefund.llm.client import LLMClient


@dataclass
class Verdict:
    ticker: str
    action: str                # BUY | ADD | HOLD | ACCUMULATE | TRIM | SELL | AVOID
    conviction: int            # 1..10
    size_pct_nav: float
    entry_low: Optional[float]
    entry_high: Optional[float]
    target_base: Optional[float]
    target_stretch: Optional[float]
    stop: Optional[float]
    thesis: str
    risks: str
    review_trigger: str
    lessons_applied: List[str] = field(default_factory=list)

    def label(self) -> str:
        rng = ""
        if self.entry_low and self.entry_high:
            rng = f" ${self.entry_low:.0f}-{self.entry_high:.0f}"
        return f"{self.action}{rng} · conviction {self.conviction}/10"


class FundManager:
    role = "Fund Manager"

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm

    def decide(self, snap: MarketSnapshot, analyst_reports: List[AgentReport],
               research: AgentReport, plan: TradePlan, risk: RiskReview,
               lessons: Optional[List[str]] = None) -> Verdict:
        lessons = lessons or []
        score = research.score

        # Risk gate dominates; then translate stance + plan into the call.
        if not risk.approved:
            action = "AVOID"
        elif plan.action in ("buy", "add") and score > 0.45:
            action = "BUY" if plan.action == "buy" else "ADD"
        elif plan.action in ("buy", "add"):
            action = "HOLD / ACCUMULATE"
        elif plan.action == "hold":
            action = "HOLD"
        elif plan.action == "trim":
            action = "TRIM"
        elif plan.action == "sell":
            action = "SELL"
        else:
            action = "AVOID"

        # Conviction: research strength x risk cleanliness x desk agreement.
        agree = self._agreement(analyst_reports, score)
        risk_ok = sum(c.passed for c in risk.checks) / max(len(risk.checks), 1)
        conviction = int(round(clamp(
            abs(score) * 6 + agree * 2 + risk_ok * 2, 1, 10)))

        thesis, risks_txt = self._write(snap, analyst_reports, research,
                                        plan, risk, lessons, action, conviction)
        review_trigger = (
            f"re-run the desk after {plan.catalyst}" if plan.catalyst
            else "re-run the desk in 20 trading days or on a 10% adverse move"
        )
        return Verdict(
            ticker=snap.ticker,
            action=action,
            conviction=conviction,
            size_pct_nav=risk.adjusted_size_pct,
            entry_low=plan.entry_low,
            entry_high=plan.entry_high,
            target_base=plan.target_base,
            target_stretch=plan.target_stretch,
            stop=plan.stop,
            thesis=thesis,
            risks=risks_txt,
            review_trigger=review_trigger,
            lessons_applied=lessons,
        )

    @staticmethod
    def _agreement(reports: List[AgentReport], stance: float) -> float:
        if not reports:
            return 0.5
        same = sum(1 for r in reports
                   if (r.score > 0.1 and stance > 0)
                   or (r.score < -0.1 and stance < 0))
        return same / len(reports)

    def _write(self, snap, reports, research, plan, risk, lessons,
               action, conviction):
        if self.llm and self.llm.enabled:
            ctx = (
                f"Ticker {snap.ticker} ({snap.company_name}). "
                f"Research: {research.headline} ({research.score:+.2f}). "
                f"Plan: {plan.action} {plan.size_pct_nav*100:.1f}% NAV, "
                f"targets {plan.target_base}/{plan.target_stretch}, stop {plan.stop}. "
                f"Risk: {risk.notes} "
                f"Lessons from past decisions: {'; '.join(lessons) or 'none'}."
            )
            thesis = self.llm.complete(
                "You are the fund manager issuing the final investment-committee "
                f"verdict ({action}, conviction {conviction}/10). Write the thesis "
                "in 3 sentences: why now, what we're paid for, and the sizing logic.",
                ctx,
            )
            risks_txt = self.llm.complete(
                "Same context. In 2 sentences, state the two biggest risks and "
                "the pre-agreed exit condition.",
                ctx,
            )
            if thesis and risks_txt:
                return thesis, risks_txt

        top = sorted(reports, key=lambda r: r.score * r.confidence,
                     reverse=(research.score >= 0))[:2]
        drivers = "; ".join(f"{r.role.lower()}: {r.headline}" for r in top)
        thesis = (
            f"{action} {snap.ticker} at {risk.adjusted_size_pct*100:.1f}% of NAV. "
            f"{research.narrative} Primary drivers — {drivers}."
        )
        bears = [r for r in reports if r.score < -0.1]
        bear_pts = "; ".join(r.headline for r in bears[:2]) or "no strong bear points"
        risks_txt = (
            f"Key risks: {bear_pts}. Exit on stop {plan.stop} or thesis break; "
            f"{risk.notes}"
        )
        if lessons:
            thesis += f" Hermes lessons applied: {lessons[0]}"
        return thesis, risks_txt
