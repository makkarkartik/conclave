import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Conversation, Expert, Message } from '../../shared/lib/api'

/** What each turn did, in the reader's language rather than the schema's. */
const ACTION_LABEL: Record<string, string> = {
  write_proposal: 'Revised the proposal',
  edit_shared_doc: 'Edited the document',
  speak: 'Argued',
  forfeit: 'Passed',
}

/**
 * The solution's own opening H1 is the document's real title; the room topic is
 * usually a brief. Lift the heading out so the page has one title, not two.
 */
export function splitTitle(markdown: string): { title: string | null; body: string } {
  const match = markdown.match(/^\s*#\s+(.+?)\s*(?:\n|$)/)
  if (!match) return { title: null, body: markdown }
  return { title: match[1], body: markdown.slice(match[0].length).trimStart() }
}

/** Gists are written in third person ("Ada challenged…"); the name is already
 *  displayed beside them, so drop the duplicate. */
function trimName(gist: string, name: string): string {
  if (!gist.toLowerCase().startsWith(name.toLowerCase() + ' ')) return gist
  const rest = gist.slice(name.length + 1)
  return rest.charAt(0).toUpperCase() + rest.slice(1)
}

/**
 * The printable document: a masthead, the converged solution, and the
 * deliberation that produced it.
 *
 * Rendered through a portal to <body>, outside #root: printing hides the app
 * with `display: none`, and an element nested inside it would be hidden too.
 * (Hiding the app with `visibility: hidden` instead leaves its full height in
 * the layout, which is what produced pages of trailing blanks.)
 */
export function SolutionPrint({
  active,
  roomExperts,
  messages,
}: {
  active: Conversation
  roomExperts: Expert[]
  messages: Message[]
}) {
  const text = (active.converged_solution || '').trim()
  const { title, body } = splitTitle(text)
  if (!text) return null

  const converged = new Date(active.updated_at).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
  const accentOf = (m: Message) =>
    roomExperts.find((e) => e.id === m.expert_id)?.accent ?? '#6ba3ff'

  // Group the turns by lap so the trail reads as rounds of argument.
  const laps = messages.reduce<Map<number, Message[]>>((acc, m) => {
    const bucket = acc.get(m.lap) ?? []
    bucket.push(m)
    return acc.set(m.lap, bucket)
  }, new Map())
  const revisions = messages.filter((m) => m.doc_diff?.trim()).length

  return createPortal(
    <div className="print-only" id="solution-print">
      <header className="print-head">
        <div className="print-brand">Conclave</div>
        <h1 className="print-topic">{title ?? active.title}</h1>
        <div className="print-meta">
          <span>Converged {converged}</span>
          <span>
            {active.lap} lap{active.lap === 1 ? '' : 's'} · {messages.length} turns ·{' '}
            {revisions} revision{revisions === 1 ? '' : 's'}
          </span>
        </div>
        <div className="print-panel">
          {roomExperts.map((e) => (
            <span key={e.id} className="print-expert">
              <span className="print-dot" style={{ background: e.accent }} />
              <b>{e.name}</b>
              <span className="print-model">{e.model}</span>
            </span>
          ))}
        </div>
        <p className="print-brief">
          <span className="print-brief-label">Brief</span>
          {active.topic}
        </p>
      </header>

      <div className="solution-md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
      </div>

      {laps.size > 0 && (
        <section className="print-trail">
          <h2 className="print-trail-title">How the room got here</h2>
          <p className="print-trail-intro">
            Each expert takes the floor in turn and must earn agreement: the default stance is
            to disagree, and the room only converges once a full lap endorses one proposal.
            Below is what each contributed, in order.
          </p>
          {[...laps.entries()].map(([lap, turns]) => (
            <div key={lap} className="print-lap">
              <div className="print-lap-label">Lap {lap + 1}</div>
              <ul className="print-turns">
                {turns.map((m) => (
                  <li key={m.id}>
                    <span className="print-dot" style={{ background: accentOf(m) }} />{' '}
                    <span className="print-turn-who">{m.expert_name}</span>{' '}
                    <span className="print-turn-act">
                      {ACTION_LABEL[m.action] ?? m.action}
                    </span>
                    {' — '}
                    <span className="print-turn-gist">
                      {m.gist ? trimName(m.gist, m.expert_name) : m.content.slice(0, 160)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}
    </div>,
    document.body,
  )
}
