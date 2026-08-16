# Conclave deliberation protocol v2

Status: **decided, not yet implemented** · 2026-08-15
Supersedes the v1 mechanism (whole-document `write_proposal`, unanimous `agree` votes,
fingerprint-equality convergence). The engine — claim loop, leases, laps, pause,
follow-ups ([architecture.md](architecture.md)) — is untouched by this redesign.

---

## 1. What we are keeping, and why it is the product

**One shared document, edited sequentially by every expert, with full history.**
This is the thing no one else in the landscape has. Karpathy's `llm-council` and its
whole ecosystem (Perplexity Model Council included) run *parallel* answers into a
chairman synthesis — the models never see each other's work. Conclave's document is a
communication medium: B's edit is both a contribution and a message to C; C can see
what A built, what B traded away, and act on that. It happened live: an expert noticed
a section another expert's rewrite had silently dropped, and restored it.

That incident is also the indictment: the collaboration succeeded **despite** the
medium. v1's `write_proposal(full_text)` is wiki-page-replacement semantics — losing
work is the invisible default, preserving it costs vigilance. v2 inverts that.

## 2. Failure modes v2 fixes

| # | Failure (v1) | Evidence | Fix (v2) |
|---|---|---|---|
| 1 | Whole-document overwrite silently destroys prior work | NICE-section incident in the live medical room | Operation-based edits; deletion is an explicit, attributed act (§3) |
| 2 | Dissent is free, agreement runs a 5-gate gauntlet → churn, 11-lap rooms | Luna/Terra room | Staked objections: keeping the room open costs a falsifiable, on-record objection (§5) |
| 3 | Convergence measures politeness, not agreement — `speak` inherits the proposal, so fingerprint equality ≈ "nobody rewrote anything"; the real rule is unanimous self-certified `agree` | Analysis of `lap_converged` + TurnAct flow | Convergence = a full lap in which no expert stakes another operation (§6) |
| 4 | First proposal anchors the room | *Hidden Anchors* (arXiv 2606.19494) | Optional sealed-divergence prefix (§7) |
| 5 | Facts degrade across laps (rolling summary compresses evidence away) | *The Deliberative Illusion* (arXiv 2606.03032); the "illegible June records" incident was three stacked truncations | Op log is lossless; contested facts route to evidence-based adjudication, not re-argument (§8) |
| 6 | Agreement may be conformity, not corroboration | *Deliberative Illusion*; *Cost of Consensus* (arXiv 2605.00914) | Sealed prefix makes independent agreement measurable; cheap-talk `agree` is replaced by absence-of-staked-objection |
| 7 | Adversarial-by-instruction is performed, not computed — attestation gates are self-certified | agree-gate design in `turn.py` | Objections are scored against adjudication outcomes; reputation ledger (§9, later phase) |

## 3. The substrate: an operation log

The shared document stops being a text column that turns overwrite. It becomes the
**derived state of an attributed operation log** — version-control semantics instead of
wiki semantics.

Turn tools (replacing `write_proposal` / `edit_shared_doc`):

```
add_section(after_anchor, heading, text, reason)
edit_section(anchor, new_text, reason)
delete_section(anchor, reason)        # destruction is explicit, attributed, contestable
revert(op_ref, reason)                # restoring someone's work is one exact call
```

- Anchors are the document's markdown headings (slugified, stable across edits).
- `doc_ops` table beside `messages`: `(id, conversation_id, turn_message_id, expert_id,
  kind, anchor, payload, reason, lap, reverted_by)`. Current document = fold over ops;
  cache the folded text on the conversation row, rebuild on revert.
- Every section carries blame: who wrote it, who last touched it, why.
- **Preservation is the default; destruction costs.** An expert cannot silently drop a
  section by omitting it from a rewrite — there is no rewrite. It must call
  `delete_section` with a reason that lands on the record.

## 4. Operations are the claims

Everything the mechanism needs a "claim" for — a discrete, attributed, stakeable,
adjudicable unit — the op log provides natively. A `delete_section` with a reason *is*
a staked objection against that section. The claim table and the document history are
the same object. (This resolves the earlier objection that claim-decomposition shreds
lengthy artifacts: we never decompose the artifact; the *edits to it* are the claims.)

## 5. Costly dissent

An expert who wants the room to stay open must **stake** something: an operation, or a
blocking objection naming what specifically must change and why, with a confidence.
Vague dissent ("not convinced yet") does not hold the room open. `TurnAct` changes:

- `agree` (bool) and the 5 self-certified gates are **removed**.
- A turn either stakes ops / a `blocking_objection {anchor, text, confidence}` — which
  keeps the room open — or it doesn't, which is consent by silence.
- Objections are adjudicated (§8). Upheld raises the expert's standing; rejected lowers
  it. The ledger is shown in-prompt ("your objection record: 7/9 upheld") — models
  respond to stated stakes through context even though they optimize nothing.

This inverts v1's asymmetry (free "no", expensive "yes"). It is the bug-bounty shape:
reward per confirmed flaw, no reward for volume.

## 6. Convergence rule

> **The room converges when a full lap passes in which no expert stakes an operation
> or a blocking objection.**

Not "everyone said yes" — "no one will put their name behind another change." Silence
is costly-backed consent. `MIN_LAPS_BEFORE_CONVERGE` (floor 3) survives as-is; the
safety lap ceiling survives as-is. `lap_converged`'s fingerprint comparison is deleted.

