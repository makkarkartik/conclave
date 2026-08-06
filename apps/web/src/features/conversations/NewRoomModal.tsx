import { useState } from 'react'
import { Modal } from '../../shared/ui/Modal'
import { Avatar } from '../../shared/ui/Avatar'
import { api, type Expert } from '../../shared/lib/api'

export function NewRoomModal({
  experts,
  onClose,
  onCreated,
}: {
  experts: Expert[]
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const [topic, setTopic] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [err, setErr] = useState('')

  function toggle(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  }

  return (
    <Modal title="New conversation" onClose={onClose}>
      <label className="block text-xs text-[var(--color-think)]">
        Topic
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          className="mt-1 h-24 w-full rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 text-sm text-white outline-none focus:border-[var(--color-sky)]"
          placeholder="Design a fair rate limiter for a public API"
        />
      </label>
      <div className="mt-4">
        <div className="mb-2 text-xs text-[var(--color-think)]">Seat experts (order = chair order)</div>
        <div className="max-h-40 space-y-1 overflow-y-auto">
          {experts.map((e) => (
            <label
              key={e.id}
              className="flex cursor-pointer items-center gap-2 rounded-xl px-2 py-1.5 hover:bg-white/[0.03]"
            >
              <input type="checkbox" checked={selected.includes(e.id)} onChange={() => toggle(e.id)} />
              <Avatar name={e.name} accent={e.accent} size={24} />
              <span className="text-sm">{e.name}</span>
            </label>
          ))}
        </div>
      </div>
      {err && <p className="mt-2 text-xs text-[var(--color-coral)]">{err}</p>}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={async () => {
            setErr('')
            if (selected.length < 2) {
              setErr('Seat at least two experts')
              return
            }
            try {
              const c = await api.createConversation({ topic, chair_ids: selected })
              onCreated(c.id)
            } catch (e) {
              setErr(String(e))
            }
          }}
          className="rounded-xl bg-[var(--color-sky)] px-4 py-2 text-sm font-semibold text-[#12141a]"
        >
          Create
        </button>
      </div>
    </Modal>
  )
}
