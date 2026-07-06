"""Plain-text rendering of desk runs, thesis cards, and health reports."""

from __future__ import annotations

from typing import List

from hedgefund.brain.orchestrator import DeskRun
from hedgefund.portfolio.health import HealthReport
from hedgefund.valuation.thesis import ThesisCard

W = 78


def _rule(ch: str = "─") -> str:
    return ch * W


def _title(text: str) -> str:
    return f"\n{_rule('═')}\n{text}\n{_rule('═')}"


def render_desk_run(run: DeskRun) -> str:
    snap = run.snapshot
    out: List[str] = []
    out.append(_title(
        f"DESK RUN — {snap.ticker} ({snap.company_name}) · {snap.as_of} "
        f"· data: {snap.provider}"))
    price = snap.last_close()
    out.append(f"price ${price:,.2f} · sector {snap.sector or 'n/a'} "
               f"· run id {run.run_id}")

    out.append(f"\n{_rule()}\nANALYST TEAM\n{_rule()}")
    for r in run.analyst_reports:
        out.append(f"\n[{r.role}]  score {r.score:+.2f} · conf {r.confidence:.2f} "
                   f"· {r.stance().upper()}")
        for k, v in r.metrics.items():
            out.append(f"    {k:<24} {v}")
        out.append(f"    ▸ {r.narrative}")

    if run.debate:
        out.append(f"\n{_rule()}\nBULL vs BEAR DEBATE\n{_rule()}")
        for t in run.debate.turns:
            tag = "🐂 BULL" if t.speaker == "bull" else "🐻 BEAR"
            out.append(f"\n{tag} (round {t.round}): {t.text}")
        rm = run.debate.manager_report
        out.append(f"\n[Research Manager] {rm.headline} (score {rm.score:+.2f})")
        out.append(f"    ▸ {rm.narrative}")

    if run.plan:
        p = run.plan
        out.append(f"\n{_rule()}\nTRADER\n{_rule()}")
        for k, v in p.metrics.items():
            out.append(f"    {k:<24} {v}")
        out.append(f"    ▸ {p.rationale}")

    if run.risk:
        out.append(f"\n{_rule()}\nRISK MANAGER\n{_rule()}")
        for k, v in run.risk.summary().items():
            out.append(f"    {k:<28} {v}")
        out.append(f"    approved: {'YES' if run.risk.approved else 'NO'} "
                   f"· final size {run.risk.adjusted_size_pct*100:.1f}% NAV")
        out.append(f"    ▸ {run.risk.notes}")

    if run.verdict:
        v = run.verdict
        out.append(_title(f"FUND MANAGER — VERDICT: {v.label()}"))
        out.append(f"size {v.size_pct_nav*100:.1f}% NAV · "
                   f"targets {v.target_base} / {v.target_stretch} · stop {v.stop}")
        out.append(f"\nTHESIS  {v.thesis}")
        out.append(f"\nRISKS   {v.risks}")
        out.append(f"\nREVIEW  {v.review_trigger}")
        if v.lessons_applied:
            out.append("\nHERMES LESSONS APPLIED")
            for l in v.lessons_applied:
                out.append(f"  • {l}")
        if run.executed:
            out.append("\n[book updated]")

    if run.thesis:
        out.append(render_thesis(run.thesis))
    return "\n".join(out)


def render_thesis(t: ThesisCard) -> str:
    out: List[str] = []
    out.append(_title(f"WRITTEN THESIS — {t.ticker} · {t.company} · "
                      f"today ${t.price:,.2f}"))
    out.append(
        f"{t.horizon_years}-yr base CAGR {t.implied_cagr*100:.1f}%/yr · "
        f"P(gain by {t.horizon_years}y) {t.prob_gain*100:.0f}% · "
        f"discount rate {t.discount_rate*100:.1f}% · "
        f"vol σ {t.volatility*100:.0f}% · beta β {t.beta:.2f} · "
        f"DCF stress floor ${t.stress_floor:,.0f}")
    out.append(f"\n{t.horizon_years}-year target range "
               f"(blended DCF · exit-multiple · Monte Carlo, "
               f"{t.mc.paths:,} paths):")
    out.append(f"    bear ${t.target_bear:,.0f}   ·   base ${t.target_base:,.0f}"
               f"   ·   bull ${t.target_bull:,.0f}")
    out.append("\nSTRENGTHS")
    for s in t.strengths:
        out.append(f"  + {s}")
    out.append("THREATS")
    for s in t.threats:
        out.append(f"  - {s}")
    out.append("\nEducation only — not financial advice.")
    return "\n".join(out)


def render_health(report: HealthReport) -> str:
    out: List[str] = []
    out.append(_title(f"HEALTH REPORT — {report.headline()}"))
    if not report.positions:
        out.append("book is empty — run `hedgefund run TICKER --execute` first")
    for p in report.positions:
        icon = {"HOLD": "✓", "ON WATCH": "◍", "EXIT": "✗"}[p.status]
        out.append(f"\n{icon} {p.ticker:<6} ${p.price:>10,.2f}  "
                   f"P&L {p.pnl_pct*100:+6.1f}%  size {p.size_pct_nav*100:4.1f}%  "
                   f"— {p.status}")
        for n in p.notes:
            out.append(f"      · {n}")
    return "\n".join(out)


def render_screen(runs: List[DeskRun]) -> str:
    out: List[str] = []
    out.append(_title(f"DESK SCREEN — {len(runs)} names, ranked"))
    out.append(f"{'#':<3}{'ticker':<8}{'verdict':<20}{'conv':<6}"
               f"{'size':<7}{'research':<10}headline")
    for i, r in enumerate(runs, 1):
        out.append(
            f"{i:<3}{r.ticker:<8}{r.verdict.action:<20}"
            f"{r.verdict.conviction}/10  "
            f"{r.verdict.size_pct_nav*100:4.1f}%  "
            f"{r.research.score:+.2f}     {r.research.headline}")
    return "\n".join(out)
