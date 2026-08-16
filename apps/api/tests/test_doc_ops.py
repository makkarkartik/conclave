"""Protocol v2 substrate: the document as a fold over attributed operations."""

from __future__ import annotations

import pytest

from conclave.domain.docops import (
    DocOpError,
    OpRecord,
    annotate_anchors,
    apply_op,
    available_anchors,
    blame_lines,
    fold,
    normalize_anchor,
    ops_log_lines,
    parse_sections,
    slugify,
    strip_anchor_tag_line,
    strip_anchor_tags,
    suppressed_seqs,
)


def op(seq, kind, reason="", name="Ada", lap=0, **payload):
    return OpRecord(seq=seq, kind=kind, payload=payload, reason=reason, expert_name=name, lap=lap)


# ---------- parsing ----------


def test_slugify_github_style():
    assert slugify("Rollback plan") == "rollback-plan"
    assert slugify("Phase 2: Cutover (draft!)") == "phase-2-cutover-draft"
    assert slugify("  ") == "section"


def test_parse_sections_intro_and_duplicates():
    text = "preamble\n\n# Plan\nbody\n\n## Steps\none\n\n## Steps\ntwo\n"
    secs = parse_sections(text)
    assert [s.anchor for s in secs] == ["_intro", "plan", "steps", "steps-2"]


def test_parse_ignores_headings_in_code_fences():
    text = "# Real\n\n```\n# not a heading\n```\n\n## Also real\n"
    assert available_anchors(text) == ["real", "also-real"]


def test_annotate_anchors_tags_headings():
    out = annotate_anchors("# Plan\nbody\n")
    assert "{#plan}" in out


def test_strip_anchor_tags_only_touches_heading_lines():
    text = "## Bottom line  {#bottom-line}\n\nbody with {#not-a-tag} inline\n"
    out = strip_anchor_tags(text)
    assert "{#bottom-line}" not in out
    assert "{#not-a-tag} inline" in out  # body lines untouched
    assert strip_anchor_tag_line("Bottom line  {#bottom-line}") == "Bottom line"


def test_normalize_anchor_accepts_model_decorations():
    for raw in ("bottom-line", "{#bottom-line}", "#bottom-line", "§bottom-line", "## Bottom line"):
        assert normalize_anchor(raw) == "bottom-line"
    assert normalize_anchor("start") == "start"
    assert normalize_anchor("_intro") == "_intro"


# ---------- single-op application ----------


def test_add_edit_delete_roundtrip():
    text, _ = apply_op("", op(1, "add_section", heading="Plan", text="v1"), strict=True)
    assert "## Plan" in text and "v1" in text
    text, _ = apply_op(text, op(2, "edit_section", anchor="plan", new_text="v2"), strict=True)
    assert "v2" in text and "v1" not in text
    assert "## Plan" in text  # body-only edit preserves the heading
    text, _ = apply_op(text, op(3, "delete_section", anchor="plan"), strict=True)
    assert text == ""


def test_add_after_anchor_and_start():
    text, _ = apply_op("", op(1, "add_section", heading="A", text="a"), strict=True)
    text, _ = apply_op(text, op(2, "add_section", heading="C", text="c"), strict=True)
    text, _ = apply_op(
        text, op(3, "add_section", heading="B", text="b", after_anchor="a"), strict=True
    )
    assert available_anchors(text) == ["a", "b", "c"]
    text, _ = apply_op(
        text, op(4, "add_section", heading="Z", text="z", after_anchor="start"), strict=True
    )
    assert available_anchors(text)[0] == "z"


def test_edit_with_full_block_can_rename():
    text, _ = apply_op("", op(1, "add_section", heading="Old name", text="body"), strict=True)
    text, anchor = apply_op(
        text, op(2, "edit_section", anchor="old-name", new_text="## New name\n\nbody2"), strict=True
    )
    assert anchor == "new-name"
    assert available_anchors(text) == ["new-name"]


def test_strict_errors_list_available_anchors():
    text, _ = apply_op("", op(1, "add_section", heading="Plan", text="x"), strict=True)
    with pytest.raises(DocOpError, match="Available anchors: plan"):
        apply_op(text, op(2, "edit_section", anchor="nope", new_text="y"), strict=True)
    with pytest.raises(DocOpError, match="already exists"):
        apply_op(text, op(3, "add_section", heading="Plan", text="again"), strict=True)


def test_replay_is_total_when_strict_would_fail():
    # Delete of a missing section: no-op. Edit of a missing section: re-added at end.
    text, _ = apply_op("intro\n", op(1, "delete_section", anchor="gone"), strict=False)
    assert "intro" in text
    text, _ = apply_op("", op(2, "edit_section", anchor="plan", new_text="body"), strict=False)
    assert "body" in text


# ---------- fold, revert, blame ----------


def build_log():
    return [
        op(1, "baseline", text="# Doc\n\nintro\n", name="Chair"),
        op(2, "add_section", heading="Rollback", text="steps", name="Ada", lap=1, reason="safety"),
        op(3, "edit_section", anchor="rollback", new_text="better steps", name="Bo", lap=2),
        op(4, "delete_section", anchor="rollback", name="Cy", lap=3, reason="redundant"),
    ]


def test_fold_applies_in_order():
    r = fold(build_log())
    assert "# Doc" in r.text and "Rollback" not in r.text


def test_revert_restores_deleted_work():
    log = build_log() + [op(5, "revert", target_seq=4, name="Ada", lap=3, reason="not redundant")]
    r = fold(log)
    assert "Rollback" in r.text and "better steps" in r.text
    # Blame lands on the surviving edit, not the suppressed delete.
    assert r.blame["rollback"].expert_name == "Bo"


def test_revert_of_revert_reinstates():
    log = build_log() + [
        op(5, "revert", target_seq=4, name="Ada"),
        op(6, "revert", target_seq=5, name="Cy"),
    ]
    assert suppressed_seqs(log) == {5}  # the second revert kills the first; op 4 stands
    r = fold(log)
    assert "Rollback" not in r.text  # delete is back in force


def test_fold_starts_from_last_active_baseline():
    log = build_log() + [op(5, "baseline", text="# Fresh\n", name="Chair", lap=4)]
    r = fold(log)
    assert r.text.startswith("# Fresh")
    assert "Rollback" not in r.text


async def test_doctools_sanitizes_echoed_annotations():
    """A model that copies the prompt's annotated heading line into an edit must not
    mint a doubled anchor (slugify('Bottom line {#bottom-line}') != 'bottom-line')."""
    from conclave.runtime.turn import DocTools

    dt = DocTools([], expert_name="Ada", lap=0)
    await dt.execute(
        "add_section", {"heading": "Bottom line", "text": "v1", "reason": "seed"}
    )
    out = await dt.execute(
        "edit_section",
        {
            "anchor": "{#bottom-line}",
            "new_text": "## Bottom line  {#bottom-line}\n\nv2",
            "reason": "revise",
        },
    )
    assert out.startswith("Applied")
    assert available_anchors(dt.doc_text) == ["bottom-line"]
    assert "v2" in dt.doc_text and "{#" not in dt.doc_text


def test_blame_and_log_render():
    log = build_log()[:3]
    r = fold(log)
    lines = blame_lines(r)
    assert "§rollback: Bo (lap 2, op 3)" in lines
    logs = ops_log_lines(build_log() + [op(5, "revert", target_seq=2, name="Cy")])
    assert "op 5" in logs and "[reverted]" in logs
