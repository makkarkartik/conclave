import type { ReactNode } from 'react'
import { AnimatePresence } from 'framer-motion'
import { Avatar } from '../../shared/ui/Avatar'
import { MessageBubble } from './MessageBubble'
import { SealedDrafting } from './SealedDrafting'
import type { Expert, Message } from '../../shared/lib/api'

/** A lap boundary, marked as a node on the timeline rail. */
function LapDivider({ lap }: { lap: number }) {
  return (
    <div className="relative flex h-5 items-center">
      <span className="absolute left-[18px] z-[1] -translate-x-1/2 rounded-full border border-[var(--color-line)] bg-[var(--color-panel)] px-2 py-0.5 text-[9px] font-semibold tracking-wider text-[var(--color-pass)] uppercase">
        Lap {lap}
      </span>
    </div>
  )
}

export function Thread({
  messages,
  expertMap,
  speakingId,
  thinkingId,
  running,
  drafting = false,
  roomExperts = [],
}: {
  messages: Message[]
  expertMap: Record<string, Expert>
  speakingId: string | null
  thinkingId: string | null
  running: boolean
  drafting?: boolean
  roomExperts?: Expert[]
}) {
  // The transcript as a chain of events: rows on a single vertical rail, with a
  // lap marker wherever a new lap begins.
  const rows: ReactNode[] = []
  let prevLap: number | null = null
  for (const m of messages) {
    if (m.lap !== prevLap) {
      prevLap = m.lap
      rows.push(<LapDivider key={`lap-${m.lap}-${m.id}`} lap={m.lap} />)
    }
    rows.push(
      <MessageBubble
        key={m.id}
        message={m}
        expert={m.expert_id ? expertMap[m.expert_id] : undefined}
        highlighted={speakingId === m.expert_id && running}
      />,
    )
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      <div className="relative space-y-4">
        {(messages.length > 0 || thinkingId) && (
          <div
            aria-hidden
            className="pointer-events-none absolute top-2 bottom-4 left-[17px] w-px bg-[var(--color-line)]"
          />
        )}
        <AnimatePresence initial={false}>{rows}</AnimatePresence>
        {drafting && roomExperts.length > 0 && <SealedDrafting experts={roomExperts} />}
        {thinkingId && expertMap[thinkingId] && (
          <div className="flex gap-3 opacity-80">
            <div className="relative z-[1] shrink-0">
              <Avatar name={expertMap[thinkingId].name} accent={expertMap[thinkingId].accent} />
            </div>
            <div className="flex-1 rounded-2xl border border-[var(--color-line)] bg-[rgba(28,31,42,0.5)] p-4">
              <div className="text-sm font-semibold">{expertMap[thinkingId].name}</div>
              <div className="mt-2 animate-pulse text-[10px] text-[var(--color-think)]">
                Thinking…
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
