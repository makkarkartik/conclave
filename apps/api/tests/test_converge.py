"""Protocol v2 convergence: a room settles when a full lap stakes nothing."""

from conclave.domain.converge import MIN_LAPS_BEFORE_CONVERGE, lap_settled


def turn(staked=False, forfeit=False):
    return {"staked": staked, "forfeit": forfeit}


def test_min_laps_floor():
    quiet = [turn(), turn()]
    assert MIN_LAPS_BEFORE_CONVERGE == 3
    assert not lap_settled(laps_done=2, chair_count=2, turns=quiet)
    assert lap_settled(laps_done=3, chair_count=2, turns=quiet)


def test_any_stake_holds_the_room_open():
    assert not lap_settled(laps_done=5, chair_count=2, turns=[turn(), turn(staked=True)])


def test_forfeits_do_not_settle_a_room():
    # A lap of passes (e.g. consecutive error turns) must not read as consent.
    all_out = [turn(forfeit=True), turn(forfeit=True)]
    assert not lap_settled(laps_done=5, chair_count=2, turns=all_out)


def test_one_forfeit_among_consents_still_settles():
    turns = [turn(), turn(), turn(forfeit=True)]
    assert lap_settled(laps_done=3, chair_count=3, turns=turns)


def test_too_few_active_turns_does_not_settle():
    turns = [turn(), turn(forfeit=True), turn(forfeit=True)]
    assert not lap_settled(laps_done=3, chair_count=3, turns=turns)


def test_forfeited_stake_is_ignored():
    # A forfeit row can't stake; only active turns count either way.
    turns = [turn(), turn(), turn(forfeit=True, staked=True)]
    assert lap_settled(laps_done=4, chair_count=3, turns=turns)
