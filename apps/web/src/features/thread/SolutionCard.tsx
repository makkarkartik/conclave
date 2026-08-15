import { useState } from 'react'
import { ChevronDown, Download, Printer, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import { SolutionPrint, splitTitle } from './SolutionPrint'
import { downloadSolutionHtml } from './exportHtml'
import type { Conversation, Expert, Message } from '../../shared/lib/api'

/** Filenames the OS will accept, derived from the room topic. */
function pdfName(topic: string): string {
  const slug = topic.trim().slice(0, 60).replace(/[^\w\s-]/g, '').replace(/\s+/g, '-')
  return `Conclave-${slug || 'converged-solution'}`
}

export function SolutionCard({
  active,
  roomExperts,
  messages,
}: {
  active: Conversation
  roomExperts: Expert[]
  messages: Message[]
}) {
  const [expanded, setExpanded] = useState(false)
  const text = (active.converged_solution || '').trim()

  // The browser's own print-to-PDF renders the app's stylesheet, so the export
  // matches this card exactly. Document title becomes the suggested filename.
  function exportPdf() {
    const previous = document.title
    document.title = pdfName(active.topic)
    const restore = () => {
      document.title = previous
      window.removeEventListener('afterprint', restore)
    }
    window.addEventListener('afterprint', restore)
    window.print()
  }

  // Only show after true room convergence — not pause / draft / in-progress proposal.
  if (active.status !== 'converged' || !text) return null

  return (
    <div className="border-t border-[var(--color-line)] px-6 py-4 md:px-8">
      <SolutionPrint active={active} roomExperts={roomExperts} messages={messages} />
      <motion.div
        layout
        className="overflow-hidden rounded-2xl border border-[var(--color-sky)]/35 bg-[linear-gradient(160deg,rgba(107,163,255,0.14),rgba(28,31,42,0.92)_45%)]"
      >
        <div className="flex w-full items-center gap-3 px-4 py-3.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex min-w-0 flex-1 items-center gap-3 text-left transition hover:opacity-90"
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
          </button>
          <button
            type="button"
            onClick={() =>
              downloadSolutionHtml(
                pdfName(active.topic),
                splitTitle(text).title ?? active.title,
              )
            }
            title="Download as a self-contained HTML document"
            className="flex shrink-0 items-center gap-1.5 rounded-xl border border-[var(--color-sky)]/35 bg-[rgba(107,163,255,0.12)] px-3 py-1.5 text-xs text-[var(--color-sky)] transition hover:bg-[rgba(107,163,255,0.2)]"
          >
            <Download size={13} /> HTML
          </button>
          <button
            type="button"
            onClick={exportPdf}
            title="Print this solution to PDF"
            className="flex shrink-0 items-center gap-1.5 rounded-xl border border-[var(--color-line)] px-3 py-1.5 text-xs text-[var(--color-think)] transition hover:bg-white/5"
          >
            <Printer size={13} /> PDF
          </button>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? 'Collapse solution' : 'Expand solution'}
            className="shrink-0 text-[var(--color-think)] transition hover:text-white"
          >
            <ChevronDown
              size={18}
              className={clsx('transition-transform duration-300', expanded && 'rotate-180')}
            />
          </button>
        </div>

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
