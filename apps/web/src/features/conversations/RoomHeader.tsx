import { FileText, Paperclip, Pause, Play } from 'lucide-react'
import clsx from 'clsx'
import { Avatar } from '../../shared/ui/Avatar'
import type { Conversation, Expert } from '../../shared/lib/api'

export function RoomHeader({
  active,
  roomExperts,
  speakingId,
  expertMap,
  onAttach,
  onOpenDoc,
  onPause,
  onStartOrResume,
}: {
  active: Conversation
  roomExperts: Expert[]
  speakingId: string | null
  expertMap: Record<string, Expert>
  onAttach: (file: File) => void
  onOpenDoc: () => void
  onPause: () => void
  onStartOrResume: () => void
}) {
  return (
    <header className="border-b border-[var(--color-line)] px-8 py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-[family-name:var(--font-display)] text-xl font-semibold tracking-tight">
            {active.topic}
          </h1>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex -space-x-2">
              {roomExperts.map((e) => (
                <div
                  key={e.id}
                  className={clsx(
                    'rounded-full ring-2',
                    speakingId === e.id ? 'ring-[var(--color-sky)]' : 'ring-[var(--color-ink)]',
                  )}
                  title={e.name}
                >
                  <Avatar name={e.name} accent={e.accent} size={32} />
                </div>
              ))}
            </div>
            <span className="text-xs text-[var(--color-think)]">
              {speakingId && expertMap[speakingId]
                ? `${expertMap[speakingId].name} speaking`
                : active.status}
              {active.lap > 0 ? ` · lap ${active.lap}` : ''}
            </span>
            {active.attachments.length > 0 && (
              <span className="flex items-center gap-1 text-xs text-[var(--color-think)]">
                <Paperclip size={12} />
                {active.attachments.length}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenDoc}
            className="flex items-center gap-1.5 rounded-xl border border-[var(--color-line)] px-3 py-2 text-xs text-[var(--color-think)] hover:bg-white/5"
          >
            <FileText size={14} /> Shared doc
          </button>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-[var(--color-line)] px-3 py-2 text-xs text-[var(--color-think)] hover:bg-white/5">
            <Paperclip size={14} /> Attach
            <input
              type="file"
              className="hidden"
              onChange={(ev) => {
                const f = ev.target.files?.[0]
                if (f) onAttach(f)
              }}
            />
          </label>
          {active.status === 'running' ? (
            <button
              type="button"
              onClick={onPause}
              className="flex items-center gap-1.5 rounded-xl border border-[var(--color-line)] px-4 py-2 text-sm font-medium hover:bg-white/5"
            >
              <Pause size={14} /> Pause to direct
            </button>
          ) : active.status === 'converged' ? (
            <span className="rounded-xl bg-[rgba(107,163,255,0.15)] px-4 py-2 text-sm text-[var(--color-sky)]">
              Converged
            </span>
          ) : (
            <button
              type="button"
              onClick={onStartOrResume}
              className="flex items-center gap-1.5 rounded-xl bg-[var(--color-sky)] px-4 py-2 text-sm font-semibold text-[#12141a]"
            >
              <Play size={14} />
              {active.status === 'draft' ? 'Start' : 'Resume'}
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
