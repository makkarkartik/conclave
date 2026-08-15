import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Conversation, Expert } from '../../shared/lib/api'

/**
 * The printable document. Hidden on screen; the only visible element when the
 * browser prints. It reuses `.solution-md` so the PDF matches the card exactly
 * rather than approximating it.
 */
export function SolutionPrint({
  active,
  roomExperts,
}: {
  active: Conversation
  roomExperts: Expert[]
}) {
  const text = (active.converged_solution || '').trim()
  if (!text) return null

  const converged = new Date(active.updated_at).toLocaleString(undefined, {
    dateStyle: 'long',
    timeStyle: 'short',
  })

  return (
    <div className="print-only" id="solution-print">
      <header className="print-head">
        <div className="print-brand">
          <span className="print-mark">C</span>
          <span>Conclave</span>
        </div>
        <h1 className="print-topic">{active.topic}</h1>
        <div className="print-meta">
          <span>Converged {converged}</span>
          <span>·</span>
          <span>
            {active.lap} lap{active.lap === 1 ? '' : 's'}
          </span>
          {roomExperts.length > 0 && (
            <>
              <span>·</span>
              <span>{roomExperts.map((e) => `${e.name} (${e.model})`).join(', ')}</span>
            </>
          )}
        </div>
      </header>

      <div className="solution-md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </div>
  )
}
