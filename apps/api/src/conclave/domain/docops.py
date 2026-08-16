"""The shared document as a fold over attributed operations.

v2 protocol (docs/deliberation-protocol.md §3): the document is never rewritten
wholesale. Experts change it through section-level operations — add, edit, delete,
revert — each carrying a reason that lands on the permanent record. The current
text is derived by replaying the operation log; preservation is the default and
destruction is an explicit, attributed, revertable act.

Pure functions only — persistence lives in db.models.DocOp and the turn runner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Anchors for the two positional pseudo-sections.
INTRO_ANCHOR = "_intro"

KINDS = ("baseline", "add_section", "edit_section", "delete_section", "revert")


class DocOpError(ValueError):
    """Raised in strict mode (interactive tool use) so the model can correct itself.
    Replay is never strict — a fold must be total."""


@dataclass
class OpRecord:
    """One operation, DB row or staged in-memory. seq orders ops within a room."""

    seq: int
    kind: str
    payload: dict
    reason: str = ""
    expert_name: str = ""
    lap: int = 0


@dataclass
class Section:
    anchor: str
    heading: str  # full heading line ("## Rollback plan"), "" for the intro block
    body: str  # text after the heading line, up to the next heading

    @property
    def text(self) -> str:
        return f"{self.heading}\n{self.body}" if self.heading else self.body


@dataclass
class BlameEntry:
    expert_name: str
    lap: int
    seq: int
    reason: str


@dataclass
class FoldResult:
    text: str
    blame: dict[str, BlameEntry] = field(default_factory=dict)


_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ANCHOR_TAG = re.compile(r"[ \t]*\{#[-\w]+\}[ \t]*$")


def strip_anchor_tags(text: str) -> str:
    """Remove trailing {#anchor} markers from heading lines. The turn prompt shows
    headings annotated with their anchors, and models sometimes echo that line
    verbatim into an edit — without this, slugify('Bottom line {#bottom-line}')
    mints a doubled anchor and a near-duplicate section."""
    out = []
    for line in (text or "").split("\n"):
        out.append(_ANCHOR_TAG.sub("", line) if _HEADING.match(line) else line)
    return "\n".join(out)


def strip_anchor_tag_line(line: str) -> str:
    """Tag-strip for a bare heading argument (no leading #'s, so the multiline
    variant's heading check would miss it)."""
    return _ANCHOR_TAG.sub("", line or "")


def normalize_anchor(anchor: str) -> str:
    """Accept anchors however models write them: '{#bottom-line}', '#bottom-line',
    '§bottom-line', or a raw heading ('## Bottom line') all resolve the same."""
    a = (anchor or "").strip()
    a = re.sub(r"[{}§]", "", a).lstrip("#").strip()
    if not a:
        return a
    if a in (INTRO_ANCHOR, "start", "end"):
        return a
    return slugify(a) if not re.fullmatch(r"[-\w]+", a) else a.lower()


def slugify(heading_text: str) -> str:
    """GitHub-style anchor slug of a heading's text."""
    s = _SLUG_STRIP.sub("", heading_text.strip().lower())
    s = re.sub(r"[\s]+", "-", s).strip("-")
    return s or "section"


def parse_sections(text: str) -> list[Section]:
    """Split markdown into an intro block plus one section per heading (any level).
    Headings inside fenced code blocks don't count. Duplicate slugs get -2, -3…"""
    lines = (text or "").split("\n")
    sections: list[Section] = []
    seen: dict[str, int] = {}
    cur_heading = ""
    cur_anchor = INTRO_ANCHOR
    cur_body: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(cur_body)
        if cur_heading or body.strip():
            sections.append(Section(anchor=cur_anchor, heading=cur_heading, body=body))

    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            cur_heading = line
            cur_body = []
            base = slugify(m.group(2))
            n = seen.get(base, 0) + 1
            seen[base] = n
            cur_anchor = base if n == 1 else f"{base}-{n}"
        else:
            cur_body.append(line)
    flush()
    return sections


def render_sections(sections: list[Section]) -> str:
    parts = [s.text for s in sections]
    text = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n") + "\n" if text.strip() else ""


def annotate_anchors(text: str) -> str:
    """The document as shown to experts: every heading tagged with its {#anchor}."""
    out: list[str] = []
    for s in parse_sections(text):
        if s.heading:
            out.append(f"{s.heading}  {{#{s.anchor}}}")
        out.append(s.body)
    return "\n".join(out).strip("\n")


def available_anchors(text: str) -> list[str]:
    return [s.anchor for s in parse_sections(text) if s.heading]


def _as_section_block(heading: str, body: str) -> str:
    head = heading.strip()
    if head and not head.startswith("#"):
        head = f"## {head}"
    return f"{head}\n\n{body.strip()}\n" if head else f"{body.strip()}\n"


def apply_op(text: str, op: OpRecord, *, strict: bool) -> tuple[str, str | None]:
    """Apply one non-revert op. Returns (new_text, resulting_anchor).

    strict=True raises DocOpError with a corrective message (interactive tool use).
    strict=False never fails — replay of the log must be total even when reverts
    have changed the context an op originally ran in: a missing edit/add target
    degrades to append-at-end, a missing delete target is a no-op.
    """
    if op.kind == "baseline":
        return str(op.payload.get("text") or ""), None

    sections = parse_sections(text)
    anchors = [s.anchor for s in sections if s.heading]

    def missing(anchor: str) -> DocOpError:
        listing = ", ".join(anchors) or "(document has no sections yet)"
        return DocOpError(f"No section with anchor '{anchor}'. Available anchors: {listing}")

    if op.kind == "add_section":
        heading = str(op.payload.get("heading") or "")
        body = str(op.payload.get("text") or "")
        after = op.payload.get("after_anchor") or None
        block = _as_section_block(heading, body)
        new_anchor = slugify(_HEADING.match(block.split("\n", 1)[0]).group(2)) if block.startswith("#") else None
        if strict and new_anchor in anchors:
            raise DocOpError(
                f"A section '{new_anchor}' already exists — use edit_section to change it."
            )
        if after in (None, "end"):
            joined = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
            return joined, new_anchor
        if after == "start":
            intro = next((s for s in sections if not s.heading), None)
            rest = [s for s in sections if s.heading]
            parts = ([intro.text] if intro else []) + [block] + [s.text for s in rest]
            return "\n\n".join(p.strip("\n") for p in parts if p.strip()) + "\n", new_anchor
        if after not in anchors:
            if strict:
                raise missing(str(after))
            joined = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
            return joined, new_anchor
        out: list[str] = []
        for s in sections:
            out.append(s.text)
            if s.anchor == after:
                out.append(block)
        return "\n\n".join(p.strip("\n") for p in out if p.strip()) + "\n", new_anchor

    if op.kind == "edit_section":
        anchor = str(op.payload.get("anchor") or "")
        new_text = str(op.payload.get("new_text") or "")
        target = next((s for s in sections if s.anchor == anchor), None)
        if target is None:
            if strict:
                raise missing(anchor)
            # Replay fallback: the target was reverted away — re-add at the end.
            block = new_text if new_text.lstrip().startswith("#") else _as_section_block(anchor, new_text)
            joined = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block.strip("\n") + "\n"
            first = block.lstrip().split("\n", 1)[0]
            m = _HEADING.match(first)
            return joined, slugify(m.group(2)) if m else anchor
        if new_text.lstrip().startswith("#"):
            replacement = new_text.strip("\n") + "\n"
            m = _HEADING.match(new_text.lstrip().split("\n", 1)[0])
            result_anchor = slugify(m.group(2)) if m else anchor
        else:
            # Body-only edit: the heading (and thus the anchor) is preserved.
            replacement = f"{target.heading}\n\n{new_text.strip()}\n" if target.heading else new_text
            result_anchor = anchor
        out = [replacement if s.anchor == anchor else s.text for s in sections]
        return "\n\n".join(p.strip("\n") for p in out if p.strip()) + "\n", result_anchor

    if op.kind == "delete_section":
        anchor = str(op.payload.get("anchor") or "")
        if anchor not in [s.anchor for s in sections]:
            if strict:
                raise missing(anchor)
            return text, None
        out = [s.text for s in sections if s.anchor != anchor]
        return ("\n\n".join(p.strip("\n") for p in out if p.strip()) + "\n") if out else "", anchor

    raise DocOpError(f"Unknown operation kind '{op.kind}'")


def suppressed_seqs(ops: list[OpRecord]) -> set[int]:
    """Which ops a fold must skip. Reverse pass handles revert-of-revert: a revert
    that is itself reverted suppresses nothing."""
    suppressed: set[int] = set()
    for op in sorted(ops, key=lambda o: o.seq, reverse=True):
        if op.kind == "revert" and op.seq not in suppressed:
            target = op.payload.get("target_seq")
            if isinstance(target, int):
                suppressed.add(target)
    return suppressed


def fold(ops: list[OpRecord]) -> FoldResult:
    """Replay the log into (text, blame). Starts from the last active baseline —
    which is also the compaction hook: a baseline supersedes everything before it."""
    ordered = sorted(ops, key=lambda o: o.seq)
    dead = suppressed_seqs(ordered)
    active = [o for o in ordered if o.seq not in dead and o.kind != "revert"]

    start = 0
    for i, op in enumerate(active):
        if op.kind == "baseline":
            start = i
    text = ""
    blame: dict[str, BlameEntry] = {}
    for op in active[start:]:
        text, anchor = apply_op(text, op, strict=False)
        entry = BlameEntry(op.expert_name, op.lap, op.seq, op.reason)
        if op.kind == "baseline":
            blame = {s.anchor: entry for s in parse_sections(text) if s.heading}
        elif op.kind == "delete_section" and anchor:
            blame.pop(anchor, None)
        elif anchor:
            blame[anchor] = entry
    # Prune blame for anchors that no longer exist (renames leave stale keys).
    live = set(available_anchors(text))
    blame = {a: b for a, b in blame.items() if a in live}
    return FoldResult(text=text, blame=blame)


def blame_lines(result: FoldResult) -> str:
    """Compact per-section attribution for the turn prompt and the doc drawer."""
    lines = []
    for anchor in available_anchors(result.text):
        b = result.blame.get(anchor)
        if b:
            reason = f" — {b.reason}" if b.reason else ""
            lines.append(f"§{anchor}: {b.expert_name} (lap {b.lap}, op {b.seq}){reason}")
    return "\n".join(lines)


def seed_ops_from_drafts(
    drafts: list[tuple[str, str]],
    *,
    used_anchors: set[str] | None = None,
    start_seq: int = 1,
    lap: int = 0,
) -> list[OpRecord]:
    """Union seed for a sealed start (protocol v2 §7, variant c): every draft's
    sections become attributed add_section ops — nobody's work is judged away.
    Heading collisions across drafts get the author's name appended, so competing
    takes on one topic sit side by side, visibly, awaiting reconciliation. An
    orphan section (a topic only one draft thought of) can then only leave the
    document through an attributed delete with a reason.

    `drafts` are (expert_name, draft_markdown), in chair order. `used_anchors`
    carries anchors already in the document (idempotent partial re-seeding).
    """
    used = set(used_anchors or ())
    ops: list[OpRecord] = []
    seq = start_seq
    for name, text in drafts:
        for s in parse_sections(strip_anchor_tags(text or "")):
            if s.heading:
                m = _HEADING.match(s.heading)
                heading = m.group(2).strip() if m else s.heading.lstrip("# ").strip()
                body = s.body.strip()
            else:
                body = s.body.strip()
                if not body:
                    continue
                heading = f"Overview ({name})"
            if not heading:
                continue
            slug = slugify(heading)
            if slug in used:
                base = f"{heading} ({name})"
                heading, slug = base, slugify(base)
                n = 2
                while slug in used:
                    heading = f"{base} {n}"
                    slug = slugify(heading)
                    n += 1
            used.add(slug)
            ops.append(
                OpRecord(
                    seq=seq,
                    kind="add_section",
                    payload={"heading": heading, "text": body},
                    reason="Sealed draft",
                    expert_name=name,
                    lap=lap,
                )
            )
            seq += 1
    return ops


def ops_log_lines(ops: list[OpRecord], limit: int = 12) -> str:
    """The recent tail of the operation log, as shown to experts (revert targets)."""
    dead = suppressed_seqs(ops)
    lines = []
    for op in sorted(ops, key=lambda o: o.seq)[-limit:]:
        target = op.payload.get("anchor") or op.payload.get("heading") or op.payload.get("target_seq", "")
        mark = " [reverted]" if op.seq in dead else ""
        reason = f': "{op.reason}"' if op.reason else ""
        lines.append(f"op {op.seq} (lap {op.lap}) {op.expert_name} {op.kind} {target}{mark}{reason}")
    return "\n".join(lines)
