"""Hermes' memory: a decision journal plus distilled lessons.

Every desk run is journaled. When a decision is later *graded* against what
the price actually did, Hermes distills a lesson ("high-conviction buys into
elevated short interest underperformed") and feeds the relevant ones back to
the Fund Manager on the next run of that name or setup.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from hedgefund.config import Config, DEFAULT_CONFIG


@dataclass
class JournalEntry:
    run_id: str
    date: str
    ticker: str
    action: str
    conviction: int
    size_pct_nav: float
    price: float
    research_score: float
    context: Dict[str, str] = field(default_factory=dict)
    # graded later:
    graded: bool = False
    outcome_return: Optional[float] = None
    outcome_horizon_days: Optional[int] = None
    grade: Optional[str] = None  # good_call | bad_call | wash


@dataclass
class Lesson:
    date: str
    text: str
    source_run_id: str
    tickers: List[str] = field(default_factory=list)


class Memory:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        config.ensure_dirs()
        self.journal_path = config.state_dir / "journal.json"
        self.lessons_path = config.state_dir / "lessons.json"
        self.entries: List[JournalEntry] = []
        self.lessons: List[Lesson] = []
        self._load()

    def _load(self) -> None:
        if self.journal_path.exists():
            self.entries = [JournalEntry(**e) for e in
                            json.loads(self.journal_path.read_text())]
        if self.lessons_path.exists():
            self.lessons = [Lesson(**l) for l in
                            json.loads(self.lessons_path.read_text())]

    def save(self) -> None:
        self.journal_path.write_text(
            json.dumps([asdict(e) for e in self.entries], indent=2))
        self.lessons_path.write_text(
            json.dumps([asdict(l) for l in self.lessons], indent=2))

    # ---- journaling ----

    def record(self, entry: JournalEntry) -> None:
        self.entries.append(entry)
        self.save()

    def history(self, ticker: str) -> List[JournalEntry]:
        return [e for e in self.entries if e.ticker == ticker.upper()]

    # ---- learning ----

    def grade(self, run_id: str, realized_return: float,
              horizon_days: int) -> Optional[JournalEntry]:
        """Grade a past decision against the realized return and distill a lesson."""
        entry = next((e for e in self.entries if e.run_id == run_id), None)
        if entry is None:
            return None
        entry.graded = True
        entry.outcome_return = realized_return
        entry.outcome_horizon_days = horizon_days

        was_long = entry.action in ("BUY", "ADD", "HOLD / ACCUMULATE", "HOLD")
        aligned = realized_return if was_long else -realized_return
        if aligned > 0.05:
            entry.grade = "good_call"
        elif aligned < -0.05:
            entry.grade = "bad_call"
        else:
            entry.grade = "wash"

        lesson_text = self._distill(entry)
        if lesson_text:
            self.lessons.append(Lesson(
                date=str(dt.date.today()),
                text=lesson_text,
                source_run_id=run_id,
                tickers=[entry.ticker],
            ))
        self.save()
        return entry

    @staticmethod
    def _distill(e: JournalEntry) -> Optional[str]:
        if e.grade == "wash":
            return None
        ret = f"{(e.outcome_return or 0)*100:+.1f}% over {e.outcome_horizon_days}d"
        if e.grade == "bad_call":
            hi_conv = e.conviction >= 7
            qualifier = ("high-conviction" if hi_conv else "low-conviction")
            ctx = ", ".join(f"{k}={v}" for k, v in list(e.context.items())[:2])
            return (f"{e.ticker}: {qualifier} {e.action} at conviction "
                    f"{e.conviction}/10 returned {ret}. Context then: {ctx or 'n/a'}. "
                    f"Demand stronger disconfirming evidence on similar setups.")
        return (f"{e.ticker}: {e.action} (conviction {e.conviction}/10) worked, "
                f"{ret}. The setup is repeatable — same evidence bar next time.")

    def relevant_lessons(self, ticker: str, limit: int = 3) -> List[str]:
        t = ticker.upper()
        specific = [l.text for l in reversed(self.lessons) if t in l.tickers]
        general = [l.text for l in reversed(self.lessons) if t not in l.tickers]
        return (specific + general)[:limit]

    # ---- scorecard ----

    def scorecard(self) -> Dict[str, float]:
        graded = [e for e in self.entries if e.graded]
        if not graded:
            return {"graded": 0, "hit_rate": 0.0, "avg_return": 0.0}
        good = sum(1 for e in graded if e.grade == "good_call")
        avg = sum(e.outcome_return or 0 for e in graded) / len(graded)
        return {
            "graded": len(graded),
            "hit_rate": round(good / len(graded), 3),
            "avg_return": round(avg, 4),
        }
