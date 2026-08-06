import { Pencil, Plus, Trash2 } from 'lucide-react'
import { Avatar } from '../../shared/ui/Avatar'
import type { Expert } from '../../shared/lib/api'

export function ExpertList({
  experts,
  onAdd,
  onEdit,
  onDelete,
}: {
  experts: Expert[]
  onAdd: () => void
  onEdit: (expert: Expert) => void
  onDelete: (id: string) => void
}) {
  return (
    <div className="px-4 pb-3">
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-[11px] font-semibold tracking-wide text-[var(--color-think)] uppercase">
          Experts
        </span>
        <button
          type="button"
          onClick={onAdd}
          className="rounded-md p-1 text-[var(--color-think)] hover:bg-white/5 hover:text-white"
          title="Add configured expert"
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="max-h-[160px] space-y-1 overflow-y-auto">
        {experts.map((e) => (
          <div key={e.id} className="group flex items-center gap-2 rounded-xl px-2 py-1.5 hover:bg-white/[0.03]">
            <Avatar name={e.name} accent={e.accent} size={28} />
            <button
              type="button"
              onClick={() => onEdit(e)}
              className="min-w-0 flex-1 text-left"
              title="Edit connector"
            >
              <div className="truncate text-sm font-medium">{e.name}</div>
              <div className="truncate text-[10px] text-[var(--color-think)]">
                {e.provider} · {e.model}
              </div>
            </button>
            <div className="flex shrink-0 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
              <button
                type="button"
                className="p-1 text-[var(--color-think)] hover:text-white"
                title="Edit connector"
                onClick={() => onEdit(e)}
              >
                <Pencil size={14} />
              </button>
              <button
                type="button"
                className="p-1 text-[var(--color-pass)] hover:text-[var(--color-coral)]"
                title="Delete"
                onClick={() => onDelete(e.id)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        {!experts.length && (
          <p className="px-2 text-xs text-[var(--color-pass)]">Add API-key experts to begin.</p>
        )}
      </div>
    </div>
  )
}
