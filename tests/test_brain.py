from hedgefund.brain.orchestrator import HermesBrain


def test_full_desk_run_offline(config):
    brain = HermesBrain(config)
    run = brain.run_desk("NVDA")
    assert run.ticker == "NVDA"
    assert len(run.analyst_reports) == 7
    assert run.debate is not None and len(run.debate.turns) == 4
    assert run.research is not None
    assert run.plan is not None
    assert run.risk is not None
    assert run.verdict is not None
    assert run.thesis is not None
    assert 1 <= run.verdict.conviction <= 10
    # journaled
    assert brain.memory.history("NVDA")
    assert brain.memory.history("NVDA")[0].run_id == run.run_id


def test_execute_updates_book(config):
    brain = HermesBrain(config)
    run = brain.run_desk("NVDA", execute=True)
    if run.verdict.action in ("BUY", "ADD", "HOLD / ACCUMULATE") \
            and run.verdict.size_pct_nav > 0:
        pos = brain.book.get("NVDA")
        assert pos is not None
        assert pos.size_pct_nav == run.verdict.size_pct_nav
        assert run.executed
    else:  # a bearish verdict on an empty book leaves it empty
        assert brain.book.get("NVDA") is None


def test_learning_loop(config):
    brain = HermesBrain(config)
    run = brain.run_desk("NVDA", with_thesis=False)
    entry = brain.grade(run.run_id, realized_return=-0.20, horizon_days=30)
    assert entry.graded and entry.grade == "bad_call"
    lessons = brain.memory.relevant_lessons("NVDA")
    assert lessons and "NVDA" in lessons[0]
    # next run carries the lesson to the fund manager
    run2 = brain.run_desk("NVDA", with_thesis=False)
    assert run2.verdict.lessons_applied
    card = brain.memory.scorecard()
    assert card["graded"] == 1


def test_screen_ranks(config):
    brain = HermesBrain(config)
    runs = brain.screen(["NVDA", "TSLA", "MU"])
    assert len(runs) == 3
    scores = [r.research.score * r.verdict.conviction for r in runs]
    assert scores == sorted(scores, reverse=True)


def test_health_check_after_execute(config):
    brain = HermesBrain(config)
    brain.run_desk("NVDA", execute=True, with_thesis=False)
    report = brain.health_check()
    assert report.headline()
