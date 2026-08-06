from __future__ import annotations

import difflib
import re

_STUB_RE = re.compile(r"^#\s*Shared document\s*$", re.IGNORECASE)


def is_stub_doc(text: str) -> bool:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return True
    return len(lines) == 1 and bool(_STUB_RE.match(lines[0]))


def format_doc_change(before: str, after: str, *, mode: str = "replace", limit: int = 80) -> str:
    """Human-readable unified diff of shared-doc edits (capped)."""
    before = before or ""
    after = after or ""
    if before == after:
        return ""

    before_lines = before.splitlines()
    after_lines = after.splitlines()

    if is_stub_doc(before) and after.strip():
        header = f"Created shared document ({mode})"
        preview = after_lines[:limit]
        body = "\n".join(f"+ {ln}" for ln in preview)
        if len(after_lines) > limit:
            body += f"\n+ … ({len(after_lines) - limit} more lines)"
        return f"{header}\n{body}"

    if mode == "append" and after.startswith(before.rstrip()):
        added = after[len(before.rstrip()) :].lstrip("\n")
        added_lines = added.splitlines() or [added]
        header = "Appended to shared document"
        preview = added_lines[:limit]
        body = "\n".join(f"+ {ln}" for ln in preview)
        if len(added_lines) > limit:
            body += f"\n+ … ({len(added_lines) - limit} more lines)"
        return f"{header}\n{body}"

    diff = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="shared.md (before)",
            tofile="shared.md (after)",
            lineterm="",
            n=2,
        )
    )
    if not diff:
        return ""
    # Drop noisy ---/+++ file headers; keep @@ hunks and +/-/context
    cleaned = [ln for ln in diff if not (ln.startswith("--- ") or ln.startswith("+++ "))]
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + [f"… ({len(diff) - limit} more diff lines truncated)"]
    return "Updated shared document\n" + "\n".join(cleaned)
