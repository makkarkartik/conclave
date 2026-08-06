from __future__ import annotations

import shutil
from pathlib import Path

from conclave.db.session import DATA_DIR

ALLOWED_SUFFIXES = {".md", ".txt", ".csv", ".json", ".pdf"}
MAX_READ_CHARS = 12_000


def conversation_dir(conversation_id: str) -> Path:
    path = DATA_DIR / "conversations" / conversation_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "files").mkdir(exist_ok=True)
    return path


def remove_conversation_dir(conversation_id: str) -> None:
    path = DATA_DIR / "conversations" / conversation_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def shared_doc_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "shared.md"


def read_shared_doc(conversation_id: str) -> str:
    path = shared_doc_path(conversation_id)
    if not path.exists():
        path.write_text("# Shared document\n\n", encoding="utf-8")
    return path.read_text(encoding="utf-8")


def write_shared_doc(conversation_id: str, content: str) -> str:
    path = shared_doc_path(conversation_id)
    path.write_text(content, encoding="utf-8")
    return content


def edit_shared_doc(conversation_id: str, mode: str, content: str) -> str:
    current = read_shared_doc(conversation_id)
    if mode == "replace":
        return write_shared_doc(conversation_id, content)
    return write_shared_doc(conversation_id, current.rstrip() + "\n\n" + content.strip() + "\n")


def read_attachment_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    if p.suffix.lower() == ".pdf":
        try:
            # Best-effort: treat as binary skip if not text-extractable without deps
            raw = p.read_bytes()
            if b"%PDF" in raw[:16]:
                return "[PDF attached — text extraction limited in v1. Filename context only.]"
        except OSError:
            return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + "\n…[truncated]"
    return text