## 7. Sealed-divergence prefix (optional per room)

The shared document's one genuine pathology is anchoring: whoever writes first frames
everyone after. For rooms that opt in:

1. **Sealed drafts** — each expert answers the topic independently; none sees another.
   (Parallel: these are N claimable turn rows, which the SKIP LOCKED engine already
   handles — v1 never actually exercised its own parallelism.)
2. **Recused judging** — drafts anonymized *by code* (strip names, normalize
   formatting, shuffle order per judge — never by an agent, which contaminates).
   Each expert judges only the drafts it did not write (LLM judges recognize and favor
   their own output even anonymized — Panickssery et al., arXiv 2404.13076). Verdicts
   are structured, never prose syntheses:
   `{base: A|B|C, imports: [named sections from losers], defects: [claims w/ evidence]}`
   Majority on `base` wins; no majority → one runoff with defect lists shared; still
   split → the human chair picks (a decision a chair *should* own).
3. **Seed** — the winning draft becomes the document as attributed `add_section` ops by
   its author; upheld imports enter as change requests. Then normal dialectic laps run.

Sealed prefix also makes **independent corroboration measurable**: sections asserted
by multiple sealed drafts are marked so in blame — agreement that predates contact is
evidence; agreement after reading each other is not.

## 8. Adjudication: evidence outranks opinion

Trigger: an **edit war** (edit → revert → re-assert on one anchor) or a staked
objection contesting a section. Routing is per-anchor — the rest of the document flows
on while one section is adjudicated.

The adjudicator's brief is not "who is persuasive" but *"what would settle this — find
it."* It gets `read_attachment` and web search, and must cite what it found
("upheld — attachment 1, p. 9"). Rulings are falsifiable: they carry a checkable
citation, unlike a chairman's synthesis. If evidence cannot settle it, the section
ships **marked contested, both positions preserved** — false unanimity is not an
available outcome. Where nothing is checkable it degenerates to taste; that is exactly
when "preserved as contested" is the honest output.

## 9. Reputation ledger (later phase)

Per `(expert, domain)`, decaying: objection precision (upheld/staked), calibration of
staked confidences, discovery rate (sealed-draft sections that survive to the final
document). Used two ways: mechanically (adjudicator selection, judge weighting) and
in-context (shown in the expert's prompt). Guardrails: decay (no entrenchment),
domain-conditioning (medicine ≠ code), reward yield as well as precision (or experts
learn to stake only safe objections — Goodhart).

## 10. Divergence from Karpathy's council, stated once

| | Karpathy / council ecosystem | Conclave v2 |
|---|---|---|
| Interaction | Parallel, blind; models never see each other's work | Sequential collaboration on one artifact with full history (sealed prefix only for the opening) |
| Final authority | Chairman model writes the answer (taste, unfalsifiable, can silently drop orphans) | No author of last resort: document is a fold of attributed ops; disagreement resolved per-section by evidence, or shipped as contested |
| Unit of judgment | Whole answers (only judgeable by taste) | Operations/sections (checkable, revertible, adjudicable) |
| Convergence | Chairman finishes writing | No expert will stake another change |
| Confidence in output | Uniform | Per-section provenance: independent-corroboration count, adjudication citations, contested flags |
| Judge hygiene | Single chairman, self-preference unmitigated | Recusal, code-anonymization, order shuffling, structured verdicts, defect citations required |

Shared limit, no protocol escapes it: **correlated error**. Models share training
data; N models independently asserting a common misconception looks identical to N
models being independently right. Cross-provider seats mitigate; nothing eliminates.
Never claim otherwise in the product.

## 11. Build order

Each phase is independently shippable and useful; each has a head-to-head eval hook.

1. **Op substrate** — `doc_ops` table, four turn tools, fold, blame, revert; delete
   `write_proposal`. UI: op-aware diff blocks (mostly exists), blame on DocDrawer.
   *Kills failure #1 outright.*
2. **Staked objections + new convergence** — TurnAct rework (§5), convergence rule
   (§6), delete fingerprint logic. *Kills #2, #3.*
3. **Sealed-divergence prefix** — room flag, parallel draft turns, code anonymizer,
   recused structured verdicts, seed. *Kills #4, halves #6.*
4. **Adjudication** — edit-war trigger, adjudicator turn type, contested flags in doc
   + exports. *Kills #5's worst case.*
5. **Reputation ledger** — §9. *Addresses #7.*
6. **Eval harness alongside, not after** — same topic + attachments run under
   `protocol: v1 | v2`, judged blind. The protocol switch on the conversation row is
   the eval harness. No new feature lands without this comparison existing.

Standing caveats that predate v2 and are not solved by it: regex-only PII redaction
(Presidio tier still needed before the medical room is recreated), no cost metering,
no auth/tenancy enforcement, `user_direction` never cleared after `ask` (one-line fix,
do it in phase 1).

## References

- Karpathy, `llm-council` — https://github.com/karpathy/llm-council
- *The Deliberative Illusion* — https://arxiv.org/abs/2606.03032
- *Hidden Anchors in Multi-Agent LLM Deliberation* — https://arxiv.org/abs/2606.19494
- *The Cost of Consensus* — https://arxiv.org/abs/2605.00914
- *LLM Evaluators Recognize and Favor Their Own Generations* (Panickssery et al.) — https://arxiv.org/abs/2404.13076
- *AI Safety via Debate* (Irving et al.) — https://arxiv.org/abs/1805.00899
