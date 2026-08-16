import { useState } from 'react'
import { CornerDownLeft, Loader2, RotateCcw } from 'lucide-react'
import clsx from 'clsx'
import type { Conversation } from '../../shared/lib/api'

/**
 * Carries a concluded room forward. Asking answers for one lap and leaves the
 * solution alone; reopening puts it back into deliberation, where convergence
 * has to be earned again.
 */
export function FollowUp({
  active,
  onAsk,
}: {
  active: Conversation
  onAsk: (question: string, reopen?: boolean) => Promise<void>
}) {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)

  const answering = active.status === 'consulting'
  const restable = ['converged', 'paused', 'safety_pause', 'error_pause'].includes(active.status)
  if (!restable && !answering) return null

  async function send(reopen: boolean) {
    const text = question.trim()
    if (!text || busy) return
    setBusy(true)
    try {
      await onAsk(text, reopen)
      setQuestion('')
    } catch {
      /* surfaced in the error banner */
    } finally {
      setBusy(false)
    }
  }

  if (answering) {
    return (
      <div className="flex items-center gap-2 border-t border-[var(--color-line)] px-6 py-3 text-xs text-[var(--color-sky)] md:px-8">
        <Loader2 size={13} className="animate-spin" />
        The room is answering your question…
      </div>
    )
  }

  return (
    <div className="border-t border-[var(--color-line)] px-6 py-3 md:px-8">
      <div className="flex items-end gap-2">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send(false)
            }
          }}
          rows={1}
          placeholder="Ask the room a follow-up…"
          className="max-h-32 min-h-[2.5rem] flex-1 resize-y rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 text-sm text-white outline-none focus:border-[var(--color-sky)]"
        />
        <button
          type="button"
          disabled={!question.trim() || busy}
          onClick={() => void send(true)}
          title="Reopen deliberation — the experts must reach agreement again"
          className="flex shrink-0 items-center gap-1.5 rounded-xl border border-[var(--color-line)] px-3 py-2 text-xs text-[var(--color-think)] transition hover:bg-white/5 disabled:opacity-40"
        >
          <RotateCcw size={13} /> Reopen
        </button>
        <button
          type="button"
          disabled={!question.trim() || busy}
          onClick={() => void send(false)}
          className={clsx(
            'flex shrink-0 items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold text-[#12141a] transition',
            busy ? 'bg-[var(--color-sky)]/60' : 'bg-[var(--color-sky)] hover:brightness-110',
            'disabled:opacity-40',
          )}
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <CornerDownLeft size={13} />}
          Ask
        </button>
      </div>
      <p className="mt-1.5 text-[11px] text-[var(--color-pass)]">
        <strong className="font-medium text-[var(--color-think)]">Ask</strong> — one round of
        answers, the solution stays as agreed.{' '}
        <strong className="font-medium text-[var(--color-think)]">Reopen</strong> — the experts
        deliberate again and must re-earn agreement.
      </p>
    </div>
  )
}
