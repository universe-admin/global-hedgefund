"""Hermes — the learning brain that orchestrates the whole desk.

One ticker in, an investment committee out:

    data snapshot -> 7 analysts (parallel seats) -> bull vs bear debate
    -> research manager -> trader -> risk manager -> fund manager verdict
    -> journal entry + optional book update + written thesis card

Hermes also owns the book: `execute=True` applies the verdict to positions,
`health_check()` runs the exit-rule engine across the book, and `grade()`
closes the learning loop so lessons feed the next run.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from hedgefund.agents.analysts import ALL_ANALYSTS
from hedgefund.agents.base import AgentReport
from hedgefund.agents.fund_manager import FundManager, Verdict
from hedgefund.agents.researchers import DebateResult, ResearchManager
from hedgefund.agents.risk import RiskManager, RiskReview
from hedgefund.agents.trader import Trader, TradePlan
from hedgefund.brain.memory import JournalEntry, Memory
from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketDataProvider, MarketSnapshot
from hedgefund.data.router import get_provider
from hedgefund.llm.client import LLMClient
from hedgefund.portfolio.book import Book, Position
from hedgefund.portfolio.health import HealthReport, run_health_check
from hedgefund.valuation.thesis import ThesisCard, build_thesis


@dataclass
class DeskRun:
    run_id: str
    ticker: str
    as_of: str
    snapshot: MarketSnapshot
    analyst_reports: List[AgentReport] = field(default_factory=list)
    debate: Optional[DebateResult] = None
    research: Optional[AgentReport] = None
    plan: Optional[TradePlan] = None
    risk: Optional[RiskReview] = None
    verdict: Optional[Verdict] = None
    thesis: Optional[ThesisCard] = None
    executed: bool = False


class HermesBrain:
    def __init__(self, config: Config = DEFAULT_CONFIG,
                 provider: Optional[MarketDataProvider] = None,
                 llm: Optional[LLMClient] = None):
        self.config = config
        config.ensure_dirs()
        self.provider = provider or get_provider(config)
        self.llm = llm or LLMClient(config)
        self.memory = Memory(config)
        self.book = Book(config)

    # ---- the full desk run ----

    def run_desk(self, ticker: str, execute: bool = False,
                 with_thesis: bool = True) -> DeskRun:
        snap = self.provider.snapshot(ticker)
        run = DeskRun(
            run_id=uuid.uuid4().hex[:12],
            ticker=snap.ticker,
            as_of=snap.as_of,
            snapshot=snap,
        )

        # 1) analyst team
        run.analyst_reports = [cls(self.llm).analyze(snap) for cls in ALL_ANALYSTS]

        # 2) bull vs bear debate, refereed
        manager = ResearchManager(self.llm, rounds=self.config.debate_rounds)
        run.debate = manager.run_debate(snap, run.analyst_reports)
        run.research = run.debate.manager_report

        # 3) trader
        held = self.book.get(snap.ticker)
        held_pct = held.size_pct_nav if held else 0.0
        trader = Trader(self.llm, self.config)
        run.plan = trader.plan(snap, run.research, held_pct_nav=held_pct)

        # 4) risk manager (sector/gross computed net of the existing position)
        risk = RiskManager(self.llm, self.config)
        run.risk = risk.review(
            snap, run.plan,
            book_gross_pct=self.book.gross_exposure() - held_pct,
            book_sector_pct=self.book.sector_exposure(snap.sector)
            - (held_pct if held and held.sector == snap.sector else 0.0),
        )

        # 5) fund manager verdict, with Hermes' lessons in hand
        lessons = self.memory.relevant_lessons(snap.ticker)
        fm = FundManager(self.llm)
        run.verdict = fm.decide(snap, run.analyst_reports, run.research,
                                run.plan, run.risk, lessons)

        # 6) written thesis card
        if with_thesis:
            run.thesis = build_thesis(snap, run.analyst_reports, self.config)

        # 7) journal it
        self.memory.record(JournalEntry(
            run_id=run.run_id,
            date=snap.as_of,
            ticker=snap.ticker,
            action=run.verdict.action,
            conviction=run.verdict.conviction,
            size_pct_nav=run.verdict.size_pct_nav,
            price=snap.last_close() or 0.0,
            research_score=run.research.score,
            context={
                "provider": snap.provider,
                "research": run.research.headline,
                "risk": run.risk.notes[:140],
            },
        ))

        # 8) optionally act on the book
        if execute:
            self._apply(run)

        return run

    def _apply(self, run: DeskRun) -> None:
        v, snap = run.verdict, run.snapshot
        price = snap.last_close() or 0.0
        if v.action in ("BUY", "ADD", "HOLD / ACCUMULATE") and v.size_pct_nav > 0:
            self.book.add(Position(
                ticker=snap.ticker,
                entry_price=price,
                entry_date=snap.as_of,
                size_pct_nav=v.size_pct_nav if v.action == "BUY"
                else max(v.size_pct_nav - (self.book.get(snap.ticker).size_pct_nav
                                           if self.book.get(snap.ticker) else 0.0), 0.0),
                stop=v.stop,
                target_base=v.target_base,
                target_stretch=v.target_stretch,
                high_water_mark=price,
                thesis=v.thesis[:300],
                conviction=v.conviction,
                sector=snap.sector,
            ))
            run.executed = True
        elif v.action == "TRIM":
            pos = self.book.get(snap.ticker)
            if pos:
                self.book.resize(snap.ticker, v.size_pct_nav)
                run.executed = True
        elif v.action == "SELL":
            if self.book.get(snap.ticker):
                self.book.close(snap.ticker, price, "committee verdict: SELL",
                                date=snap.as_of)
                run.executed = True

    # ---- book maintenance ----

    def health_check(self) -> HealthReport:
        return run_health_check(self.book, self.provider, self.config)

    def screen(self, tickers: List[str]) -> List[DeskRun]:
        runs = [self.run_desk(t, execute=False, with_thesis=False)
                for t in tickers]
        runs.sort(key=lambda r: (r.research.score * (r.verdict.conviction / 10)),
                  reverse=True)
        return runs

    # ---- the learning loop ----

    def grade(self, run_id: str, realized_return: float,
              horizon_days: int):
        return self.memory.grade(run_id, realized_return, horizon_days)

    def grade_from_market(self, run_id: str) -> Optional[float]:
        """Grade a journaled decision against today's price automatically."""
        entry = next((e for e in self.memory.entries if e.run_id == run_id), None)
        if entry is None or not entry.price:
            return None
        snap = self.provider.snapshot(entry.ticker)
        price = snap.last_close()
        if not price:
            return None
        realized = price / entry.price - 1.0
        then = dt.date.fromisoformat(entry.date)
        horizon = max((dt.date.fromisoformat(snap.as_of) - then).days, 1)
        self.memory.grade(run_id, realized, horizon)
        return realized
