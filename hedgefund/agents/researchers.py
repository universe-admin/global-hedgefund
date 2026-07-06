"""Bull vs. bear debate, refereed by the Research Manager.

Every name is forced through the fight: the Bull builds the strongest long
case from the analysts' bullish evidence, the Bear attacks it with the
bearish evidence, they exchange rebuttals for N rounds, and the Research
Manager weighs the transcript into a single research stance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from hedgefund.agents.base import AgentReport, clamp
from hedgefund.data.base import MarketSnapshot
from hedgefund.llm.client import LLMClient


@dataclass
class DebateTurn:
    speaker: str  # "bull" | "bear"
    round: int
    text: str


@dataclass
class DebateResult:
    turns: List[DebateTurn] = field(default_factory=list)
    bull_report: Optional[AgentReport] = None
    bear_report: Optional[AgentReport] = None
    manager_report: Optional[AgentReport] = None


class _Researcher:
    side = "bull"
    role = "Bull Researcher"

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm

    def _evidence(self, reports: List[AgentReport]) -> List[AgentReport]:
        if self.side == "bull":
            picked = [r for r in reports if r.score > 0.05]
        else:
            picked = [r for r in reports if r.score < -0.05]
        return sorted(picked, key=lambda r: abs(r.score) * r.confidence, reverse=True)

    def opening(self, snap: MarketSnapshot, reports: List[AgentReport]) -> AgentReport:
        ev = self._evidence(reports)
        strength = sum(abs(r.score) * r.confidence for r in ev)
        total = sum(abs(r.score) * r.confidence for r in reports) or 1.0
        share = strength / total
        sign = 1.0 if self.side == "bull" else -1.0
        score = sign * clamp(0.2 + share, 0.0, 1.0)

        points = [f"{r.role}: {r.headline} ({r.score:+.2f})" for r in ev[:4]]
        headline = (
            f"{len(ev)}/{len(reports)} desks support the {self.side} case"
            if ev else f"little evidence for the {self.side} case"
        )
        narrative = self._speak(snap, reports, points, phase="opening")
        return AgentReport(
            agent=f"{self.side}_researcher",
            role=self.role,
            score=score,
            confidence=clamp(0.3 + share * 0.7, 0.0, 1.0),
            headline=headline,
            metrics={f"pillar {i+1}": p for i, p in enumerate(points)},
            narrative=narrative,
        )

    def rebut(self, snap: MarketSnapshot, reports: List[AgentReport],
              opponent_text: str, rnd: int) -> str:
        return self._speak(snap, reports,
                           [f"opponent said: {opponent_text[:400]}"],
                           phase=f"rebuttal round {rnd}")

    def _speak(self, snap, reports, points, phase: str) -> str:
        if self.llm and self.llm.enabled:
            summary = "\n".join(
                f"- {r.role}: {r.headline} (score {r.score:+.2f}, conf {r.confidence:.2f})"
                for r in reports
            )
            out = self.llm.complete(
                f"You are the {self.role} in an investment-committee debate on "
                f"{snap.ticker}. Argue the {self.side} case as hard as the evidence "
                "allows — concede nothing without data. 3-4 sentences, "
                f"this is your {phase}.",
                f"Analyst reports:\n{summary}\n\nContext points:\n"
                + "\n".join(points),
            )
            if out:
                return out
        ev = self._evidence(reports)
        if not ev:
            return (f"The {self.side} case on {snap.ticker} is thin; "
                    f"conceding this {phase} on the evidence.")
        cited = "; ".join(f"{r.role.lower()} says {r.headline}" for r in ev[:3])
        stance = "own it" if self.side == "bull" else "fade it"
        return (f"[{phase}] The {self.side} case on {snap.ticker}: {cited}. "
                f"Weight of evidence says {stance}.")


class BullResearcher(_Researcher):
    side = "bull"
    role = "Bull Researcher"


class BearResearcher(_Researcher):
    side = "bear"
    role = "Bear Researcher"


class ResearchManager:
    """Referees the debate and sets the research stance."""

    role = "Research Manager"

    def __init__(self, llm: Optional[LLMClient] = None, rounds: int = 2):
        self.llm = llm
        self.rounds = max(1, rounds)

    def run_debate(self, snap: MarketSnapshot,
                   reports: List[AgentReport]) -> DebateResult:
        bull, bear = BullResearcher(self.llm), BearResearcher(self.llm)
        result = DebateResult()

        result.bull_report = bull.opening(snap, reports)
        result.bear_report = bear.opening(snap, reports)
        result.turns.append(DebateTurn("bull", 0, result.bull_report.narrative))
        result.turns.append(DebateTurn("bear", 0, result.bear_report.narrative))

        for rnd in range(1, self.rounds):
            last_bear = result.turns[-1].text
            bull_reply = bull.rebut(snap, reports, last_bear, rnd)
            result.turns.append(DebateTurn("bull", rnd, bull_reply))
            bear_reply = bear.rebut(snap, reports, bull_reply, rnd)
            result.turns.append(DebateTurn("bear", rnd, bear_reply))

        result.manager_report = self._adjudicate(snap, reports, result)
        return result

    def _adjudicate(self, snap: MarketSnapshot, reports: List[AgentReport],
                    debate: DebateResult) -> AgentReport:
        # Confidence-weighted evidence, with the debate strength as tiebreak.
        total_w = sum(r.confidence for r in reports) or 1.0
        evidence = sum(r.score * r.confidence for r in reports) / total_w
        bull_s = debate.bull_report.score * debate.bull_report.confidence
        bear_s = debate.bear_report.score * debate.bear_report.confidence
        debate_lean = (bull_s + bear_s)  # bear score is negative
        score = clamp(evidence * 0.7 + debate_lean * 0.3)

        n_bull = sum(1 for r in reports if r.score > 0.1)
        n_bear = sum(1 for r in reports if r.score < -0.1)
        headline = (
            f"{'bull' if score >= 0 else 'bear'} thesis prevails "
            f"({n_bull} bullish vs {n_bear} bearish desks)"
        )
        narrative = None
        if self.llm and self.llm.enabled:
            transcript = "\n".join(
                f"[{t.speaker} r{t.round}] {t.text}" for t in debate.turns
            )
            narrative = self.llm.complete(
                f"You are the {self.role}. Adjudicate this bull/bear debate on "
                f"{snap.ticker}. In 3 sentences: who won, on what evidence, and "
                "the single biggest risk to that conclusion.",
                transcript,
            )
        if not narrative:
            winner = "bull" if score >= 0 else "bear"
            loser_pt = (debate.bear_report if winner == "bull"
                        else debate.bull_report).headline
            narrative = (
                f"The {winner} case carries: weighted analyst evidence is "
                f"{evidence:+.2f} across {len(reports)} desks. The losing side's "
                f"best point stands as the key risk: {loser_pt}."
            )
        return AgentReport(
            agent="research_manager",
            role=self.role,
            score=score,
            confidence=clamp(0.4 + abs(score) * 0.5, 0.0, 1.0),
            headline=headline,
            metrics={
                "weighted evidence": f"{evidence:+.2f}",
                "bullish desks": str(n_bull),
                "bearish desks": str(n_bear),
                "debate rounds": str(self.rounds),
            },
            narrative=narrative,
        )
