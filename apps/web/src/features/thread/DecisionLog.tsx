import { useMemo } from 'react'
import { Check, CircleDashed, HelpCircle, Minus, PenLine, X } from 'lucide-react'
import clsx from 'clsx'
import { Avatar } from '../../shared/ui/Avatar'
import type { Expert, Message } from '../../shared/lib/api'

/**
 * The room's decision log: where every expert stands right now, how stances moved
 * lap by lap, and the permanent ledger of who did what (gists + document ops).
 * All of it is derived from data the room already records — this panel just makes
 * the deliberation legible at a glance.
 */

type Stance = 'backs' | 'objects' | 'passed' | 'drafted'

function stanceOf(m: Message): Stance {
  if (m.action === 'draft') return 'drafted'
  if (m.action === 'forfeit') return 'passed'
  return m.agree ? 'backs' : 'objects'
}

const STANCE_STYLE: Record<Stance, { dot: string; text: string; label: string }> = {
  backs: {
    dot: 'bg-[#50c878]',
    text: 'text-[#9ddeb5]',
    label: 'consents',
  },
  objects: {
    dot: 'bg-[var(--color-coral)]',
    text: 'text-[var(--color-coral)]',
    label: 'staked a change',
  },
  passed: {
    dot: 'bg-[var(--color-pass)]',
    text: 'text-[var(--color-pass)]',
    label: 'passed',
  },
  drafted: {
    dot: 'bg-[var(--color-sky)]',
    text: 'text-[var(--color-sky)]',
    label: 'drafted sealed',
  },
}

function StanceIcon({ stance, size = 12 }: { stance: Stance; size?: number }) {
  if (stance === 'backs') return <Check size={size} className="text-[#9ddeb5]" />
  if (stance === 'objects') return <X size={size} className="text-[var(--color-coral)]" />
  if (stance === 'drafted') return <PenLine size={size} className="text-[var(--color-sky)]" />
  return <Minus size={size} className="text-[var(--color-pass)]" />
}

/** Op chips ("Edited §bottom-line") are decisions about the artifact; keep them
 * visually distinct from utility chips ("Read notes.pdf", "Searched the web"). */
function isOpChip(c: string) {
  return /^(Added|Edited|Deleted) §|^Reverted op /.test(c)
}

