import { useEffect, useState } from 'react'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import clsx from 'clsx'
import type { Conversation } from '../../shared/lib/api'

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: {
  conversations: Conversation[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    if (editingId && !conversations.some((c) => c.id === editingId)) {
      setEditingId(null)
    }
  }, [conversations, editingId])

  async function commitRename(id: string) {
    const title = draft.trim()
    if (!title) return
    setBusyId(id)
    try {
      await onRename(id, title)
      setEditingId(null)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col border-t border-[var(--color-line)] px-4 pt-3">
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-[11px] font-semibold tracking-wide text-[var(--color-think)] uppercase">
          Conversations
        </span>
        <button
          type="button"
          onClick={onNew}
          className="rounded-md p-1 text-[var(--color-think)] hover:bg-white/5 hover:text-white"
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pb-4">
        {conversations.map((c) => {
          const editing = editingId === c.id
          return (
            <div
              key={c.id}
              className={clsx(
                'group flex w-full items-start gap-1 rounded-xl px-2 py-2 transition',
                activeId === c.id ? 'bg-[rgba(107,163,255,0.18)]' : 'hover:bg-white/[0.03]',
              )}
            >
              {editing ? (
                <div className="min-w-0 flex-1">
                  <input
                    autoFocus
                    value={draft}
                    disabled={busyId === c.id}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void commitRename(c.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    className="w-full rounded-lg border border-[var(--color-line)] bg-black/30 px-2 py-1 text-sm text-white outline-none focus:border-[var(--color-sky)]"
                  />
                  <div className="mt-1 flex gap-1">
                    <button
                      type="button"
                      disabled={busyId === c.id}
                      onClick={() => void commitRename(c.id)}
                      className="rounded p-1 text-[var(--color-sky)] hover:bg-white/5"
                      title="Save"
                    >
                      <Check size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="rounded p-1 text-[var(--color-think)] hover:bg-white/5"
                      title="Cancel"
                    >
                      <X size={14} />
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className="min-w-0 flex-1 px-1 text-left"
                  >
                    <div className="truncate text-sm font-medium">{c.title}</div>
                    <div className="mt-0.5 text-[11px] text-[var(--color-think)] capitalize">
                      {c.status}
                    </div>
                  </button>
                  <div className="flex shrink-0 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      className="rounded p-1 text-[var(--color-think)] hover:bg-white/5 hover:text-white"
                      title="Rename"
                      onClick={(e) => {
                        e.stopPropagation()
                        setEditingId(c.id)
                        setDraft(c.title)
                      }}
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      type="button"
                      className="rounded p-1 text-[var(--color-pass)] hover:bg-white/5 hover:text-[var(--color-coral)]"
                      title="Delete"
                      disabled={busyId === c.id}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (!window.confirm(`Delete “${c.title}”? This cannot be undone.`)) return
                        setBusyId(c.id)
                        void onDelete(c.id).finally(() => setBusyId(null))
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
