"""The proposal ledger — protocol v3 (docs/deliberation-protocol.md §9b).

During deliberation the shared document is frozen. Turns propose executable
changes and vote on outstanding ones; the room converges when every proposal is
settled and a lap adds nothing new; then the approved plan is executed once, as
ops, attributed to each proposal's author.

Pure functions only — persistence lives in db.models.Proposal / ProposalVote and
the turn runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from conclave.domain.docops import (
    DocOpError,
    OpRecord,
    apply_op,
    available_anchors,
    normalize_anchor,
    strip_anchor_tag_line,
    strip_anchor_tags,
)

PROPOSAL_KINDS = ("add_section", "edit_section", "delete_section", "merge_sections")
STANCES = ("agree", "reject")


@dataclass
class ProposalRecord:
    """One proposed change, DB row or in-memory. num orders proposals within a room
    and is what experts refer to ("P3")."""

    num: int
    kind: str
    payload: dict
    reason: str
    expert_name: str
    lap: int
    status: str = "open"  # open | approved | rejected | superseded
    supersedes: int | None = None  # an amend replaces this earlier proposal
    superseded_by: int | None = None


@dataclass
class VoteRecord:
    proposal_num: int
    expert_name: str
    stance: str  # agree | reject  (an amend is recorded as reject + a new proposal)
    reason: str = ""
    lap: int = 0


@dataclass
class Settlement:
    """Where the ledger stands after applying votes."""

    approved: list[ProposalRecord] = field(default_factory=list)
    rejected: list[ProposalRecord] = field(default_factory=list)
    open: list[ProposalRecord] = field(default_factory=list)  # awaiting votes
    superseded: list[ProposalRecord] = field(default_factory=list)

    @property
    def settled(self) -> bool:
        return not self.open


# --- validation --------------------------------------------------------------


def sanitize_payload(args: dict) -> dict:
    """Same ingestion hygiene as DocTools: models echo {#anchor} tags and decorate
    anchors; stored proposals must be clean."""
    payload = {k: v for k, v in args.items() if k != "reason" and v is not None}
    if "heading" in payload:
        payload["heading"] = strip_anchor_tag_line(str(payload["heading"]))
    for key in ("text", "new_text"):
        if key in payload:
            payload[key] = strip_anchor_tags(str(payload[key]))
    for key in ("anchor", "after_anchor"):
        if key in payload:
            payload[key] = normalize_anchor(str(payload[key]))
    if "anchors" in payload:
        payload["anchors"] = [normalize_anchor(str(a)) for a in payload["anchors"]]
    return payload


def proposal_to_ops(
    prop: ProposalRecord, *, doc_text: str, start_seq: int, lap: int
) -> list[OpRecord]:
    """Compile one proposal into concrete ops against the given document text.
    merge_sections becomes edit(first) + delete(rest). Raises DocOpError if the
    proposal cannot apply (bad anchor etc.)."""
    p = prop.payload
    common = dict(reason=prop.reason, expert_name=prop.expert_name, lap=lap)
    if prop.kind in ("add_section", "edit_section", "delete_section"):
        return [OpRecord(seq=start_seq, kind=prop.kind, payload=dict(p), **common)]
    if prop.kind == "merge_sections":
        anchors = list(p.get("anchors") or [])
        if len(anchors) < 2:
            raise DocOpError("merge_sections needs at least two anchors")
        present = set(available_anchors(doc_text))
        missing = [a for a in anchors if a not in present]
        if missing:
            raise DocOpError("merge_sections: unknown anchor(s) " + ", ".join(missing))
        heading = str(p.get("heading") or "")
        text = str(p.get("text") or "")
        first, rest = anchors[0], anchors[1:]
        new_text = f"## {heading}\n{text}" if heading else text
        ops = [
            OpRecord(
                seq=start_seq,
                kind="edit_section",
                payload={"anchor": first, "new_text": new_text},
                **common,
            )
        ]
        for i, a in enumerate(rest, start=1):
            ops.append(
                OpRecord(
                    seq=start_seq + i, kind="delete_section", payload={"anchor": a}, **common
                )
            )
        return ops
    raise DocOpError(f"Unknown proposal kind {prop.kind}")


def dry_run(prop: ProposalRecord, *, doc_text: str) -> str | None:
    """Error message if the proposal cannot apply to doc_text, else None. Used at
    proposal time so broken proposals are refused at the door, visibly."""
    try:
        text = doc_text
        for op in proposal_to_ops(prop, doc_text=doc_text, start_seq=1, lap=prop.lap):
            text, _ = apply_op(text, op, strict=True)
    except DocOpError as exc:
        return str(exc)
    return None


# --- settlement ---------------------------------------------------------------


TERMINAL = ("executed", "skipped")


def settle(
    proposals: list[ProposalRecord],
    votes: list[VoteRecord],
    *,
    voters: list[str],
) -> Settlement:
    """The standing rule. A proposal is:
    - rejected when any seat rejects it — rejection is a staked act with a reason
      on record; one is enough to keep a change out of the plan;
    - approved when it has no reject and every seat other than its author has voted;
    - open otherwise (some seat still owes a vote);
    - superseded when a *live* amendment replaced it. An amendment that is itself
      rejected revives the original: the room said no to the change, not to the
      thing it was changing, and the original's votes still stand.
    Terminal statuses (executed, skipped) are sticky: an executed proposal is
    history, never re-planned. A proposal's own author never votes on it."""
    rejected_nums: set[int] = set()
    voted: dict[int, set[str]] = {}
    for v in votes:
        voted.setdefault(v.proposal_num, set()).add(v.expert_name)
        if v.stance == "reject":
            rejected_nums.add(v.proposal_num)
    by_num = {p.num: p for p in proposals}

    def superseded_live(p: ProposalRecord) -> bool:
        """True if some chain of amendments off p is still alive (not rejected)."""
        nxt = p.superseded_by
        while nxt is not None and nxt in by_num:
            amend = by_num[nxt]
            if amend.status in TERMINAL:
                return True
            if amend.num not in rejected_nums:
                return True
            # This amendment was rejected; look through it to any amendment *of it*.
            nxt = amend.superseded_by
        return False

    out = Settlement()
    for p in proposals:
        if p.status in TERMINAL:
            continue  # history, not part of the live ledger
        if superseded_live(p):
            out.superseded.append(p)
        elif p.num in rejected_nums:
            out.rejected.append(p)
        elif {n for n in voters if n != p.expert_name}.issubset(voted.get(p.num, set())):
            out.approved.append(p)
        else:
            out.open.append(p)
    return out


def open_nums(
    proposals: list[ProposalRecord], votes: list[VoteRecord], *, voters: list[str]
) -> set[int]:
    """Numbers of proposals currently awaiting votes — the only ones a seat may
    vote on or amend. Derived from settle(), so a revived original counts."""
    return {p.num for p in settle(proposals, votes, voters=voters).open}


def duplicate_topics(anchors: list[str]) -> list[list[str]]:
    """Groups of anchors that look like the same topic left unreconciled — the
    union seed's collision suffixes ("plan", "plan-bo") or a numeric suffix
    ("resolution", "resolution-2"). Reported to the confirmation lap so a merge
    that missed one is caught immediately, not a lap later."""
    import re

    groups: dict[str, list[str]] = {}
    for a in anchors:
        base = re.sub(r"-\d+$", "", a)
        groups.setdefault(base, []).append(a)
    out = [g for g in groups.values() if len(g) > 1]
    # Author-suffixed collisions: "x-<name>" where "x" also exists.
    present = set(anchors)
    for a in anchors:
        for b in anchors:
            if b != a and b.startswith(a + "-") and a in present:
                grp = next((g for g in out if a in g), None)
                if grp is None:
                    out.append([a, b])
                elif b not in grp:
                    grp.append(b)
    return out


def apply_settlement_status(s: Settlement) -> None:
    for p in s.approved:
        p.status = "approved"
    for p in s.rejected:
        p.status = "rejected"
    for p in s.open:
        p.status = "open"
    for p in s.superseded:
        p.status = "superseded"


def compile_plan(
    approved: list[ProposalRecord], *, doc_text: str, start_seq: int, lap: int
) -> tuple[list[OpRecord], str, list[tuple[ProposalRecord, str]]]:
    """Execute the approved plan against doc_text, in proposal order. Returns
    (ops, final_text, skipped) — a proposal that no longer applies (its anchor was
    removed by an earlier approved change) is skipped and reported, never guessed."""
    ops: list[OpRecord] = []
    text = doc_text
    skipped: list[tuple[ProposalRecord, str]] = []
    seq = start_seq
    for prop in sorted(approved, key=lambda p: p.num):
        try:
            batch = proposal_to_ops(prop, doc_text=text, start_seq=seq, lap=lap)
            new_text = text
            for op in batch:
                new_text, _ = apply_op(new_text, op, strict=True)
        except DocOpError as exc:
            skipped.append((prop, str(exc)))
            continue
        ops.extend(batch)
        seq += len(batch)
        text = new_text
    return ops, text, skipped


# --- rendering for prompts ------------------------------------------------------


def describe_proposal(p: ProposalRecord, *, full: bool = True) -> str:
    pl = p.payload
    tag = f"P{p.num} [{p.expert_name}, lap {p.lap}]"
    if p.kind == "add_section":
        where = pl.get("after_anchor") or "end"
        head = f'{tag} ADD section "{pl.get("heading", "")}" after §{where}'
        body = str(pl.get("text", ""))
    elif p.kind == "edit_section":
        head = f"{tag} EDIT §{pl.get('anchor', '')}"
        body = str(pl.get("new_text", ""))
    elif p.kind == "delete_section":
        head = f"{tag} DELETE §{pl.get('anchor', '')}"
        body = ""
    elif p.kind == "merge_sections":
        anchors = ", §".join(pl.get("anchors") or [])
        head = f'{tag} MERGE §{anchors} → "{pl.get("heading", "")}"'
        body = str(pl.get("text", ""))
    else:
        head, body = f"{tag} {p.kind}", ""
    lines = [head, f"  reason: {p.reason}"]
    if p.supersedes:
        lines.append(f"  amends P{p.supersedes}")
    if full and body:
        lines.append("  text:")
        lines.extend("    " + ln for ln in body.rstrip().splitlines())
    return "\n".join(lines)


def ledger_lines(
    proposals: list[ProposalRecord],
    votes: list[VoteRecord],
    *,
    voters: list[str],
    for_expert: str | None = None,
) -> str:
    """The ledger as the prompt shows it: every live proposal with its votes, and
    (if for_expert) which open ones this seat still owes a vote on."""
    s = settle(proposals, votes, voters=voters)
    by_num: dict[int, list[VoteRecord]] = {}
    for v in votes:
        by_num.setdefault(v.proposal_num, []).append(v)
    out: list[str] = []

    def block(title: str, items: list[ProposalRecord], full: bool) -> None:
        if not items:
            return
        out.append(f"### {title}")
        for p in sorted(items, key=lambda p: p.num):
            out.append(describe_proposal(p, full=full))
            vs = by_num.get(p.num, [])
            if vs:
                out.append(
                    "  votes: "
                    + "; ".join(
                        f"{v.expert_name} {v.stance}" + (f" ({v.reason})" if v.reason else "")
                        for v in vs
                    )
                )
            if (
                for_expert
                and for_expert != p.expert_name
                and p in s.open
                and for_expert not in {v.expert_name for v in vs}
            ):
                out.append("  <- YOU HAVE NOT VOTED ON THIS")
            out.append("")

    block("Open proposals (awaiting votes)", s.open, full=True)
    block("Approved so far (will execute)", s.approved, full=False)
    block("Rejected", s.rejected, full=False)
    return "\n".join(out).rstrip() or "(no proposals yet)"


def next_num(proposals: list[ProposalRecord]) -> int:
    return max((p.num for p in proposals), default=0) + 1
