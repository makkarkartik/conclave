from types import SimpleNamespace

from conclave.services.context import MAX_SUMMARY_CHARS, fold_lap_into_summary


def msg(name="Ada", gist="argued for plan A", action="speak"):
    return SimpleNamespace(expert_name=name, gist=gist, action=action)


def test_fold_appends_one_line_per_lap():
    conv = SimpleNamespace(rolling_summary="")
    fold_lap_into_summary(conv, 0, [msg(), msg(name="Bo", gist="challenged the budget")])
    fold_lap_into_summary(conv, 1, [msg(gist="revised plan")])
    lines = conv.rolling_summary.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("Lap 0: ")
    assert "Bo: challenged the budget" in lines[0]
    assert lines[1] == "Lap 1: Ada: revised plan"


def test_fold_skips_gistless_speak_but_keeps_actions():
    conv = SimpleNamespace(rolling_summary="")
    fold_lap_into_summary(conv, 0, [msg(gist="", action="speak")])
    assert conv.rolling_summary == ""
    fold_lap_into_summary(conv, 1, [msg(gist="", action="write_proposal")])
    assert "Ada: write_proposal" in conv.rolling_summary


def test_fold_caps_summary_from_the_front():
    conv = SimpleNamespace(rolling_summary="x" * (MAX_SUMMARY_CHARS - 10))
    fold_lap_into_summary(conv, 7, [msg(gist="g" * 100)])
    assert len(conv.rolling_summary) <= MAX_SUMMARY_CHARS + 1  # leading ellipsis
    assert conv.rolling_summary.endswith("g" * 100)
