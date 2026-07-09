import json

import pytest

from hedgefund.config import Config
from hedgefund.data.lse_provider import LSEProvider, parse_candles
from hedgefund.data.router import get_provider

FAKE_KEY = "lse_test_0000000000000000000000000000"


def test_available_requires_key(monkeypatch):
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    monkeypatch.delenv("HEDGEFUND_LSE_KEY", raising=False)
    assert not LSEProvider().available()
    monkeypatch.setenv("LSE_API_KEY", FAKE_KEY)
    assert LSEProvider().available()


def test_router_auto_prefers_lse_with_key(monkeypatch):
    monkeypatch.setenv("LSE_API_KEY", FAKE_KEY)
    assert get_provider(Config(data_provider="auto")).name == "lse"
    monkeypatch.delenv("LSE_API_KEY")
    assert get_provider(Config(data_provider="auto")).name != "lse"


def test_parse_candles_bare_list_short_keys():
    payload = [
        {"t": 1719878400, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100},
        {"t": 1719964800, "o": 1.5, "h": 3, "l": 1, "c": 2.5, "v": 200},
    ]
    bars = parse_candles(payload)
    assert len(bars) == 2
    assert bars[0].date == "2024-07-02"
    assert bars[1].close == 2.5


def test_parse_candles_nested_long_keys_iso_dates():
    payload = {"candles": [
        {"date": "2026-07-01T00:00:00Z", "open": 10, "high": 11,
         "low": 9, "close": 10.5, "volume": 1000},
        {"date": "2026-07-02", "open": 10.5, "high": 12,
         "low": 10, "close": 11.0, "volume": 900},
    ]}
    bars = parse_candles(payload)
    assert [b.date for b in bars] == ["2026-07-01", "2026-07-02"]
    assert bars[-1].close == 11.0


def test_parse_candles_epoch_millis_and_sorting():
    payload = {"data": [
        {"timestamp": 1751500800000, "close": 5.0},   # 2025-07-03 (ms)
        {"timestamp": 1751414400000, "close": 4.0},   # 2025-07-02 (ms)
    ]}
    bars = parse_candles(payload)
    assert [b.close for b in bars] == [4.0, 5.0]      # sorted oldest-first
    assert bars[0].open == 4.0                        # close backfills OHLC


def test_parse_candles_garbage_is_empty():
    assert parse_candles({"error": "nope"}) == []
    assert parse_candles("not json-ish") == []
    assert parse_candles([{"foo": 1}, "x", None]) == []


def test_snapshot_via_mocked_http(monkeypatch):
    monkeypatch.setenv("LSE_API_KEY", FAKE_KEY)
    provider = LSEProvider()
    captured = {}

    def fake_request(path, params):
        captured["path"] = path
        captured["params"] = params
        return {"candles": [
            {"date": "2026-07-06", "open": 100, "high": 102,
             "low": 99, "close": 101, "volume": 5000},
            {"date": "2026-07-07", "open": 101, "high": 104,
             "low": 100, "close": 103, "volume": 6000},
        ]}

    monkeypatch.setattr(provider, "_request", fake_request)
    snap = provider.snapshot("btc-usd", lookback_days=30)
    assert snap.ticker == "BTC-USD"
    assert snap.provider == "lse"
    assert snap.price == 103
    assert snap.as_of == "2026-07-07"
    assert captured["path"] == "/candles"
    assert captured["params"]["symbol"] == "BTC-USD"
    assert captured["params"]["interval"] == "1d"


def test_candles_path_override(monkeypatch):
    monkeypatch.setenv("LSE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LSE_CANDLES_PATH", "/v2/history")
    provider = LSEProvider()
    seen = {}
    monkeypatch.setattr(provider, "_request",
                        lambda path, params: seen.setdefault("path", path) and [])
    provider.fetch_candles("AAPL", 10)
    assert seen["path"] == "/v2/history"


def test_request_would_send_both_auth_headers(monkeypatch):
    """The key must ride in both Bearer and X-API-Key headers."""
    monkeypatch.setenv("LSE_API_KEY", FAKE_KEY)
    provider = LSEProvider()
    seen = {}

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps([]).encode()

    def fake_urlopen(req, timeout=None, context=None):
        seen["auth"] = req.get_header("Authorization")
        seen["xkey"] = req.get_header("X-api-key")
        return FakeResp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider._request("/candles", {"symbol": "X"})
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["xkey"] == FAKE_KEY


def test_no_key_raises(monkeypatch):
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    monkeypatch.delenv("HEDGEFUND_LSE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LSE_API_KEY"):
        LSEProvider()._request("/candles", {})
