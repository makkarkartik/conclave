import { useState } from 'react'
import { Modal } from '../../shared/ui/Modal'
import { api, type Expert } from '../../shared/lib/api'

type Form = {
  name: string
  persona: string
  provider: string
  model: string
  api_key: string
}

export function ExpertModal({
  expert,
  onClose,
  onSaved,
}: {
  expert?: Expert | null
  onClose: () => void
  onSaved: () => void
}) {
  const editing = Boolean(expert)
  const [form, setForm] = useState<Form>({
    name: expert?.name ?? '',
    persona: expert?.persona ?? '',
    provider: expert?.provider ?? 'openai',
    model: expert?.model ?? 'gpt-4.1',
    api_key: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  return (
    <Modal title={editing ? 'Edit connector' : 'Add configured expert'} onClose={onClose}>
      <p className="mb-4 text-xs leading-relaxed text-[var(--color-think)]">
        Needs a <strong className="text-white">developer API key</strong> from OpenAI, Anthropic, or Google AI
        Studio. ChatGPT Plus or Claude Pro alone will not work.
        {editing && (
          <>
            {' '}
            Leave API key blank to keep the current key ({expert?.api_key_masked}).
          </>
        )}
      </p>
      <div className="space-y-3">
        {(
          [
            ['name', 'Name'],
            ['persona', 'Persona (optional)'],
            ['model', 'Model'],
            ['api_key', editing ? 'API key (optional)' : 'API key'],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="block text-xs text-[var(--color-think)]">
            {label}
            <input
              type={key === 'api_key' ? 'password' : 'text'}
              value={form[key]}
              placeholder={
                key === 'api_key' && editing ? expert?.api_key_masked || '••••' : undefined
              }
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              className="mt-1 w-full rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 text-sm text-white outline-none focus:border-[var(--color-sky)]"
            />
          </label>
        ))}
        <label className="block text-xs text-[var(--color-think)]">
          Provider
          <select
            value={form.provider}
            onChange={(e) => setForm({ ...form, provider: e.target.value })}
            className="mt-1 w-full rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 text-sm text-white outline-none"
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="google">Google</option>
          </select>
        </label>
      </div>
      {err && <p className="mt-2 text-xs text-[var(--color-coral)]">{err}</p>}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setErr('')
            try {
              if (editing && expert) {
                const body: Record<string, string> = {
                  name: form.name,
                  persona: form.persona,
                  provider: form.provider,
                  model: form.model,
                }
                if (form.api_key.trim()) body.api_key = form.api_key.trim()
                await api.updateExpert(expert.id, body)
              } else {
                await api.createExpert(form)
              }
              onSaved()
            } catch (e) {
              setErr(String(e))
            } finally {
              setBusy(false)
            }
          }}
          className="rounded-xl bg-[var(--color-sky)] px-4 py-2 text-sm font-semibold text-[#12141a] disabled:opacity-50"
        >
          {editing ? 'Save changes' : 'Save expert'}
        </button>
      </div>
    </Modal>
  )
}
