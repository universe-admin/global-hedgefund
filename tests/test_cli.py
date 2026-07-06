import json

import pytest

from hedgefund import cli


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HEDGEFUND_HOME", str(tmp_path / ".hedgefund"))
    monkeypatch.setenv("HEDGEFUND_DATA", "offline")
    monkeypatch.setenv("HEDGEFUND_LLM", "off")


def test_cli_run(capsys):
    assert cli.main(["run", "NVDA"]) == 0
    out = capsys.readouterr().out
    assert "DESK RUN — NVDA" in out
    assert "ANALYST TEAM" in out
    assert "BULL vs BEAR DEBATE" in out
    assert "RISK MANAGER" in out
    assert "FUND MANAGER — VERDICT" in out
    assert "WRITTEN THESIS" in out


def test_cli_run_json(capsys):
    assert cli.main(["--json", "run", "MU", "--no-thesis"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ticker"] == "MU"
    assert 1 <= payload["verdict"]["conviction"] <= 10


def test_cli_thesis(capsys):
    assert cli.main(["thesis", "GOOG"]) == 0
    assert "WRITTEN THESIS — GOOG" in capsys.readouterr().out


def test_cli_screen(capsys):
    assert cli.main(["screen", "NVDA", "AAPL"]) == 0
    out = capsys.readouterr().out
    assert "DESK SCREEN" in out
    assert "NVDA" in out and "AAPL" in out


def test_cli_book_and_health(capsys):
    assert cli.main(["run", "NVDA", "--execute", "--no-thesis"]) == 0
    capsys.readouterr()
    assert cli.main(["book"]) == 0
    capsys.readouterr()
    assert cli.main(["health"]) == 0
    assert "HEALTH REPORT" in capsys.readouterr().out


def test_cli_grade_unknown_run(capsys):
    assert cli.main(["grade", "doesnotexist"]) == 1
