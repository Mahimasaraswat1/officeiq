/**
 * Circular completion ring.
 *
 * Drawn with a stroke-dashoffset so the sweep animates when the number
 * changes — ticking a task off visibly moves the ring rather than snapping.
 * The arc is decorative; the percentage sits in the middle as real text, so a
 * screen reader gets the value without needing the geometry described.
 */

export default function ProgressRing({
  percent = 0,
  size = 160,
  stroke = 12,
  label,
  tone = 'accent',
}) {
  const safe = Math.max(0, Math.min(100, Math.round(percent)))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (safe / 100) * circumference

  const colours = {
    accent: '#2563eb',
    emerald: '#059669',
    red: '#dc2626',
  }
  const colour = colours[tone] ?? colours.accent

  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${safe}% complete${label ? ` — ${label}` : ''}`}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#e4e9f2"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={colour}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 700ms ease, stroke 300ms ease' }}
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold tracking-tight text-navy-900 tabular-nums">
          {safe}%
        </span>
        {label && (
          <span className="mt-0.5 text-xs font-medium text-navy-500">{label}</span>
        )}
      </div>
    </div>
  )
}
