import { Sparkles } from 'lucide-react'

export function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
      <Sparkles className="text-[var(--color-sky)]" size={28} />
      <h1 className="font-[family-name:var(--font-display)] text-2xl font-semibold">
        Seat experts. Set a topic. Start.
      </h1>
      <p className="max-w-md text-sm text-[var(--color-think)]">
        Conclave keeps deliberating until they converge — or you pause to direct.
      </p>
      <button
        type="button"
        onClick={onNew}
        className="mt-2 rounded-xl bg-[var(--color-sky)] px-5 py-2.5 text-sm font-semibold text-[#12141a]"
      >
        New conversation
      </button>
    </div>
  )
}
