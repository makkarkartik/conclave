"""Protocol v3 proposal ledger: settlement math and plan compilation (pure)."""

from __future__ import annotations

from conclave.domain.docops import OpRecord, fold
from conclave.domain.proposals import (
    ProposalRecord,
    VoteRecord,
    compile_plan,
    dry_run,
    ledger_lines,
    settle,
)

DOC = "## Intro\nHello.\n\n## Pricing\nCosts money.\n\n## Pricing (Bo)\nAlso costs money.\n"
SEATS = ["Ada", "Bo", "Cy"]


def P(num, kind, payload, by="Ada", **kw):
    return ProposalRecord(
        num=num, kind=kind, payload=payload, reason="because", expert_name=by, lap=1, **kw
    )


def test_silence_is_consent_once_everyone_else_voted():
    p = P(1, "delete_section", {"anchor": "pricing-bo"})
    # Only Bo has voted: Cy still owes one -> open
    s = settle([p], [VoteRecord(1, "Bo", "agree")], voters=SEATS)
    assert s.open == [p] and not s.approved
    # Cy votes agree -> approved (author Ada never votes on her own)
    s = settle([p], [VoteRecord(1, "Bo", "agree"), VoteRecord(1, "Cy", "agree")], voters=SEATS)
    assert s.approved == [p] and s.settled


def test_one_reject_keeps_a_change_out_of_the_plan():
    p = P(1, "add_section", {"heading": "FAQ", "text": "q&a"})
    s = settle(
        [p],
        [VoteRecord(1, "Bo", "agree"), VoteRecord(1, "Cy", "reject", "too verbose")],
        voters=SEATS,
    )
    assert s.rejected == [p] and not s.open and s.settled


def test_amend_supersedes_original():
    p1 = P(1, "edit_section", {"anchor": "pricing", "new_text": "## Pricing\nv1"})
    p2 = P(2, "edit_section", {"anchor": "pricing", "new_text": "## Pricing\nv2"}, by="Bo", supersedes=1)
    p1.superseded_by = 2
    s = settle([p1, p2], [VoteRecord(2, "Ada", "agree"), VoteRecord(2, "Cy", "agree")], voters=SEATS)
    assert s.superseded == [p1] and s.approved == [p2]


def test_merge_compiles_to_edit_plus_deletes_and_plan_applies_in_order():
    merge = P(
        1,
        "merge_sections",
        {"anchors": ["pricing", "pricing-bo"], "heading": "Pricing", "text": "One price."},
    )
    add = P(2, "add_section", {"heading": "FAQ", "text": "q&a"}, by="Cy")
    ops, text, skipped = compile_plan([merge, add], doc_text=DOC, start_seq=10, lap=3)
    assert not skipped
    assert [o.kind for o in ops] == ["edit_section", "delete_section", "add_section"]
    assert [o.seq for o in ops] == [10, 11, 12]
    # Attribution follows the proposer, not the executor
    assert {o.expert_name for o in ops[:2]} == {"Ada"} and ops[2].expert_name == "Cy"
    assert "One price." in text and "Also costs money" not in text and "## FAQ" in text


def test_plan_skips_a_proposal_its_predecessor_invalidated():
    delete = P(1, "delete_section", {"anchor": "pricing"})
    edit = P(2, "edit_section", {"anchor": "pricing", "new_text": "## Pricing\nnew"}, by="Bo")
    ops, text, skipped = compile_plan([delete, edit], doc_text=DOC, start_seq=1, lap=2)
    assert len(ops) == 1 and len(skipped) == 1 and skipped[0][0] is edit
    assert "## Pricing\n" not in text or "Pricing (Bo)" in text


def test_dry_run_refuses_broken_proposals_at_the_door():
    assert dry_run(P(1, "edit_section", {"anchor": "nope", "new_text": "x"}), doc_text=DOC)
    assert dry_run(P(1, "merge_sections", {"anchors": ["pricing"], "heading": "P", "text": "t"}), doc_text=DOC)
    assert dry_run(P(1, "delete_section", {"anchor": "pricing-bo"}), doc_text=DOC) is None


