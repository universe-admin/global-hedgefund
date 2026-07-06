import datetime as dt

from hedgefund.portfolio.book import Book, Position
from hedgefund.portfolio.exit_rules import ExitRuleEngine
from hedgefund.portfolio.health import run_health_check


def _pos(ticker="NVDA", entry=100.0, stop=85.0, size=0.05,
         date=None, stretch=None):
    return Position(
        ticker=ticker,
        entry_price=entry,
        entry_date=date or str(dt.date.today() - dt.timedelta(days=10)),
        size_pct_nav=size,
        stop=stop,
        target_stretch=stretch,
        high_water_mark=entry,
    )


def test_book_roundtrip(config):
    book = Book(config)
    book.add(_pos())
    book2 = Book(config)  # reload from disk
    assert book2.get("NVDA") is not None
    assert book2.gross_exposure() == 0.05


def test_book_average_in(config):
    book = Book(config)
    book.add(_pos(entry=100.0, size=0.05))
    book.add(_pos(entry=200.0, size=0.05))
    p = book.get("NVDA")
    assert abs(p.size_pct_nav - 0.10) < 1e-9
    assert abs(p.entry_price - 150.0) < 1e-9


def test_book_close(config):
    book = Book(config)
    book.add(_pos())
    book.close("NVDA", 120.0, "target hit")
    assert book.get("NVDA") is None
    assert book.positions[0].status == "closed"
    assert book.positions[0].exit_price == 120.0


def test_hard_stop_triggers(config, provider):
    snap = provider.snapshot("NVDA")  # price 193
    pos = _pos(entry=300.0, stop=250.0)  # stop far above market price
    check = ExitRuleEngine(config).check(pos, snap)
    assert check.status() == "EXIT"
    assert any(s.rule == "hard stop" and s.triggered
               for s in check.signals)


def test_no_exit_when_healthy(config, provider):
    snap = provider.snapshot("NVDA")
    price = snap.last_close()
    pos = _pos(entry=price * 0.95, stop=price * 0.8)
    pos.high_water_mark = price
    check = ExitRuleEngine(config).check(pos, snap)
    assert not check.exits_triggered


def test_time_stop_only_when_losing(config, provider):
    snap = provider.snapshot("NVDA")
    price = snap.last_close()
    old = str(dt.date.today() - dt.timedelta(days=400))
    loser = _pos(entry=price * 2, stop=price * 0.1, date=old)
    winner = _pos(entry=price * 0.5, stop=price * 0.1, date=old)
    assert any(s.rule == "time stop" and s.triggered
               for s in ExitRuleEngine(config).check(loser, snap).signals)
    assert not any(s.rule == "time stop" and s.triggered
                   for s in ExitRuleEngine(config).check(winner, snap).signals)


def test_health_report(config, provider):
    book = Book(config)
    snap = provider.snapshot("NVDA")
    price = snap.last_close()
    book.add(_pos(entry=price * 0.9, stop=price * 0.75))
    report = run_health_check(book, provider, config)
    assert len(report.positions) == 1
    assert report.positions[0].status in ("HOLD", "ON WATCH")
    assert "HOLD" in report.headline()
