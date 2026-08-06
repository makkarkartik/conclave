import { useEffect, useMemo, useState } from 'react'
import { FileText, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function isStubDoc(text: string) {
  const t = text.trim()
  return !t || t === '# Shared document' || t === '# Shared document\n'
}

export function DocDrawer({
  content,
  fallback,
  editable,
  onClose,
  onSave,
}: {
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
