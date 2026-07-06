"""Health Report: the whole book against the exit-rule engine at once.

Reproduces "FIG. 02 — HEALTH REPORT: 5x HOLD · 0 EXITS TRIGGERED".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketDataProvider
from hedgefund.portfolio.book import Book
from hedgefund.portfolio.exit_rules import ExitCheck, ExitRuleEngine


@dataclass
class PositionHealth:
    ticker: str
    price: float
    entry_price: float
    size_pct_nav: float
    pnl_pct: float
    status: str                 # HOLD | ON WATCH | EXIT
    notes: List[str] = field(default_factory=list)


@dataclass
class HealthReport:
    positions: List[PositionHealth] = field(default_factory=list)
    exits_triggered: int = 0
    on_watch: int = 0
    gross_exposure: float = 0.0

    def headline(self) -> str:
        holds = sum(1 for p in self.positions if p.status == "HOLD")
        return (f"{holds}x HOLD · {self.on_watch} ON WATCH · "
                f"{self.exits_triggered} EXITS TRIGGERED · "
                f"gross {self.gross_exposure*100:.0f}%")


def run_health_check(book: Book, provider: MarketDataProvider,
                     config: Config = DEFAULT_CONFIG) -> HealthReport:
    engine = ExitRuleEngine(config)
    report = HealthReport(gross_exposure=book.gross_exposure())

    for pos in book.open_positions():
        snap = provider.snapshot(pos.ticker)
        price = snap.last_close() or pos.entry_price
        book.mark(pos.ticker, price)
        check: ExitCheck = engine.check(pos, snap)
        status = check.status()
        notes = [f"{s.rule}: {s.detail}"
                 for s in check.signals if s.triggered]
        report.positions.append(PositionHealth(
            ticker=pos.ticker,
            price=round(price, 2),
            entry_price=round(pos.entry_price, 2),
            size_pct_nav=pos.size_pct_nav,
            pnl_pct=round(pos.unrealized_return(price), 4),
            status=status,
            notes=notes,
        ))
        if status == "EXIT":
            report.exits_triggered += 1
        elif status == "ON WATCH":
            report.on_watch += 1

    return report