export function DecisionLog({
  messages,
  roomExperts,
  expertMap,
  onClose,
}: {
  messages: Message[]
  roomExperts: Expert[]
  expertMap: Record<string, Expert>
  onClose: () => void
}) {
  const turns = useMemo(() => messages.filter((m) => m.action !== 'ask'), [messages])

  // Latest stance per seated expert (by id; name fallback for removed experts).
  const currentStance = useMemo(() => {
    const map = new Map<string, Message>()
    for (const m of turns) if (m.expert_id) map.set(m.expert_id, m)
    return map
  }, [turns])

  // laps ascending, each lap holding its turns in spoken order
  const laps = useMemo(() => {
    const byLap = new Map<number, Message[]>()
    for (const m of messages) {
      const list = byLap.get(m.lap) ?? []
      list.push(m)
      byLap.set(m.lap, list)
    }
    return [...byLap.entries()].sort(([a], [b]) => a - b)
  }, [messages])

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[var(--color-line)] bg-[var(--color-panel)] shadow-2xl">
      <div className="flex items-center justify-between border-b border-[var(--color-line)] px-4 py-3">
        <h2 className="font-[family-name:var(--font-display)] font-semibold">Decision log</h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 text-[var(--color-think)] hover:bg-white/5"
        >
          <X size={18} />
        </button>
      </div>

      {turns.length === 0 ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
          <CircleDashed className="text-[var(--color-pass)]" size={28} />
          <p className="text-sm text-[var(--color-think)]">
            No turns yet. Once experts speak, their stances and document decisions appear here.
          </p>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {/* Where the room stands now */}
          <div className="border-b border-[var(--color-line)] px-4 py-3">
            <div className="mb-2 text-[10px] font-semibold tracking-wide text-[var(--color-pass)] uppercase">
              Where the room stands
            </div>
            <div className="space-y-1.5">
              {roomExperts.map((e) => {
                const last = currentStance.get(e.id)
                const stance = last ? stanceOf(last) : null
                return (
                  <div key={e.id} className="flex items-center gap-2">
                    <Avatar name={e.name} accent={e.accent} size={22} />
                    <span className="min-w-0 flex-1 truncate text-xs">{e.name}</span>
                    {stance ? (
                      <span
                        className={clsx(
                          'flex items-center gap-1 text-[11px]',
                          STANCE_STYLE[stance].text,
                        )}
                        title={last?.gist || undefined}
                      >
                        <StanceIcon stance={stance} />
                        {STANCE_STYLE[stance].label}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] text-[var(--color-pass)]">
                        <HelpCircle size={12} /> hasn&apos;t spoken
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Stance grid: one row per lap, one dot per expert — the path to convergence */}
          {laps.length > 1 && (
            <div className="border-b border-[var(--color-line)] px-4 py-3">
              <div className="mb-2 text-[10px] font-semibold tracking-wide text-[var(--color-pass)] uppercase">
                Stances by lap
              </div>
              <table className="text-[11px]">
                <thead>
                  <tr>
                    <th className="pr-3 text-left font-normal text-[var(--color-pass)]">lap</th>
                    {roomExperts.map((e) => (
                      <th key={e.id} className="px-1.5 font-normal" title={e.name}>
                        <span className="text-[var(--color-think)]">
                          {e.name.slice(0, 2)}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {laps.map(([lap, lapMsgs]) => (
                    <tr key={lap}>
                      <td className="pr-3 text-[var(--color-pass)]">{lap}</td>
                      {roomExperts.map((e) => {
                        const m = lapMsgs.find((x) => x.expert_id === e.id)
                        return (
                          <td key={e.id} className="px-1.5 py-1 text-center">
                            {m ? (
                              <span
                                title={`${e.name}: ${m.gist || m.action}`}
                                className={clsx(
                                  'inline-block h-2.5 w-2.5 rounded-full',
                                  STANCE_STYLE[stanceOf(m)].dot,
                                )}
                              />
                            ) : (
                              <span className="inline-block h-2.5 w-2.5 rounded-full border border-[var(--color-line)]" />
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* The ledger: lap by lap, who did what */}
          <div className="px-4 py-3">
            <div className="mb-2 text-[10px] font-semibold tracking-wide text-[var(--color-pass)] uppercase">
              Ledger
            </div>
            <div className="space-y-3">
              {laps.map(([lap, lapMsgs]) => (
                <div key={lap}>
                  <div className="mb-1.5 text-[10px] text-[var(--color-pass)]">Lap {lap}</div>
                  <div className="space-y-2 border-l border-[var(--color-line)] pl-3">
                    {lapMsgs.map((m) =>
                      m.action === 'ask' ? (
                        <div key={m.id} className="text-[11px] leading-relaxed">
                          <span className="font-medium text-[var(--color-sky)]">You asked:</span>{' '}
                          <span className="text-[var(--color-think)]">{m.content}</span>
                        </div>
                      ) : (
                        <div key={m.id} className="text-[11px] leading-relaxed">
                          <div className="flex items-center gap-1.5">
                            <StanceIcon stance={stanceOf(m)} size={11} />
                            <span
                              className="font-medium"
                              style={{
                                color: m.expert_id
                                  ? expertMap[m.expert_id]?.accent
                                  : undefined,
                              }}
                            >
                              {m.expert_name}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[var(--color-think)]">
                              {m.gist || (m.action === 'forfeit' ? 'passed' : 'spoke')}
                            </span>
                          </div>
                          {m.objection && (
                            <div className="mt-0.5 text-[10px] leading-relaxed text-[var(--color-coral)]">
                              ⚑ {m.objection.text}
                            </div>
                          )}
                          {m.chips.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {m.chips.map((c) => (
                                <span
                                  key={c}
                                  className={clsx(
                                    'rounded-full px-1.5 py-px text-[9px]',
                                    isOpChip(c)
                                      ? 'bg-[rgba(107,163,255,0.15)] text-[var(--color-sky)]'
                                      : 'bg-white/[0.06] text-[var(--color-pass)]',
                                  )}
                                >
                                  {c}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ),
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
