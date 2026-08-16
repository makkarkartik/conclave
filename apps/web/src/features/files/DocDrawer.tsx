import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, FileText, History, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import { api } from '../../shared/lib/api'

function isStubDoc(text: string) {
  const t = text.trim()
  return !t || t === '# Shared document' || t === '# Shared document\n'
}

/** Who last shaped each section, and the recent operation log — the document's
 * history is part of the document (protocol v2). */
function HistoryPanel({ conversationId }: { conversationId: string }) {
  const [blame, setBlame] = useState('')
  const [opsLog, setOpsLog] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let stale = false
    api
      .getSharedDoc(conversationId)
      .then((d) => {
        if (!stale) {
          setBlame(d.blame)
          setOpsLog(d.ops_log)
        }
      })
      .catch(() => {
        /* history is best-effort; the doc itself is already on screen */
      })
    return () => {
      stale = true
    }
  }, [conversationId])

  if (!blame && !opsLog) return null
  return (
    <div className="border-t border-[var(--color-line)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-white/[0.03]"
      >
        <History size={13} className="text-[var(--color-sky)]" />
        <span className="flex-1 text-[11px] font-medium text-[var(--color-sky)]">History</span>
        <ChevronDown
          size={14}
          className={clsx('text-[var(--color-think)] transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <div className="max-h-48 overflow-y-auto px-4 pb-3">
          {blame && (
            <>
              <div className="mb-1 text-[10px] font-semibold tracking-wide text-[var(--color-pass)] uppercase">
                Sections
              </div>
              <pre className="mb-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap text-[var(--color-think)]">
                {blame}
              </pre>
            </>
          )}
          {opsLog && (
            <>
              <div className="mb-1 text-[10px] font-semibold tracking-wide text-[var(--color-pass)] uppercase">
                Operations
              </div>
              <pre className="font-mono text-[10px] leading-relaxed whitespace-pre-wrap text-[var(--color-think)]">
                {opsLog}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function DocDrawer({
  conversationId,
  content,
  fallback,
  editable,
  onClose,
  onSave,
}: {
  conversationId: string
  content: string
  fallback?: string
  editable: boolean
  onClose: () => void
  onSave: (c: string) => Promise<void>
}) {
  const resolved = useMemo(() => {
    if (!isStubDoc(content)) return content
    if (fallback && fallback.trim()) return fallback
    return content
  }, [content, fallback])

  const showingFallback = isStubDoc(content) && Boolean(fallback?.trim())
  const [text, setText] = useState(resolved)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setText(resolved)
  }, [resolved])

  const empty = isStubDoc(text)

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[var(--color-line)] bg-[var(--color-panel)] shadow-2xl">
      <div className="flex items-center justify-between border-b border-[var(--color-line)] px-4 py-3">
        <div className="min-w-0">
          <h2 className="font-[family-name:var(--font-display)] font-semibold">Shared document</h2>
          {showingFallback && (
            <p className="truncate text-[11px] text-[var(--color-think)]">
              Showing live proposal (notes file was empty)
            </p>
          )}
        </div>
        <button type="button" onClick={onClose} className="rounded-lg p-1 text-[var(--color-think)] hover:bg-white/5">
          <X size={18} />
        </button>
      </div>

      {empty ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
          <FileText className="text-[var(--color-pass)]" size={28} />
          <p className="text-sm text-[var(--color-think)]">
            Nothing in the shared doc yet. When experts update the proposal, it will appear here.
          </p>
        </div>
      ) : editable ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="min-h-0 flex-1 resize-none bg-transparent px-4 py-3 font-mono text-xs leading-relaxed text-[var(--color-speak)] outline-none"
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4">
          <div className="solution-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        </div>
      )}

      <HistoryPanel conversationId={conversationId} />

      {editable && !empty && (
        <div className="border-t border-[var(--color-line)] p-3">
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onSave(text)
              } finally {
                setBusy(false)
              }
            }}
            className="w-full rounded-xl bg-[var(--color-sky)] py-2 text-sm font-semibold text-[#12141a] disabled:opacity-50"
          >
            Save
          </button>
        </div>
      )}
      {editable && empty && (
        <div className="border-t border-[var(--color-line)] p-3">
          <textarea
            value={text === '# Shared document\n\n' ? '' : text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Start the shared document…"
            className="mb-3 h-28 w-full resize-none rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 font-mono text-xs outline-none focus:border-[var(--color-sky)]"
          />
          <button
            type="button"
            disabled={busy || !text.trim()}
            onClick={async () => {
              setBusy(true)
              try {
                await onSave(text.trim() ? text : '# Shared document\n\n')
              } finally {
                setBusy(false)
              }
            }}
            className="w-full rounded-xl bg-[var(--color-sky)] py-2 text-sm font-semibold text-[#12141a] disabled:opacity-50"
          >
            Save
          </button>
        </div>
      )}
    </div>
  )
}
