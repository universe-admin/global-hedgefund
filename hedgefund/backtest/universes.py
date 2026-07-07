"""Exchange universes for backtesting and next-day prediction.

Symbols use Yahoo/OpenBB conventions: ``.NS`` = NSE, ``.BO`` = BSE.
Each universe carries a ``lead`` symbol — the market whose *previous* session
plausibly leads it. For Indian markets that is the prior US close (the US
session ends hours before the NSE/BSE open), which is the one legitimate
cross-market signal this engine exploits. US markets get no lead by default.
"""

from __future__ import annotations

UNIVERSES = {
    "nse": {
        "index": "^NSEI",
        "tickers": [
            "^NSEI", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
            "ICICIBANK.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS",
        ],
        "lead": "^GSPC",  # prior US session leads the Indian open
    },
    "bse": {
        "index": "^BSESN",
        "tickers": [
            "^BSESN", "RELIANCE.BO", "TCS.BO", "HDFCBANK.BO",
            "INFY.BO", "SBIN.BO",
        ],
        "lead": "^GSPC",
    },
    "nasdaq": {
        "index": "^IXIC",
        "tickers": [
            "^IXIC", "AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META", "AVGO",
        ],
        "lead": None,
    },
    "nyse": {
        "index": "^NYA",
        "tickers": [
            "^NYA", "JPM", "XOM", "JNJ", "PG", "UNH", "V", "KO",
        ],
        "lead": None,
    },
    # Crypto trades 24/7 — "next session" means next calendar day. The lead
    # here is intra-market: BTC is the market's risk proxy and tends to move
    # first, so the alts get BTC's prior day as a feature (BTC itself doesn't
    # self-lead; the engine skips the lead for the lead symbol).
    "crypto": {
        "index": "BTC-USD",
        "tickers": [
            "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD",
            "XRP-USD", "ADA-USD", "DOGE-USD", "AVAX-USD",
        ],
        "lead": "BTC-USD",
    },
}
