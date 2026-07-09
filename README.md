# global-hedgefund

**One ticker in. An investment committee out.**

A full hedge-fund desk in one Python package, modeled on the three-repo stack:

| Layer | Inspired by | What it does here |
|---|---|---|
| Agent desk | **TradingAgents** | 7 analysts → bull vs. bear debate → research manager → trader → risk manager → fund-manager verdict |
| Market data | **OpenBB** (with yfinance fallback) | live prices, fundamentals, estimates, news, options flow, ownership/insider data, macro |
| Orchestrator | **Hermes** (the learning brain) | runs the desk, journals every decision, grades outcomes into lessons, manages the book, exit rules & health reports |

Zero required dependencies: the core desk runs fully offline on a deterministic
data provider and a quant fallback for every agent. Install the extras and the
same code upgrades itself to live OpenBB/yfinance data and Claude-written
research notes.

```
                                   ┌─────────────────────┐
                 ┌────────────────►│  Technical Analyst  │──┐
                 │                 │  Fundamentals       │  │
┌──────────────┐ │  ┌───────────┐  │  Estimates          │  │   ┌──────┐   ┌──────┐
│ OpenBB MCP / │ └──│  Market   │  │  News / Sentiment   │  ├──►│ Bull │vs.│ Bear │
│ yfinance /   │────│  Snapshot │─►│  Flow / Ownership   │  │   └──┬───┘   └──┬───┘
│ offline      │    └───────────┘  │  Options            │  │      └────┬─────┘
└──────────────┘                   │  Macro              │──┘   ┌───────▼────────┐
                                   └─────────────────────┘      │Research Manager│
                                                                └───────┬────────┘
      ┌─────────────────┐   ┌──────────────┐   ┌────────┐               │
      │  Fund Manager   │◄──│ Risk Manager │◄──│ Trader │◄──────────────┘
      │    VERDICT      │   └──────────────┘   └────────┘
      └───────┬─────────┘
              ▼
   Hermes: journal · lessons · book · exit rules · health · thesis (DCF+MC)
```

## Quickstart

```bash
pip install -e .              # zero-dep core (offline data, quant agents)
pip install -e ".[all]"      # + anthropic, yfinance, openbb

hedgefund run NVDA            # full desk run: 7 analysts -> debate -> verdict
hedgefund run NVDA --execute  # ...and put the position on the book
hedgefund thesis NVDA         # written thesis: DCF + CAPM + 20k-path Monte Carlo
hedgefund screen NVDA MU GOOG # rank several names by the committee's conviction
hedgefund health              # the whole book vs. the exit-rule engine
hedgefund book                # open positions
hedgefund scorecard           # Hermes' graded hit rate so far
hedgefund grade <RUN_ID>      # grade a past decision against today's tape
```

Sample verdict (offline, deterministic):

```
FUND MANAGER — VERDICT: BUY $187-196 · conviction 8/10
size 15.0% NAV · targets 210.37 / 235.61 · stop 164.05

WRITTEN THESIS — NVDA · today $193.00
5-yr base CAGR 14.8%/yr · P(gain by 5y) 58% · discount rate 15.2% · σ 56% · β 2.20 · stress floor $29
5-year target range:  bear $107 · base $385 · bull $743
```

## How a desk run works

1. **Snapshot** — the data router picks the best available provider
   (`openbb` → `yfinance` → `offline`) and builds one typed
   `MarketSnapshot`: tape, fundamentals, estimates, news, options,
   ownership, macro.
2. **Analyst team** — seven independent seats each score the name on
   [-1, +1] with a confidence, off their own slice of the snapshot.
3. **Bull vs. bear debate** — every position is forced through the fight
   first: openings built from each side's best evidence, N rebuttal rounds,
   then the Research Manager adjudicates into a single research stance.
4. **Trader** — turns the stance into an executable plan: vol-targeted
   sizing, entry band, base/stretch targets, hard stop, next catalyst.
5. **Risk manager** — liquidity, single-name and sector concentration,
   gross exposure, volatility/crowding gates; resizes or blocks.
6. **Fund manager** — the final verdict (action, conviction 1–10, sizing,
   review trigger), with Hermes' lessons from past graded decisions in hand.
7. **Hermes** — journals the run; `--execute` applies it to the book. Later,
   `hedgefund grade RUN_ID` scores the call against the tape and distills a
   lesson that feeds the next run.

