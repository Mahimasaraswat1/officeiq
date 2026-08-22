/**
 * The stat-card pattern used across every dashboard.
 *
 * Fixed anatomy so a row of them scans as one object: tinted icon top-left,
 * trend chip top-right, the number large, its label underneath.
 *
 * `trend` is optional by design. Several metrics have no historical series
 * behind them, and inventing a percentage for those would be worse than an
 * empty corner — see the note in the HR dashboard about which cards can and
 * cannot show one.
 */

export const TREND_UP_IS_GOOD = 'up-good'
export const TREND_UP_IS_BAD = 'up-bad'

export default function StatCard({
  icon,
  label,
  value,
  hint,
  trend = null,
  trendPolarity = TREND_UP_IS_GOOD,
  tone = 'accent',
}) {
  const tones = {
    accent: 'bg-accent-50 text-accent-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    amber: 'bg-amber-50 text-amber-600',
    red: 'bg-red-50 text-red-600',
    navy: 'bg-navy-100 text-navy-700',
  }

  // "Good" depends on the metric: more new hires is good, more overdue tasks
  // is not. Colour follows meaning, not direction.
  // 'new' means there was no prior period to compare against.
  const isNew = trend === 'new'
  const rising = typeof trend === 'number' && trend > 0
  const good = trendPolarity === TREND_UP_IS_GOOD ? rising : !rising
  const flat = trend === 0

  return (
    <div className="group rounded-2xl bg-white p-5 shadow-card ring-1 ring-navy-100/70 transition duration-200 hover:-translate-y-0.5 hover:shadow-card-hover">
      <div className="flex items-start justify-between gap-3">
        <span
          className={`flex h-10 w-10 items-center justify-center rounded-xl transition duration-200 group-hover:scale-105 ${tones[tone] ?? tones.accent}`}
        >
          {icon}
        </span>

        {isNew && (
          <span
            className="inline-flex items-center rounded-full bg-accent-50 px-2 py-0.5 text-xs font-semibold text-accent-700"
            title="No activity in the previous period to compare against"
          >
            New
          </span>
        )}

        {typeof trend === 'number' && (
          <span
            className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-semibold ${
              flat
                ? 'bg-navy-100 text-navy-600'
                : good
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'bg-red-50 text-red-700'
            }`}
          >
            {!flat && (
              <svg viewBox="0 0 12 12" fill="currentColor" className="h-3 w-3" aria-hidden="true">
                {rising ? <path d="M6 2.5L10 8H2z" /> : <path d="M6 9.5L2 4h8z" />}
              </svg>
            )}
            {trend > 0 ? '+' : ''}
            {trend}%
          </span>
        )}
      </div>

      <p className="mt-4 text-3xl font-bold tracking-tight text-navy-900 tabular-nums">
        {value}
      </p>
      <p className="mt-0.5 text-sm font-medium text-navy-500">{label}</p>
      {hint && <p className="mt-1 text-xs text-navy-400">{hint}</p>}
    </div>
  )
}
