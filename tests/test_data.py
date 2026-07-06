from hedgefund.config import Config
from hedgefund.data.offline_provider import OfflineProvider
from hedgefund.data.router import get_provider


def test_offline_snapshot_is_deterministic(provider):
    a = provider.snapshot("NVDA")
    b = provider.snapshot("NVDA")
    assert a.price == b.price
    assert [x.close for x in a.bars] == [x.close for x in b.bars]
    assert a.news[0].title == b.news[0].title


def test_offline_snapshot_anchors_curated_price(snapshot):
    assert snapshot.price == 193.0
    assert snapshot.company_name == "NVIDIA Corporation"
    assert snapshot.bars[-1].close == 193.0
    assert len(snapshot.bars) >= 250


def test_offline_handles_unknown_ticker(provider):
    snap = provider.snapshot("ZZZQ")
    assert snap.price and snap.price > 0
    assert snap.fundamentals.pe_forward is not None
    assert len(snap.bars) > 200


def test_indicators(snapshot):
    assert snapshot.sma(50) is not None
    assert snapshot.sma(200) is not None
    rsi = snapshot.rsi(14)
    assert rsi is not None and 0 <= rsi <= 100
    vol = snapshot.realized_vol(20)
    assert vol is not None and 0.02 < vol < 3.0
    assert snapshot.total_return(21) is not None


def test_router_forced_offline():
    cfg = Config(data_provider="offline")
    assert get_provider(cfg).name == "offline"


def test_router_auto_falls_back():
    cfg = Config(data_provider="auto")
    provider = get_provider(cfg)
    assert provider.available()
