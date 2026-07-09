"""London Strategic Edge adapter — live/licensed data over the Vault HTTP API.

Configuration is environment-only so the API key never touches the repo:

    LSE_API_KEY       your key (required to activate the provider)
    LSE_API_URL       base URL, default https://api.londonstrategicedge.com/vault
    LSE_CANDLES_PATH  candles endpoint path, default /candles

Auth is sent as both ``Authorization: Bearer <key>`` and ``X-API-Key`` —
whichever scheme the Vault expects, one of them matches. The candle parser
is deliberately tolerant: it accepts a bare JSON list or a list nested under
``candles``/``data``/``results``/``series``, with OHLCV keys in any of the
common spellings and timestamps as ISO dates or epoch seconds/milliseconds.
Run ``hedgefund lse-check SYMBOL`` to see exactly what the API returns and
confirm the mapping on your machine.

The WebSocket feed (wss://data-ws.londonstrategicedge.com) streams ticks;
this desk runs on daily bars, so only the HTTP API is used here.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from hedgefund.data.base import MarketDataProvider, MarketSnapshot, PriceBar

DEFAULT_API_URL = "https://api.londonstrategicedge.com/vault"

_TIME_KEYS = ("date", "time", "timestamp", "t", "datetime", "dt")
_KEYMAP = {
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "price", "last"),
    "volume": ("volume", "v", "vol"),
}
_LIST_KEYS = ("candles", "data", "results", "series", "bars", "items")


def _api_key() -> Optional[str]:
    return os.environ.get("LSE_API_KEY") or os.environ.get("HEDGEFUND_LSE_KEY")


def _base_url() -> str:
    return os.environ.get("LSE_API_URL", DEFAULT_API_URL).rstrip("/")


def _pick(row: dict, keys) -> Optional[float]:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return None
    return None


def _parse_date(row: dict) -> Optional[str]:
    for k in _TIME_KEYS:
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            ts = float(v)
            if ts > 1e12:      # epoch milliseconds
                ts /= 1000.0
            try:
                return dt.datetime.utcfromtimestamp(ts).date().isoformat()
            except (OverflowError, OSError, ValueError):
                return None
        s = str(v)
        return s[:10] if len(s) >= 10 else None
    return None


def parse_candles(payload) -> List[PriceBar]:
    """Best-effort candle extraction from any reasonable JSON shape."""
    rows = payload
    if isinstance(payload, dict):
        for k in _LIST_KEYS:
            if isinstance(payload.get(k), list):
                rows = payload[k]
                break
        else:
            rows = []
    if not isinstance(rows, list):
        return []

    bars: List[PriceBar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _pick(row, _KEYMAP["close"])
        date = _parse_date(row)
        if close is None or date is None:
            continue
        bars.append(PriceBar(
            date=date,
            open=_pick(row, _KEYMAP["open"]) or close,
            high=_pick(row, _KEYMAP["high"]) or close,
            low=_pick(row, _KEYMAP["low"]) or close,
            close=close,
            volume=_pick(row, _KEYMAP["volume"]) or 0.0,
        ))
    bars.sort(key=lambda b: b.date)
    return bars


class LSEProvider(MarketDataProvider):
    name = "lse"

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def available(self) -> bool:
        return bool(_api_key())

    # ---- HTTP ----

    def _request(self, path: str, params: dict) -> object:
        key = _api_key()
        if not key:
            raise RuntimeError(
                "LSE_API_KEY is not set — export it to enable the "
                "London Strategic Edge provider.")
        url = f"{_base_url()}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {key}",
            "X-API-Key": key,
            "Accept": "application/json",
            "User-Agent": "global-hedgefund/0.1",
        })
        cafile = (os.environ.get("SSL_CERT_FILE")
                  or os.environ.get("CURL_CA_BUNDLE") or None)
        ctx = ssl.create_default_context(cafile=cafile)
        with urllib.request.urlopen(req, timeout=self.timeout,
                                    context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def fetch_candles(self, symbol: str, days: int) -> List[PriceBar]:
        path = os.environ.get("LSE_CANDLES_PATH", "/candles")
        start = dt.date.today() - dt.timedelta(days=int(days * 1.5))
        payload = self._request(path, {
            "symbol": symbol,
            "interval": "1d",
            "start": str(start),
            "limit": days,
        })
        return parse_candles(payload)

    # ---- provider interface ----

    def snapshot(self, ticker: str, lookback_days: int = 300) -> MarketSnapshot:
        t = ticker.upper()
        bars = self.fetch_candles(t, lookback_days)
        return MarketSnapshot(
            ticker=t,
            as_of=bars[-1].date if bars else str(dt.date.today()),
            provider=self.name,
            price=bars[-1].close if bars else None,
            bars=bars,
        )

    # ---- diagnostics (used by `hedgefund lse-check`) ----

    def check(self, symbol: str = "BTC-USD") -> str:
        lines = [f"base url : {_base_url()}",
                 f"key set  : {'yes' if _api_key() else 'NO — export LSE_API_KEY'}"]
        try:
            bars = self.fetch_candles(symbol, 30)
            lines.append(f"candles  : {len(bars)} parsed for {symbol}")
            if bars:
                lines.append(f"first    : {bars[0]}")
                lines.append(f"last     : {bars[-1]}")
            else:
                lines.append(
                    "candles parsed to 0 — the endpoint answered but the shape "
                    "was unrecognized. Set LSE_CANDLES_PATH to the documented "
                    "path (see the Vault API docs) and retry.")
        except urllib.error.HTTPError as e:
            lines.append(f"HTTP {e.code} from {e.url}")
            lines.append("401/403 = auth scheme or key issue; "
                         "404 = wrong path, set LSE_CANDLES_PATH.")
        except Exception as e:  # noqa: BLE001 - diagnostic surface
            lines.append(f"error    : {type(e).__name__}: {e}")
        return "\n".join(lines)
