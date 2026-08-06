from conclave.domain.converge import can_converge, normalize_proposal, proposals_agree


def test_normalize():
    assert normalize_proposal("  Hello   World ") == "hello world"


def test_agree():
    assert proposals_agree(["Token bucket", "token   bucket"])
    assert not proposals_agree(["a", "b"])
    assert not proposals_agree(["only-one"])


def _votes(agree: bool = True, proposal: str = "ship it"):
    return [
        {"agree": agree, "proposal": proposal, "forfeit": False},
        {"agree": agree, "proposal": proposal, "forfeit": False},
    ]


def test_cannot_converge_before_min_laps():
    assert not can_converge(lap=1, chair_count=2, votes=_votes())
    assert not can_converge(lap=2, chair_count=2, votes=_votes())


def test_can_converge_after_debate():
    assert can_converge(lap=3, chair_count=2, votes=_votes())
    assert not can_converge(lap=3, chair_count=2, votes=_votes(agree=False))
    assert not can_converge(
        lap=3,
        chair_count=2,
        votes=[
            {"agree": True, "proposal": "a", "forfeit": False},
            {"agree": True, "proposal": "b", "forfeit": False},
        ],
    )
