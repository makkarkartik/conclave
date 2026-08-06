import { useState } from 'react'
import { ChevronDown, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import type { Conversation } from '../../shared/lib/api'

export function SolutionCard({ active }: { active: Conversation }) {
  const [expanded, setExpanded] = useState(false)
  const text = (active.converged_solution || '').trim()

  // Only show after true room convergence — not pause / draft / in-progress proposal.
  if (active.status !== 'converged' || !text) return null

  return (
    <div className="border-t border-[var(--color-line)] px-6 py-4 md:px-8">
      <motion.div
        layout
        className="overflow-hidden rounded-2xl border border-[var(--color-sky)]/35 bg-[linear-gradient(160deg,rgba(107,163,255,0.14),rgba(28,31,42,0.92)_45%)]"
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition hover:bg-white/[0.03]"
          aria-expanded={expanded}
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[rgba(107,163,255,0.18)] text-[var(--color-sky)]">
            <Sparkles size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-[family-name:var(--font-display)] text-sm font-semibold tracking-tight text-[var(--color-sky)]">
              Converged solution
            </div>
            <div className="truncate text-xs text-[var(--color-think)]">
              {expanded ? 'Click to collapse' : 'Click to expand · markdown'}
            </div>
          </div>
          <ChevronDown
            size={18}
            className={clsx(
              'shrink-0 text-[var(--color-think)] transition-transform duration-300',
              expanded && 'rotate-180',
            )}
          />
        </button>

        <AnimatePresence initial={false}>
          {expanded ? (
            <motion.div
              key="open"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="max-h-[min(42vh,28rem)] overflow-y-auto overscroll-contain border-t border-[var(--color-line)] px-4 py-4">
                <div className="solution-md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="peek"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="border-t border-[var(--color-line)] px-4 pb-4"
            >
              <div className="solution-md solution-md--peek pointer-events-none max-h-24 overflow-hidden">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
              </div>
              <div className="pointer-events-none -mt-10 h-10 bg-gradient-to-t from-[rgba(28,31,42,0.98)] to-transparent" />
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
