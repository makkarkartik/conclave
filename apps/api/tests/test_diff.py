from conclave.domain.diff import format_doc_change, is_stub_doc


def test_stub():
    assert is_stub_doc("")
    assert is_stub_doc("# Shared document\n\n")
    assert not is_stub_doc("# Plan\n\nDo the thing")


def test_create_from_stub():
    diff = format_doc_change("# Shared document\n\n", "# Plan\n\n- ship it\n", mode="replace")
    assert "Created shared document" in diff
    assert "+ # Plan" in diff
    assert "+ - ship it" in diff


def test_append():
    before = "# Plan\n"
    after = "# Plan\n\n## Risk\n- cost\n"
    diff = format_doc_change(before, after, mode="append")
    assert "Appended" in diff
    assert "+ ## Risk" in diff


def test_replace_unified():
    before = "alpha\nbeta\n"
    after = "alpha\ngamma\n"
    diff = format_doc_change(before, after, mode="replace")
    assert "Updated shared document" in diff
    assert "-beta" in diff
    assert "+gamma" in diff
