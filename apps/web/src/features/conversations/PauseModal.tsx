import { Modal } from '../../shared/ui/Modal'

export function PauseModal({
  direction,
  onDirectionChange,
  onClose,
  onPauseOnly,
  onPauseWithDirection,
}: {
  direction: string
  onDirectionChange: (v: string) => void
  onClose: () => void
  onPauseOnly: () => void
  onPauseWithDirection: () => void
}) {
  return (
    <Modal title="Pause to direct" onClose={onClose}>
      <p className="mb-3 text-sm text-[var(--color-think)]">
        Add guidance for the experts, then pause. Resume when ready.
      </p>
      <textarea
        value={direction}
        onChange={(e) => onDirectionChange(e.target.value)}
        className="mb-4 h-28 w-full rounded-xl border border-[var(--color-line)] bg-black/20 px-3 py-2 text-sm outline-none focus:border-[var(--color-sky)]"
        placeholder="e.g. Focus on abuse resistance and keep the API simple…"
      />
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onPauseOnly}
          className="rounded-xl px-4 py-2 text-sm text-[var(--color-think)] hover:bg-white/5"
        >
          Pause only
        </button>
        <button
          type="button"
          onClick={onPauseWithDirection}
          className="rounded-xl bg-[var(--color-sky)] px-4 py-2 text-sm font-semibold text-[#12141a]"
        >
          Pause with direction
        </button>
      </div>
    </Modal>
  )
}
