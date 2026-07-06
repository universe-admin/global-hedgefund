"""Runtime configuration for the desk.

Everything is overridable via environment variables so the same code runs in
CI (offline, deterministic), on a laptop (yfinance), or on a funded desk
(OpenBB Platform + Anthropic API).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    # Data layer: "auto" tries openbb -> yfinance -> offline.
    data_provider: str = field(default_factory=lambda: _env("HEDGEFUND_DATA", "auto"))

    # LLM layer: "auto" uses Anthropic when ANTHROPIC_API_KEY is set,
    # otherwise the deterministic quant fallback. "off" forces the fallback.
    llm_mode: str = field(default_factory=lambda: _env("HEDGEFUND_LLM", "auto"))
    llm_model: str = field(
        default_factory=lambda: _env("HEDGEFUND_MODEL", "claude-sonnet-5")
    )
    llm_max_tokens: int = 1200

    # Where the brain persists its state (book, journal, lessons).
    state_dir: Path = field(
        default_factory=lambda: Path(
            _env("HEDGEFUND_HOME", os.path.join(os.getcwd(), ".hedgefund"))
        )
    )

    # Desk risk policy.
    max_position_pct: float = 0.15      # single-name cap, fraction of NAV
    max_gross_exposure: float = 1.0     # no leverage by default
    target_position_vol: float = 0.20   # annualized vol contribution target
    stop_loss_pct: float = 0.15         # default hard stop below entry
    trailing_stop_pct: float = 0.20     # trail from high-water mark
    time_stop_days: int = 180           # thesis must work within this window
    debate_rounds: int = 2              # bull/bear rebuttal rounds

    # Valuation defaults (CAPM).
    risk_free_rate: float = 0.042
    equity_risk_premium: float = 0.05
    monte_carlo_paths: int = 20_000
    valuation_horizon_years: int = 5

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG = Config()
