import { AnimatePresence } from 'framer-motion'
import { Avatar } from '../../shared/ui/Avatar'
import { MessageBubble } from './MessageBubble'
import type { Expert, Message } from '../../shared/lib/api'

export function Thread({
  messages,
  expertMap,
  speakingId,
  thinkingId,
  running,
}: {
  messages: Message[]
  expertMap: Record<string, Expert>
  speakingId: string | null
  thinkingId: string | null
  running: boolean
}) {
  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-8 py-6">
      <AnimatePresence initial={false}>
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            expert={m.expert_id ? expertMap[m.expert_id] : undefined}
            highlighted={speakingId === m.expert_id && running}
          />
        ))}
      </AnimatePresence>
      {thinkingId && expertMap[thinkingId] && (
        <div className="flex gap-3 opacity-80">
          <Avatar name={expertMap[thinkingId].name} accent={expertMap[thinkingId].accent} />
          <div className="flex-1 rounded-2xl border border-[var(--color-line)] bg-[rgba(28,31,42,0.5)] p-4">
            <div className="text-sm font-semibold">{expertMap[thinkingId].name}</div>
            <div className="mt-2 animate-pulse text-[10px] text-[var(--color-think)]">Thinking…</div>
          </div>
        </div>
      )}
    </div>
  )
}
