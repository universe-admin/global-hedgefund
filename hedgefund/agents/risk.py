"""The Risk Manager: hard gates the trade must pass before it reaches the PM.

Checks liquidity, single-name concentration, gross exposure, volatility and
crowding, then either passes the plan through or hands back a resized one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from hedgefund.agents.trader import TradePlan
from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketSnapshot
from hedgefund.llm.client import LLMClient


@dataclass
class RiskCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class RiskReview:
    approved: bool
    adjusted_size_pct: float
    checks: List[RiskCheck] = field(default_factory=list)
    var_1d_pct: Optional[float] = None      # 1-day 95% VaR of the position, % of NAV
    notes: str = ""

    def summary(self) -> Dict[str, str]:
        out = {c.name: ("pass" if c.passed else "FAIL") + f" — {c.detail}"
               for c in self.checks}
        if self.var_1d_pct is not None:
            out["VaR (1d, 95%)"] = f"{self.var_1d_pct * 100:.2f}% of NAV"
        return out


class RiskManager:
    role = "Risk Manager"

    def __init__(self, llm: Optional[LLMClient] = None,
                 config: Config = DEFAULT_CONFIG):
        self.llm = llm
        self.config = config

    def review(self, snap: MarketSnapshot, plan: TradePlan,
               book_gross_pct: float = 0.0,
               book_sector_pct: float = 0.0) -> RiskReview:
        checks: List[RiskCheck] = []
        size = plan.size_pct_nav

        # 1. Liquidity: position vs average dollar volume.
        adv = self._avg_dollar_volume(snap)
        if adv and snap.last_close():
            # assume $100mm NAV book for the liquidity sanity check
            pos_dollars = size * 100e6
            days_to_exit = pos_dollars / (adv * 0.1) if adv else 99
            ok = days_to_exit <= 5
            checks.append(RiskCheck(
                "liquidity", ok,
                f"~{days_to_exit:.1f} days to exit at 10% of ADV"))
            if not ok:
                size = min(size, (adv * 0.1 * 5) / 100e6)
        else:
            checks.append(RiskCheck("liquidity", True, "no volume data; waived"))

        # 2. Concentration: single-name cap.
        cap = self.config.max_position_pct
        ok = size <= cap + 1e-9
        checks.append(RiskCheck(
            "concentration (single name)", ok,
            f"{size*100:.1f}% vs cap {cap*100:.0f}%"))
        size = min(size, cap)

        # 3. Gross exposure.
        gross_after = book_gross_pct + size
        ok = gross_after <= self.config.max_gross_exposure + 1e-9
        checks.append(RiskCheck(
            "gross exposure", ok,
            f"{gross_after*100:.0f}% after trade vs "
            f"{self.config.max_gross_exposure*100:.0f}% max"))
        if not ok:
            size = max(0.0, self.config.max_gross_exposure - book_gross_pct)

        # 4. Sector concentration (soft: warn + halve above 35%).
        sector_after = book_sector_pct + size
        ok = sector_after <= 0.35
        checks.append(RiskCheck(
            "sector concentration", ok,
            f"{sector_after*100:.0f}% in {snap.sector or 'sector'} after trade"))
        if not ok:
            size *= 0.5

        # 5. Volatility / crowding sanity.
        vol = snap.realized_vol(20)
        short = snap.ownership.short_pct_float
        crowd_notes = []
        if vol and vol > 0.80:
            size *= 0.7
            crowd_notes.append(f"extreme vol {vol*100:.0f}%: size haircut 30%")
        if short and short > 20:
            size *= 0.8
            crowd_notes.append(f"short interest {short:.0f}% of float: haircut 20%")
        checks.append(RiskCheck(
            "volatility & crowding", not crowd_notes,
            "; ".join(crowd_notes) or
            f"vol {vol*100:.0f}% ann., positioning clean" if vol else "no vol data"))

        var_1d = None
        if vol:
            var_1d = size * vol / (252 ** 0.5) * 1.65  # 95% one-day VaR

        hard_fail = any(
            not c.passed and c.name in ("gross exposure",)
            for c in checks
        ) and size <= 0
        approved = not hard_fail and (plan.action in ("hold", "avoid") or size > 0
                                      or plan.action in ("sell", "trim"))

        review = RiskReview(
            approved=approved,
            adjusted_size_pct=round(max(size, 0.0), 4),
            checks=checks,
            var_1d_pct=round(var_1d, 5) if var_1d is not None else None,
        )
        review.notes = self._explain(snap, plan, review)
        return review

    @staticmethod
    def _avg_dollar_volume(snap: MarketSnapshot, days: int = 20) -> Optional[float]:
        bars = snap.bars[-days:]
        if not bars:
            return None
        return sum(b.close * b.volume for b in bars) / len(bars)

    def _explain(self, snap, plan, review) -> str:
        if self.llm and self.llm.enabled:
            out = self.llm.complete(
                "You are the risk manager. Summarize your review in 2 sentences: "
                "what you approved/resized and the binding constraint.",
                f"Ticker {snap.ticker}; proposed {plan.action} "
                f"{plan.size_pct_nav*100:.1f}% NAV; approved size "
                f"{review.adjusted_size_pct*100:.1f}%.\nChecks:\n"
                + "\n".join(f"- {c.name}: "
                            f"{'pass' if c.passed else 'FAIL'} ({c.detail})"
                            for c in review.checks),
            )
            if out:
                return out
        failed = [c.name for c in review.checks if not c.passed]
        if review.adjusted_size_pct < plan.size_pct_nav - 1e-9:
            return (f"Resized {snap.ticker} from {plan.size_pct_nav*100:.1f}% to "
                    f"{review.adjusted_size_pct*100:.1f}% of NAV; binding: "
                    f"{', '.join(failed) or 'policy haircuts'}.")
        return (f"Approved {plan.action} at {review.adjusted_size_pct*100:.1f}% "
                f"of NAV; all gates {'clean' if not failed else 'noted: ' + ', '.join(failed)}.")
