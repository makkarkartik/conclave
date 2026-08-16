import { motion } from 'framer-motion'
import { Lock } from 'lucide-react'
import { Avatar } from '../../shared/ui/Avatar'
import type { Expert } from '../../shared/lib/api'

/** Skeleton "text" lines that write themselves in, staggered per card so the
 * grid reads as N experts working at once — not one after another. */
function WritingLines({ seed }: { seed: number }) {
  // Deterministic per-card widths so the cards look distinct but stable.
  const widths = [88, 72, 94, 61, 80, 68, 90].map((w, i) => ((w + seed * 13 + i * 7) % 40) + 55)
  return (
    <div className="mt-3 space-y-2">
      {widths.map((w, i) => (
        <motion.div
          key={i}
          className="h-1.5 rounded-full bg-[var(--color-line)]"
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: [`0%`, `${w}%`, `${w}%`, `0%`], opacity: [0, 1, 1, 0] }}
          transition={{
            duration: 6,
            times: [0, 0.35, 0.85, 1],
            delay: seed * 0.6 + i * 0.35,
            repeat: Infinity,
            repeatDelay: 1.2,
            ease: 'easeInOut',
          }}
        />
      ))}
    </div>
  )
}

/** The sealed-drafting phase, made visible: every seat drafts blind, in
 * parallel. Rendered as a grid of walled-off cards — the visual opposite of
 * the serial "thinking" bubble — because the waiting IS the experience here:
 * the drafts all land at once when they are done. */
export function SealedDrafting({ experts }: { experts: Expert[] }) {
  return (
    <div className="mx-auto w-full max-w-3xl py-6">
      <div className="mb-4 flex items-center justify-center gap-2 text-xs text-[var(--color-think)]">
        <Lock size={12} className="text-[var(--color-sky)]" />
        <span>
          Sealed drafts in progress — {experts.length} experts working blind, in parallel. Nobody
          sees anyone else&apos;s work until every draft is in.
        </span>
      </div>
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${Math.min(experts.length, 4)}, minmax(0, 1fr))` }}
      >
        {experts.map((e, i) => (
          <motion.div
            key={e.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            className="relative overflow-hidden rounded-2xl border border-[var(--color-line)] bg-[rgba(28,31,42,0.6)] p-4"
          >
            {/* the seal: a soft sweep of light, offset per card */}
            <motion.div
              aria-hidden
              className="pointer-events-none absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-white/[0.04] to-transparent"
              initial={{ x: '-100%' }}
              animate={{ x: '300%' }}
              transition={{ duration: 3.2, delay: i * 0.5, repeat: Infinity, ease: 'linear' }}
            />
            <div className="flex items-center gap-2">
              <div className="relative">
                <Avatar name={e.name} accent={e.accent} size={28} />
                <motion.span
                  aria-hidden
                  className="absolute -inset-1 rounded-full border"
                  style={{ borderColor: e.accent }}
                  animate={{ opacity: [0.15, 0.6, 0.15], scale: [1, 1.08, 1] }}
                  transition={{ duration: 1.8, delay: i * 0.3, repeat: Infinity, ease: 'easeInOut' }}
                />
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{e.name}</div>
                <div className="truncate text-[10px] text-[var(--color-pass)]">{e.model}</div>
              </div>
              <Lock size={11} className="ml-auto shrink-0 text-[var(--color-pass)]" />
            </div>
            <WritingLines seed={i} />
            <div className="mt-3 flex items-center gap-1.5 text-[10px] text-[var(--color-think)]">
              <span className="relative flex h-1.5 w-1.5">
                <span
                  className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
                  style={{ background: e.accent }}
                />
                <span
                  className="relative inline-flex h-1.5 w-1.5 rounded-full"
                  style={{ background: e.accent }}
                />
              </span>
              drafting alone
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
