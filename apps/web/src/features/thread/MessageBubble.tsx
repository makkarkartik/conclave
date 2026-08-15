import { useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, FileDiff, Globe } from 'lucide-react'
import clsx from 'clsx'
import { Avatar } from '../../shared/ui/Avatar'
import type { Expert, Message } from '../../shared/lib/api'

function DiffBlock({ diff }: { diff: string }) {
  const [open, setOpen] = useState(true)
  const lines = diff.split('\n')
  const title = lines[0] || 'Document changes'
  const body = lines.slice(1)

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-[var(--color-sky)]/25 bg-black/25">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.03]"
      >
        <FileDiff size={14} className="text-[var(--color-sky)]" />
        <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-[var(--color-sky)]">
          {title}
        </span>
        <ChevronDown
          size={14}
          className={clsx('text-[var(--color-think)] transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && body.length > 0 && (
        <pre className="max-h-56 overflow-auto border-t border-[var(--color-line)] px-3 py-2 font-mono text-[11px] leading-relaxed">
          {body.map((line, i) => {
            const kind =
              line.startsWith('+') && !line.startsWith('+++')
                ? 'add'
                : line.startsWith('-') && !line.startsWith('---')
                  ? 'del'
                  : line.startsWith('@@')
                    ? 'hunk'
                    : 'ctx'
            return (
              <div
                key={`${i}-${line.slice(0, 24)}`}
                className={clsx(
                  kind === 'add' && 'bg-[rgba(80,200,120,0.12)] text-[#9ddeb5]',
                  kind === 'del' && 'bg-[rgba(255,120,100,0.12)] text-[#ffb3a3]',
                  kind === 'hunk' && 'text-[var(--color-sky)]',
                  kind === 'ctx' && 'text-[var(--color-think)]',
                )}
              >
                {line || ' '}
              </div>
            )
          })}
        </pre>
      )}
    </div>
  )
}

export function MessageBubble({
  message,
  expert,
  highlighted,
}: {
  message: Message
  expert?: Expert
  highlighted: boolean
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-3"
    >
      <Avatar name={message.expert_name} accent={expert?.accent} />
      <div
        className={clsx(
          'min-w-0 flex-1 rounded-2xl border border-[var(--color-line)] bg-[rgba(28,31,42,0.72)] p-4 backdrop-blur',
          highlighted ? 'ring-1 ring-[var(--color-sky)]/40' : '',
        )}
      >
        <div className="mb-2 flex items-center gap-2">
          <span className="font-[family-name:var(--font-display)] text-sm font-semibold">
            {message.expert_name}
          </span>
          <span className="text-[11px] text-[var(--color-pass)]">
            {message.provider}
            {message.model ? ` · ${message.model}` : ''}
          </span>
        </div>
        {message.thought && (
          <div className="mb-3 w-full rounded-xl border border-white/[0.06] bg-black/20 px-3 py-2">
            <div className="text-[10px] leading-relaxed text-[var(--color-think)]">{message.thought}</div>
          </div>
        )}
        <div
          className={clsx(
            'text-[15px] leading-relaxed',
            message.action === 'forfeit'
              ? 'italic text-[var(--color-pass)]'
              : 'text-[var(--color-speak)]',
          )}
        >
          {message.content}
        </div>
        {message.doc_diff?.trim() ? <DiffBlock diff={message.doc_diff} /> : null}
        {message.citations?.length > 0 && (
          <div className="mt-3 border-t border-[var(--color-line)] pt-2">
            <div className="mb-1 flex items-center gap-1.5 text-[10px] text-[var(--color-pass)]">
              <Globe size={11} /> Sources
            </div>
            <ol className="space-y-0.5">
              {message.citations.map((c, i) => (
                <li key={c.url} className="flex gap-1.5 text-[11px] leading-relaxed">
                  <span className="text-[var(--color-pass)]">{i + 1}.</span>
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="min-w-0 truncate text-[var(--color-sky)] hover:underline"
                    title={c.url}
                  >
                    {c.title}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        )}
        {message.chips?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.chips.map((c) => (
              <span
                key={c}
                className="rounded-full bg-[rgba(255,139,107,0.15)] px-2 py-0.5 text-[10px] text-[var(--color-coral)]"
              >
                {c}
              </span>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}
