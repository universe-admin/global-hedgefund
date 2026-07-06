"""The book: positions persisted as JSON under the brain's state dir."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from hedgefund.config import Config, DEFAULT_CONFIG


@dataclass
class Position:
    ticker: str
    entry_price: float
    entry_date: str
    size_pct_nav: float
    stop: Optional[float] = None
    target_base: Optional[float] = None
    target_stretch: Optional[float] = None
    high_water_mark: Optional[float] = None
    thesis: str = ""
    conviction: int = 5
    sector: Optional[str] = None
    status: str = "open"           # open | closed
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None

    def unrealized_return(self, price: float) -> float:
        return price / self.entry_price - 1.0 if self.entry_price else 0.0

    def age_days(self, today: Optional[dt.date] = None) -> int:
        today = today or dt.date.today()
        entry = dt.date.fromisoformat(self.entry_date)
        return (today - entry).days


class Book:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        config.ensure_dirs()
        self.path = config.state_dir / "book.json"
        self.positions: List[Position] = []
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self.positions = [Position(**p) for p in raw.get("positions", [])]

    def save(self) -> None:
        self.path.write_text(json.dumps(
            {"positions": [asdict(p) for p in self.positions]}, indent=2))

    # ---- operations ----

    def open_positions(self) -> List[Position]:
        return [p for p in self.positions if p.status == "open"]

    def get(self, ticker: str) -> Optional[Position]:
        for p in self.open_positions():
            if p.ticker == ticker.upper():
                return p
        return None

    def gross_exposure(self) -> float:
        return sum(p.size_pct_nav for p in self.open_positions())

    def sector_exposure(self, sector: Optional[str]) -> float:
        if not sector:
            return 0.0
        return sum(p.size_pct_nav for p in self.open_positions()
                   if p.sector == sector)

    def add(self, position: Position) -> Position:
        existing = self.get(position.ticker)
        if existing:
            # Average in: blend entry, sum size, keep tighter stop.
            total = existing.size_pct_nav + position.size_pct_nav
            if total > 0:
                existing.entry_price = (
                    existing.entry_price * existing.size_pct_nav
                    + position.entry_price * position.size_pct_nav) / total
            existing.size_pct_nav = total
            existing.stop = max(filter(None, [existing.stop, position.stop]),
                                default=existing.stop)
            existing.thesis = position.thesis or existing.thesis
            existing.conviction = position.conviction
            self.save()
            return existing
        self.positions.append(position)
        self.save()
        return position

    def resize(self, ticker: str, new_size_pct: float) -> Optional[Position]:
        p = self.get(ticker)
        if p:
            p.size_pct_nav = max(new_size_pct, 0.0)
            self.save()
        return p

    def close(self, ticker: str, price: float, reason: str,
              date: Optional[str] = None) -> Optional[Position]:
        p = self.get(ticker)
        if p:
            p.status = "closed"
            p.exit_price = price
            p.exit_date = date or str(dt.date.today())
            p.exit_reason = reason
            self.save()
        return p

    def mark(self, ticker: str, price: float) -> None:
        """Update high-water mark on a new price print."""
        p = self.get(ticker)
        if p and (p.high_water_mark is None or price > p.high_water_mark):
            p.high_water_mark = price
            self.save()
