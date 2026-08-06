from pathlib import Path

from conclave.domain.files import (
    edit_shared_doc,
    read_shared_doc,
    remove_conversation_dir,
    write_shared_doc,
)
from conclave.domain.mask import mask_key


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("short") == "••••"
    assert mask_key("sk-abcdefghijklmnop").startswith("sk-")
    assert mask_key("sk-abcdefghijklmnop").endswith("mnop")


def test_shared_doc_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("conclave.domain.files.DATA_DIR", tmp_path)
    cid = "conv-test"
    write_shared_doc(cid, "# Hello\n")
    assert "Hello" in read_shared_doc(cid)
    edit_shared_doc(cid, "append", "World")
    assert "World" in read_shared_doc(cid)
    edit_shared_doc(cid, "replace", "Only")
    assert read_shared_doc(cid) == "Only"
    assert (tmp_path / "conversations" / cid / "shared.md").exists()
    remove_conversation_dir(cid)
    assert not (tmp_path / "conversations" / cid).exists()
