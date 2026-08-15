from conclave.domain.converge import (
    lap_converged,
    normalize_proposal,
    proposal_fingerprint,
)


def turn(agree=True, forfeit=False, proposal="ship plan A"):
    return {
        "agree": agree,
        "forfeit": forfeit,
        "proposal_hash": "" if forfeit else proposal_fingerprint(proposal),
    }


def test_normalize_collapses_whitespace_and_case():
    assert normalize_proposal("  Ship\n\nPlan   A ") == "ship plan a"


def test_fingerprint_stable_across_formatting():
    assert proposal_fingerprint("Ship Plan A") == proposal_fingerprint("  ship   plan a\n")
    assert proposal_fingerprint("") == ""
    assert proposal_fingerprint("x") != proposal_fingerprint("y")


def test_no_convergence_before_min_laps():
    turns = [turn(), turn()]
    assert not lap_converged(laps_done=2, chair_count=2, turns=turns)
    assert lap_converged(laps_done=3, chair_count=2, turns=turns)


def test_dissent_blocks_convergence():
    turns = [turn(), turn(agree=False)]
    assert not lap_converged(laps_done=5, chair_count=2, turns=turns)


def test_differing_proposals_block_convergence():
    turns = [turn(proposal="plan A"), turn(proposal="plan B")]
    assert not lap_converged(laps_done=5, chair_count=2, turns=turns)


def test_forfeits_do_not_veto_but_quorum_required():
    # 3 chairs: one forfeit still leaves quorum (chair_count - 1)
    turns = [turn(), turn(), turn(forfeit=True)]
    assert lap_converged(laps_done=3, chair_count=3, turns=turns)
    # two forfeits: below quorum
    turns = [turn(), turn(forfeit=True), turn(forfeit=True)]
    assert not lap_converged(laps_done=3, chair_count=3, turns=turns)


def test_empty_proposals_never_converge():
    turns = [turn(proposal=""), turn(proposal="")]
    assert not lap_converged(laps_done=5, chair_count=2, turns=turns)
