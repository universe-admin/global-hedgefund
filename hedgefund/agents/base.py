"""Shared agent machinery.

Every seat on the desk produces an :class:`AgentReport`: a signed score, a
confidence, the metrics it looked at, and a short written view. Scores are
on [-1, +1] (bearish .. bullish) so downstream seats can aggregate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from hedgefund.data.base import MarketSnapshot
from hedgefund.llm.client import LLMClient


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def fmt(v: Optional[float], pct: bool = False, digits: int = 2,
        signed: bool = False) -> str:
    if v is None:
        return "n/a"
    if pct:
        return f"{v * 100:+.1f}%" if signed else f"{v * 100:.1f}%"
    return f"{v:,.{digits}f}"


@dataclass
class AgentReport:
    agent: str
    role: str
    score: float                 # -1 (max bearish) .. +1 (max bullish)
    confidence: float            # 0 .. 1
    headline: str
    metrics: Dict[str, str] = field(default_factory=dict)
    narrative: str = ""

    def stance(self) -> str:
        if self.score > 0.35:
            return "bullish"
        if self.score < -0.35:
            return "bearish"
        return "neutral"


class Analyst:
    """Base class: quant scoring is mandatory, LLM prose is optional."""

    name = "analyst"
    role = "Analyst"
    system = (
        "You are a {role} at a multi-strategy hedge fund. You are given "
        "computed metrics for {ticker}. Write a tight 2-3 sentence desk note: "
        "state your read, cite the specific numbers that drive it, and flag "
        "the one thing that would change your mind. No preamble."
    )

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm

    # subclasses implement: returns (score, confidence, headline, metrics)
    def evaluate(self, snap: MarketSnapshot):
        raise NotImplementedError

    def analyze(self, snap: MarketSnapshot) -> AgentReport:
        score, confidence, headline, metrics = self.evaluate(snap)
        narrative = self._write(snap, score, headline, metrics)
        return AgentReport(
            agent=self.name,
            role=self.role,
            score=clamp(score),
            confidence=clamp(confidence, 0.0, 1.0),
            headline=headline,
            metrics=metrics,
            narrative=narrative,
        )

    def _write(self, snap, score, headline, metrics) -> str:
        if self.llm and self.llm.enabled:
            lines = "\n".join(f"- {k}: {v}" for k, v in metrics.items())
            out = self.llm.complete(
                self.system.format(role=self.role, ticker=snap.ticker),
                f"Ticker: {snap.ticker} ({snap.company_name}, {snap.sector})\n"
                f"Quant score: {score:+.2f} ({headline})\nMetrics:\n{lines}",
            )
            if out:
                return out
        # Deterministic fallback prose.
        tone = "bullish" if score > 0.35 else "bearish" if score < -0.35 else "neutral"
        keys = list(metrics.items())[:3]
        cited = "; ".join(f"{k} {v}" for k, v in keys)
        return f"{self.role} is {tone} on {snap.ticker}: {headline}. Key data: {cited}."
