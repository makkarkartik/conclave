import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, ClipboardList, FileText, History, PenLine, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import { Avatar } from '../../shared/ui/Avatar'
import { api, type DocOpRow, type DocSection, type Expert, type Proposal } from '../../shared/lib/api'

function isStubDoc(text: string) {
  const t = text.trim()
  return !t || t === '# Shared document' || t === '# Shared document\n'
}

const KIND_STYLE: Record<string, { label: string; cls: string }> = {
  add_section: { label: 'added', cls: 'bg-[rgba(80,200,120,0.14)] text-[#9ddeb5]' },
  edit_section: { label: 'edited', cls: 'bg-[rgba(107,163,255,0.14)] text-[var(--color-sky)]' },
  delete_section: { label: 'deleted', cls: 'bg-[rgba(255,139,107,0.14)] text-[var(--color-coral)]' },
  revert: { label: 'revert', cls: 'bg-[rgba(255,213,138,0.14)] text-[#ffd58a]' },
  baseline: { label: 'baseline', cls: 'bg-white/[0.08] text-[var(--color-think)]' },
}

/** The document's history as a first-class view: who owns each section now, and
 * the full attributed operation log — the collaboration, made legible. */
function HistoryView({
  sections,
  ops,
  accentOf,
}: {
  sections: DocSection[]
  ops: DocOpRow[]
  accentOf: (name: string) => string | undefined
}) {
  if (!sections.length && !ops.length) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
        <History className="text-[var(--color-pass)]" size={28} />
        <p className="text-sm text-[var(--color-think)]">
          No operation history yet. Once experts shape the document, every add, edit, delete,
          and revert lands here with its author and reason.
        </p>
      </div>
    )
  }

  // Ops grouped by lap, newest lap first — recent activity is what you came for.
  const laps = new Map<number, DocOpRow[]>()
  for (const op of ops) {
    const list = laps.get(op.lap) ?? []
    list.push(op)
    laps.set(op.lap, list)
  }
  const lapEntries = [...laps.entries()].sort(([a], [b]) => b - a)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      {sections.length > 0 && (
        <div className="border-b border-[var(--color-line)] px-5 py-4">
          <div className="mb-2.5 text-[10px] font-semibold tracking-wider text-[var(--color-pass)] uppercase">
            Sections — who shaped each, last
          </div>
          <div className="space-y-1.5">
            {sections.map((s) => (
              <div key={s.anchor} className="flex items-baseline gap-2 text-xs">
                <span
                  className="relative top-px h-2 w-2 shrink-0 rounded-full"
                  style={{ background: accentOf(s.expert) || 'var(--color-pass)' }}
                />
                <span className="min-w-0 truncate font-medium text-[var(--color-speak)]">
                  {s.heading}
                </span>
                <span className="shrink-0 text-[var(--color-think)]">{s.expert}</span>
                <span className="shrink-0 text-[10px] text-[var(--color-pass)]">
                  lap {s.lap} · op {s.seq}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="px-5 py-4">
        <div className="mb-2.5 text-[10px] font-semibold tracking-wider text-[var(--color-pass)] uppercase">
          Every operation, attributed
        </div>
        <div className="space-y-4">
          {lapEntries.map(([lap, lapOps]) => (
            <div key={lap}>
              <div className="mb-1.5 text-[10px] text-[var(--color-pass)]">Lap {lap}</div>
              <div className="space-y-2 border-l border-[var(--color-line)] pl-3">
                {lapOps.map((op) => {
                  const kind = KIND_STYLE[op.kind] ?? KIND_STYLE.baseline
                  return (
                    <div key={op.seq} className={clsx('text-xs', op.reverted && 'opacity-50')}>
                      <div className="flex items-center gap-2">
                        <span className="w-8 shrink-0 text-right font-mono text-[10px] text-[var(--color-pass)]">
                          {op.seq}
                        </span>
                        <Avatar name={op.expert} accent={accentOf(op.expert)} size={18} />
                        <span className="shrink-0 font-medium text-[var(--color-speak)]">
                          {op.expert}
                        </span>
                        <span
                          className={clsx(
                            'shrink-0 rounded-full px-1.5 py-px text-[10px]',
                            kind.cls,
                          )}
                        >
                          {kind.label}
                        </span>
                        <span
                          className={clsx(
                            'min-w-0 truncate text-[var(--color-think)]',
                            op.reverted && 'line-through',
                          )}
                        >
                          {op.target}
                        </span>
                        {op.reverted && (
                          <span className="shrink-0 rounded-full bg-[rgba(255,213,138,0.14)] px-1.5 py-px text-[10px] text-[#ffd58a]">
                            undone
                          </span>
                        )}
                      </div>
                      {op.reason && (
                        <div className="mt-0.5 pl-10 text-[11px] leading-relaxed text-[var(--color-think)] italic">
                          {op.reason}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

const PROPOSAL_KIND: Record<string, { label: string; cls: string }> = {
  add_section: { label: 'add', cls: 'bg-[rgba(80,200,120,0.14)] text-[#9ddeb5]' },
  edit_section: { label: 'edit', cls: 'bg-[rgba(107,163,255,0.14)] text-[var(--color-sky)]' },
  delete_section: { label: 'delete', cls: 'bg-[rgba(255,139,107,0.14)] text-[var(--color-coral)]' },
  merge_sections: { label: 'merge', cls: 'bg-[rgba(255,213,138,0.14)] text-[#ffd58a]' },
}

const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  open: { label: 'open — awaiting votes', cls: 'text-[var(--color-sky)]' },
  approved: { label: 'approved', cls: 'text-[#9ddeb5]' },
  rejected: { label: 'rejected', cls: 'text-[var(--color-coral)]' },
  superseded: { label: 'superseded by amendment', cls: 'text-[var(--color-pass)]' },
  executed: { label: 'executed', cls: 'text-[#9ddeb5]' },
  skipped: { label: 'skipped at execution', cls: 'text-[#ffd58a]' },
}

function ProposalCard({
  p,
  accentOf,
  seats,
}: {
  p: Proposal
  accentOf: (name: string) => string | undefined
  seats: string[]
}) {
  const [open, setOpen] = useState(false)
  const kind = PROPOSAL_KIND[p.kind] ?? PROPOSAL_KIND.edit_section
  const status = STATUS_STYLE[p.status] ?? STATUS_STYLE.open
  const dim = p.status === 'superseded' || p.status === 'rejected' || p.status === 'skipped'
  const voted = new Set(p.votes.map((v) => v.expert))
  const pending = seats.filter((n) => n !== p.expert && !voted.has(n))
  return (
    <div
      className={clsx(
        'rounded-xl border border-[var(--color-line)] bg-black/15 px-3 py-2.5',
        dim && 'opacity-55',
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 w-7 shrink-0 font-mono text-[10px] text-[var(--color-pass)]">
          P{p.num}
        </span>
        <span className={clsx('mt-0.5 shrink-0 rounded-full px-1.5 py-px text-[10px]', kind.cls)}>
          {kind.label}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span
              className={clsx(
                'min-w-0 truncate text-xs font-medium text-[var(--color-speak)]',
                p.status === 'rejected' && 'line-through',
              )}
              title={p.target}
            >
              {p.target}
            </span>
            {p.supersedes && (
              <span className="shrink-0 text-[10px] text-[var(--color-pass)]">
                amends P{p.supersedes}
              </span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[var(--color-think)]">
            <Avatar name={p.expert} accent={accentOf(p.expert)} size={14} />
            <span>{p.expert}</span>
            <span className="text-[var(--color-pass)]">· lap {p.lap} ·</span>
            <span className={status.cls}>{status.label}</span>
          </div>
          {p.reason && (
            <div className="mt-1 text-[11px] leading-relaxed text-[var(--color-think)] italic">
              {p.reason}
            </div>
          )}
          {(p.votes.length > 0 || (p.status === 'open' && pending.length > 0)) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {p.votes.map((v) => (
                <span
                  key={v.expert}
                  title={v.reason || undefined}
                  className={clsx(
                    'flex items-center gap-1 rounded-full px-1.5 py-px text-[10px]',
                    v.stance === 'agree'
                      ? 'bg-[rgba(80,200,120,0.14)] text-[#9ddeb5]'
                      : 'bg-[rgba(255,139,107,0.14)] text-[var(--color-coral)]',
                  )}
                >
                  {v.stance === 'agree' ? (
                    <Check size={9} strokeWidth={3} />
                  ) : (
                    <X size={9} strokeWidth={3} />
                  )}
                  {v.expert}
                  {v.stance === 'reject' && v.reason ? ` — ${v.reason}` : ''}
                </span>
              ))}
              {p.status === 'open' &&
                pending.map((n) => (
                  <span
                    key={n}
                    className="rounded-full border border-dashed border-[var(--color-line)] px-1.5 py-px text-[10px] text-[var(--color-pass)]"
                  >
                    {n} — pending
                  </span>
                ))}
            </div>
          )}
          {p.text && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="mt-1.5 flex items-center gap-1 text-[10px] text-[var(--color-sky)] hover:underline"
            >
              <ChevronDown size={11} className={clsx('transition-transform', open && 'rotate-180')} />
              {open ? 'hide proposed text' : 'show proposed text'}
            </button>
          )}
          {open && p.text && (
            <div className="solution-md mt-2 rounded-lg border border-[var(--color-line)] bg-black/20 px-3 py-2 text-[12px]">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{p.text}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** The plan the room is deliberating (protocol v3): every proposed change, its
 * votes, and its fate. The document stays frozen until this settles. */
function PlanView({
  proposals,
  accentOf,
  seats,
  phase,
}: {
  proposals: Proposal[]
  accentOf: (name: string) => string | undefined
  seats: string[]
  phase: string
}) {
  if (!proposals.length) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
        <ClipboardList className="text-[var(--color-pass)]" size={28} />
        <p className="text-sm text-[var(--color-think)]">
          No proposals yet. The document is frozen while the room deliberates; experts propose
          changes here, vote on each other&apos;s, and the approved plan is executed once at the
          end.
        </p>
      </div>
    )
  }
  const live = proposals.filter((p) => p.status === 'open')
  const approved = proposals.filter((p) => p.status === 'approved' || p.status === 'executed')
  const rest = proposals.filter((p) => !live.includes(p) && !approved.includes(p))
  const group = (title: string, items: Proposal[]) =>
    items.length > 0 && (
      <div className="px-5 py-4">
        <div className="mb-2.5 text-[10px] font-semibold tracking-wider text-[var(--color-pass)] uppercase">
          {title}
        </div>
        <div className="space-y-2">
          {items
            .slice()
            .sort((a, b) => b.num - a.num)
            .map((p) => (
              <ProposalCard key={p.num} p={p} accentOf={accentOf} seats={seats} />
            ))}
        </div>
      </div>
    )
  return (
    <div className="min-h-0 flex-1 divide-y divide-[var(--color-line)] overflow-y-auto overscroll-contain">
      <div className="px-5 py-3 text-[11px] text-[var(--color-think)]">
        {phase === 'execute'
          ? 'Plan approved — the executor is applying it to the document.'
          : phase === 'confirm'
            ? 'Plan executed — the room is confirming the result.'
            : `${live.length} open · ${approved.length} approved · ${rest.length} settled otherwise. Document frozen until the plan settles.`}
      </div>
      {group('Open — awaiting votes', live)}
      {group('Approved — will execute', approved)}
      {group('Rejected, superseded, skipped', rest)}
    </div>
  )
}

export function DocDrawer({
  conversationId,
  content,
  fallback,
  docRev,
  experts,
  seatNames,
  planPhase,
  messageCount,
  initialTab = 'doc',
  editable,
  onClose,
  onSave,
}: {
  conversationId: string
  content: string
  fallback?: string
  docRev: number
  experts: Expert[]
  seatNames: string[]
  planPhase: string
  messageCount: number
  initialTab?: 'doc' | 'history' | 'plan'
  editable: boolean
  onClose: () => void
  onSave: (c: string) => Promise<void>
}) {
  const resolved = useMemo(() => {
    if (!isStubDoc(content)) return content
    if (fallback && fallback.trim()) return fallback
    return content
  }, [content, fallback])

  const [tab, setTab] = useState<'doc' | 'history' | 'plan'>(initialTab)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(resolved)
  const [busy, setBusy] = useState(false)
  const [sections, setSections] = useState<DocSection[]>([])
  const [ops, setOps] = useState<DocOpRow[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])

  useEffect(() => {
    setText(resolved)
  }, [resolved])

  useEffect(() => {
    let stale = false
    api
      .getProposals(conversationId)
      .then((ps) => {
        if (!stale) setProposals(ps)
      })
      .catch(() => {
        /* best-effort */
      })
    return () => {
      stale = true
    }
  }, [conversationId, docRev, messageCount])

  useEffect(() => {
    let stale = false
    api
      .getSharedDoc(conversationId)
      .then((d) => {
        if (!stale) {
          setSections(d.sections)
          setOps(d.ops)
        }
      })
      .catch(() => {
        /* history is best-effort; the doc itself is already on screen */
      })
    return () => {
      stale = true
    }
  }, [conversationId, docRev])

  const accents = useMemo(
    () => Object.fromEntries(experts.map((e) => [e.name, e.accent])),
    [experts],
  )
  const accentOf = (name: string) => accents[name]

  const empty = isStubDoc(text)
  const words = useMemo(() => (text.trim() ? text.trim().split(/\s+/).length : 0), [text])

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-2xl flex-col border-l border-[var(--color-line)] bg-[var(--color-panel)] shadow-2xl">
      <div className="flex items-center gap-1 border-b border-[var(--color-line)] px-4 py-2.5">
        <h2 className="mr-3 font-[family-name:var(--font-display)] font-semibold">Shared document</h2>
        <button
          type="button"
          onClick={() => setTab('doc')}
          className={clsx(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition',
            tab === 'doc'
              ? 'bg-white/[0.07] text-white'
              : 'text-[var(--color-think)] hover:bg-white/[0.04]',
          )}
        >
          <FileText size={13} /> Document
        </button>
        <button
          type="button"
          onClick={() => setTab('history')}
          className={clsx(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition',
            tab === 'history'
              ? 'bg-white/[0.07] text-white'
              : 'text-[var(--color-think)] hover:bg-white/[0.04]',
          )}
        >
          <History size={13} /> History
          {ops.length > 0 && (
            <span className="rounded-full bg-white/[0.08] px-1.5 text-[10px] text-[var(--color-pass)]">
              {ops.length}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => setTab('plan')}
          className={clsx(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition',
            tab === 'plan'
              ? 'bg-white/[0.07] text-white'
              : 'text-[var(--color-think)] hover:bg-white/[0.04]',
          )}
        >
          <ClipboardList size={13} /> Plan
          {proposals.filter((p) => p.status === 'open').length > 0 && (
            <span className="rounded-full bg-[rgba(107,163,255,0.18)] px-1.5 text-[10px] text-[var(--color-sky)]">
              {proposals.filter((p) => p.status === 'open').length}
            </span>
          )}
        </button>
        <div className="ml-auto flex items-center gap-3">
          {!empty && (
            <span className="text-[10px] text-[var(--color-pass)]">
              {sections.length > 0 ? `${sections.length} sections · ` : ''}
              {words.toLocaleString()} words · rev {docRev}
            </span>
          )}
          {tab === 'doc' && editable && !empty && !editing && (
            <button
              type="button"
              onClick={() => setEditing(true)}
              title="Edit the document directly (recorded as a chair edit)"
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--color-think)] hover:bg-white/5"
            >
              <PenLine size={12} /> Edit
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-[var(--color-think)] hover:bg-white/5"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {tab === 'plan' ? (
        <PlanView proposals={proposals} accentOf={accentOf} seats={seatNames} phase={planPhase} />
      ) : tab === 'history' ? (
        <HistoryView sections={sections} ops={ops} accentOf={accentOf} />
      ) : empty ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
          <FileText className="text-[var(--color-pass)]" size={28} />
          <p className="text-sm text-[var(--color-think)]">
            Nothing in the shared doc yet. When experts update the proposal, it will appear here.
          </p>
        </div>
      ) : editable && editing ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="min-h-0 flex-1 resize-none bg-transparent px-5 py-4 font-mono text-xs leading-relaxed text-[var(--color-speak)] outline-none"
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-5">
          <div className="solution-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        </div>
      )}

      {tab === 'doc' && editable && !empty && editing && (
        <div className="flex gap-2 border-t border-[var(--color-line)] p-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setText(resolved)
              setEditing(false)
            }}
            className="rounded-xl border border-[var(--color-line)] px-4 py-2 text-sm text-[var(--color-think)] hover:bg-white/5 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onSave(text)
                setEditing(false)
              } finally {
                setBusy(false)
              }
            }}
            className="flex-1 rounded-xl bg-[var(--color-sky)] py-2 text-sm font-semibold text-[#12141a] disabled:opacity-50"
          >
            Save as chair edit
          </button>
        </div>
      )}
      {tab === 'doc' && editable && empty && (
        <div className="border-t border-[var(--color-line)] p-3">
          <textarea
            value={text === '# Shared document\n\n' ? '' : text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Start the shared document…"
            className="mb-3 h-28 w-full resize-none rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 font-mono text-xs outline-none focus:border-[var(--color-sky)]"
          />
          <button
            type="button"
            disabled={busy || !text.trim()}
            onClick={async () => {
              setBusy(true)
              try {
                await onSave(text.trim() ? text : '# Shared document\n\n')
              } finally {
                setBusy(false)
              }
            }}
            className="w-full rounded-xl bg-[var(--color-sky)] py-2 text-sm font-semibold text-[#12141a] disabled:opacity-50"
          >
            Save
          </button>
        </div>
      )}
    </div>
  )
}
