function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export function Avatar({
  name,
  accent,
  size = 36,
}: {
  name: string
  accent?: string
  size?: number
}) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full font-[family-name:var(--font-display)] text-xs font-semibold text-white"
      style={{ width: size, height: size, background: accent || '#6BA3FF' }}
    >
      {initials(name)}
    </div>
  )
}
