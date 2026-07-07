"""Command-line interface — one ticker in, an investment committee out.

    hedgefund run NVDA               full desk run (7 analysts -> debate ->
                                     trader -> risk -> verdict + thesis card)
    hedgefund run NVDA --execute     ...and apply the verdict to the book
    hedgefund thesis NVDA            written thesis card only
    hedgefund screen NVDA MU GOOG    rank several names
    hedgefund health                 book vs the exit-rule engine
    hedgefund book                   show open positions
    hedgefund grade RUN_ID           grade a past decision against the market
    hedgefund scorecard              Hermes' hit rate so far
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from hedgefund.brain.orchestrator import HermesBrain
from hedgefund.config import Config
from hedgefund.report import (
    render_desk_run,
    render_health,
    render_screen,
    render_thesis,
)
from hedgefund.valuation.thesis import build_thesis


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hedgefund",
        description="A full hedge-fund desk: analysts -> bull/bear debate -> "
                    "trader -> risk -> fund-manager verdict, with a learning "
                    "brain, a book, and an exit-rule engine.",
    )
    p.add_argument("--data", choices=["auto", "openbb", "yfinance", "offline"],
                   default=None, help="force a data provider")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="full desk run on one ticker")
    run.add_argument("ticker")
    run.add_argument("--execute", action="store_true",
                     help="apply the verdict to the book")
    run.add_argument("--no-thesis", action="store_true")

    thesis = sub.add_parser("thesis", help="written thesis card (DCF + Monte Carlo)")
    thesis.add_argument("ticker")

    screen = sub.add_parser("screen", help="run the desk over several tickers")
    screen.add_argument("tickers", nargs="+")

    sub.add_parser("health", help="health-check the book against exit rules")
    sub.add_parser("book", help="list open positions")

    grade = sub.add_parser("grade", help="grade a journaled run vs the market")
    grade.add_argument("run_id")

    sub.add_parser("scorecard", help="Hermes' graded hit rate")

    bt = sub.add_parser(
        "backtest",
        help="walk-forward backtest of next-day predictions on an exchange")
    bt.add_argument("exchange",
                choices=["nse", "bse", "nasdaq", "nyse", "crypto", "all"])
    bt.add_argument("--days", type=int, default=900,
                    help="lookback window in trading days")
    bt.add_argument("--tickers", nargs="*", default=None,
                    help="override the exchange's default universe")

    pr = sub.add_parser(
        "predict",
        help="backtest, then emit tomorrow's calibrated outlook")
    pr.add_argument("exchange",
                choices=["nse", "bse", "nasdaq", "nyse", "crypto"])
    pr.add_argument("--days", type=int, default=900)
    pr.add_argument("--tickers", nargs="*", default=None)
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    config = Config()
    if args.data:
        config.data_provider = args.data
    brain = HermesBrain(config)

    if args.cmd == "run":
        run = brain.run_desk(args.ticker, execute=args.execute,
                             with_thesis=not args.no_thesis)
        if args.json:
            print(json.dumps({
                "run_id": run.run_id,
                "ticker": run.ticker,
                "verdict": asdict(run.verdict),
                "risk_approved": run.risk.approved,
                "thesis": asdict(run.thesis) if run.thesis else None,
            }, indent=2, default=str))
        else:
            print(render_desk_run(run))

    elif args.cmd == "thesis":
        snap = brain.provider.snapshot(args.ticker)
        card = build_thesis(snap, config=config)
        print(json.dumps(asdict(card), indent=2, default=str)
              if args.json else render_thesis(card))

    elif args.cmd == "screen":
        runs = brain.screen(args.tickers)
        if args.json:
            print(json.dumps([
                {"ticker": r.ticker, "action": r.verdict.action,
                 "conviction": r.verdict.conviction,
                 "size_pct_nav": r.verdict.size_pct_nav,
                 "research_score": r.research.score}
                for r in runs], indent=2))
        else:
            print(render_screen(runs))

    elif args.cmd == "health":
        report = brain.health_check()
        print(json.dumps(asdict(report), indent=2, default=str)
              if args.json else render_health(report))

    elif args.cmd == "book":
        positions = brain.book.open_positions()
        if args.json:
            print(json.dumps([asdict(p) for p in positions], indent=2))
        elif not positions:
            print("book is empty")
        else:
            for p in positions:
                print(f"{p.ticker:<6} entry ${p.entry_price:,.2f} on {p.entry_date} "
                      f"· size {p.size_pct_nav*100:.1f}% · stop {p.stop} "
                      f"· conviction {p.conviction}/10")

    elif args.cmd == "grade":
        realized = brain.grade_from_market(args.run_id)
        if realized is None:
            print(f"run {args.run_id} not found in the journal", file=sys.stderr)
            return 1
        print(f"graded {args.run_id}: realized {realized*100:+.1f}% — "
              "journal updated")

    elif args.cmd == "scorecard":
        print(json.dumps(brain.memory.scorecard(), indent=2))

    elif args.cmd == "backtest":
        from hedgefund.backtest.engine import run_backtest
        from hedgefund.report import render_backtest
        exchanges = (["nse", "bse", "nasdaq", "nyse", "crypto"]
                     if args.exchange == "all" else [args.exchange])
        for ex in exchanges:
            report = run_backtest(ex, brain.provider,
                                  lookback_days=args.days,
                                  tickers=args.tickers or None)
            if args.json:
                print(json.dumps(asdict(report), indent=2, default=str))
            else:
                print(render_backtest(report))

    elif args.cmd == "predict":
        from hedgefund.backtest.engine import predict_next_day
        from hedgefund.report import render_backtest, render_predictions
        report, preds = predict_next_day(args.exchange, brain.provider,
                                         lookback_days=args.days,
                                         tickers=args.tickers or None)
        if args.json:
            print(json.dumps({
                "backtest": asdict(report),
                "predictions": [asdict(p) for p in preds],
            }, indent=2, default=str))
        else:
            print(render_backtest(report))
            print(render_predictions(report, preds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