## The book

- `hedgefund health` re-prices every open position and runs the
  **exit-rule engine**: hard stop, trailing stop from the position's
  high-water mark, 200-dma trend break, time stop (stale losers), and
  stretch-target review. Output is the classic
  `5x HOLD · 0 EXITS TRIGGERED` health report.
- Positions persist as JSON under `.hedgefund/` (override with
  `HEDGEFUND_HOME`).

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `HEDGEFUND_DATA` | `auto` | `openbb`, `yfinance`, `offline`, or `auto` (best available) |
| `HEDGEFUND_LLM` | `auto` | `auto` uses Claude when `ANTHROPIC_API_KEY` is set; `off` forces the quant fallback |
| `HEDGEFUND_MODEL` | `claude-sonnet-5` | Anthropic model for agent prose |
| `HEDGEFUND_HOME` | `./.hedgefund` | state dir: book, journal, lessons |

Risk policy (single-name cap, gross cap, stops, debate rounds, CAPM inputs,
Monte Carlo paths) lives in `hedgefund/config.py` as one dataclass.

### London Strategic Edge (licensed data feed)

If you have an LSE Vault API key, export it and the router prefers it
automatically for price history (candles) — no install needed, stdlib only:

```bash
export LSE_API_KEY=lse_live_...     # never commit this
hedgefund lse-check BTC-USD         # verify connectivity + response shape
hedgefund --data lse predict crypto
```

| Env var | Default | Meaning |
|---|---|---|
| `LSE_API_KEY` | — | your key; presence activates the provider |
| `LSE_API_URL` | `https://api.londonstrategicedge.com/vault` | Vault base URL |
| `LSE_CANDLES_PATH` | `/candles` | candles endpoint path, if your docs differ |

The adapter sends the key as both `Authorization: Bearer` and `X-API-Key`,
and parses candles from any common JSON shape (bare list or nested under
`candles`/`data`/`results`, short or long OHLCV keys, ISO or epoch s/ms
timestamps). `hedgefund lse-check` prints exactly what came back so a
mismatched path or auth scheme is a one-line env fix. The LSE feed is
price-focused: desk runs fall back gracefully for fundamentals/news, or
force `--data yfinance` for full-snapshot desk runs. The WebSocket tick
stream (`wss://data-ws.londonstrategicedge.com`) is not used — this desk
trades daily bars.

**Secret hygiene:** keys live in environment variables only. Nothing in this
repo, its config files, or its state dir ever stores the key.

## Backtesting & next-day prediction (NSE · BSE · NASDAQ · NYSE · crypto)

```bash
hedgefund backtest nse            # walk-forward backtest of next-day calls
hedgefund backtest all            # ...across all five markets
hedgefund predict nse             # tomorrow's calibrated outlook for NSE
hedgefund predict crypto          # BTC/ETH/SOL/... next-day outlook
hedgefund predict nse --tickers RELIANCE.NS TCS.NS   # custom universe
```

The engine walks each tape day by day with **zero look-ahead**: features for
day *t* come strictly from bars `[0..t]`, an online logistic model predicts
tomorrow *before* seeing the label (prequential protocol, 120-day burn-in),
and for Indian markets it adds the one legitimate cross-market lead — the
**prior US session** (which ends hours before the NSE/BSE open); for crypto
the lead is intra-market — BTC's prior day feeds the altcoins. Fundamentals
and news are deliberately excluded from the backtest: point-in-time history
for them isn't available, and using today's values would leak.

Every `predict` ships with its receipts: the pooled backtested accuracy vs.
the always-up baseline, a Brier score, and a **calibration table** mapping
each emitted probability bucket to how often the market actually closed up.
If the model has no edge in a window, the report says so in plain text.

**Honesty note:** next-day market direction is close to a coin flip;
world-class is a low-single-digit edge over baseline, sustained. Any tool
promising "utmost accuracy" on tomorrow's close is lying to you — this one
measures and reports what it actually achieves instead.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite (43 tests) runs entirely offline against the deterministic provider:
data layer, all seven analysts, the debate, trader sizing, risk gates, the
verdict, DCF/Monte Carlo, the book, exit rules, the learning loop, the
walk-forward backtester (including a no-look-ahead property test), and the CLI.

## Disclaimer

Education only — **not financial advice**. The offline provider generates
synthetic data; live providers pull real market data but nothing here should
run real money.