def test_ledger_flags_what_this_seat_still_owes():
    p = P(1, "delete_section", {"anchor": "pricing-bo"})
    text = ledger_lines([p], [VoteRecord(1, "Bo", "agree")], voters=SEATS, for_expert="Cy")
    assert "YOU HAVE NOT VOTED" in text
    text_bo = ledger_lines([p], [VoteRecord(1, "Bo", "agree")], voters=SEATS, for_expert="Bo")
    assert "YOU HAVE NOT VOTED" not in text_bo
    # The author is never asked to vote on her own proposal
    text_ada = ledger_lines([p], [], voters=SEATS, for_expert="Ada")
    assert "YOU HAVE NOT VOTED" not in text_ada


def test_compiled_ops_fold_like_any_others():
    base = [OpRecord(seq=1, kind="baseline", payload={"text": DOC}, expert_name="seed", lap=0)]
    add = P(1, "add_section", {"heading": "FAQ", "text": "q&a"}, by="Cy")
    ops, _, _ = compile_plan([add], doc_text=fold(base).text, start_seq=2, lap=2)
    folded = fold(base + ops)
    assert "## FAQ" in folded.text and folded.blame["faq"].expert_name == "Cy"


# --- ledger-semantics fixes found in live rooms (Bertrand's Box, Two-Envelope) ---


def test_rejected_amendment_revives_the_original():
    """Room 1: P2 amended by P3; P3 rejected. Under the old rule P2 stayed
    superseded and nothing approved survived - the room had to re-propose the
    consensus text. Now the room said no to the amendment, not to P2."""
    p2 = P(2, "edit_section", {"anchor": "pricing", "new_text": "## Pricing\nv2"}, by="Sol")
    p3 = P(3, "edit_section", {"anchor": "pricing", "new_text": "## Pricing\nv3"}, by="Ada", supersedes=2)
    p2.superseded_by = 3
    votes = [
        VoteRecord(2, "Bo", "agree"), VoteRecord(2, "Cy", "agree"),  # P2 had full support
        VoteRecord(3, "Sol", "reject", "adds nothing"), VoteRecord(3, "Bo", "reject", "scope"),
    ]
    s = settle([p2, p3], votes, voters=SEATS + ["Sol"])
    assert s.rejected == [p3]
    assert p2 in s.approved or p2 in s.open  # revived, not superseded
    assert p2 not in s.superseded


def test_amendment_chain_looks_through_rejected_links():
    """P1 <- P2 (rejected) <- P3 (live, amends P2): P1 is still superseded, by
    the live P3 at the end of the chain."""
    p1 = P(1, "delete_section", {"anchor": "pricing-bo"}, by="Ada")
    p2 = P(2, "delete_section", {"anchor": "pricing-bo"}, by="Bo", supersedes=1)
    p3 = P(3, "delete_section", {"anchor": "pricing-bo"}, by="Cy", supersedes=2)
    p1.superseded_by, p2.superseded_by = 2, 3
    s = settle([p1, p2, p3], [VoteRecord(2, "Ada", "reject", "x")], voters=SEATS)
    # P1 and P2 are both replaced by the live P3; P3 is what the room votes on.
    assert p1 in s.superseded and p2 in s.superseded and p3 in s.open


def test_executed_proposals_are_history_not_plan():
    """Room 2: after execution, P5 (still 'approved' in the DB) was recompiled
    on the next execution pass and reported as skipped. Terminal statuses are
    sticky - the ledger never re-plans them."""
    done = P(1, "delete_section", {"anchor": "pricing-bo"}, status="executed")
    fresh = P(2, "add_section", {"heading": "FAQ", "text": "q&a"}, by="Bo")
    s = settle([done, fresh], [VoteRecord(2, "Ada", "agree"), VoteRecord(2, "Cy", "agree")], voters=SEATS)
    assert s.approved == [fresh]
    assert done not in s.approved + s.open + s.rejected + s.superseded


def test_duplicate_topics_flags_unreconciled_sections():
    from conclave.domain.proposals import duplicate_topics

    # Room 2's leftover: an executed merge missed "resolution-2".
    groups = duplicate_topics(["intro", "resolution", "resolution-2", "faq"])
    assert groups == [["resolution", "resolution-2"]]
    # Union-seed author collisions count too; unrelated hyphens do not.
    groups = duplicate_topics(["plan", "plan-bo", "bottom-line", "costs"])
    assert ["plan", "plan-bo"] in groups and len(groups) == 1
    assert duplicate_topics(["a", "b", "c"]) == []
