/**
 * The onboarding pipeline as a single stacked bar plus a legend.
 *
 * The four segments partition the workforce — every employee is counted once,
 * so the bar always totals 100%. That is why "Overdue" is carved *out* of
 * "In progress" rather than added alongside it: someone with an overdue task
 * is also mid-onboarding, and counting them twice would make the bar lie.
 *
 * Segments are separated by a 2px surface gap rather than a border, so
 * neighbouring colours stay distinct without adding ink that isn't data.
 */

export const PIPELINE_COLOURS = {
  completed: '#059669', // emerald-600
  in_progress: '#2563eb', // accent-600
  overdue: '#dc2626', // red-600
  not_started: '#c7d1e3', // navy-200
}

const LABELS = {
  completed: 'Completed',
  in_progress: 'In progress',
  overdue: 'Overdue',
  not_started: 'Not started',
}

const ORDER = ['completed', 'in_progress', 'overdue', 'not_started']

export default function PipelineBar({ counts, total, footnote }) {
  const sum = total ?? ORDER.reduce((acc, key) => acc + (counts[key] ?? 0), 0)

  if (sum === 0) {
    return (
      <p className="py-6 text-center text-sm text-navy-500">
        No employees to chart yet.
      </p>
    )
  }

  const segments = ORDER.map((key) => ({
    key,
    label: LABELS[key],
    count: counts[key] ?? 0,
    pct: ((counts[key] ?? 0) / sum) * 100,
  }))

  return (
    <div>
      <div
        className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full bg-navy-50"
        role="img"
        aria-label={segments.map((s) => `${s.label}: ${s.count}`).join(', ')}
      >
        {segments
          .filter((segment) => segment.count > 0)
          .map((segment) => (
            <div
              key={segment.key}
              // A minimum width keeps a single-person segment visible instead
              // of collapsing to nothing on a wide bar.
              style={{
                width: `${Math.max(segment.pct, 1.5)}%`,
                backgroundColor: PIPELINE_COLOURS[segment.key],
              }}
              className="h-full transition-[width] duration-500 first:rounded-l-full last:rounded-r-full"
              title={`${segment.label}: ${segment.count}`}
            />
          ))}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        {segments.map((segment) => (
          <div key={segment.key} className="flex items-start gap-2">
            <span
              aria-hidden="true"
              className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: PIPELINE_COLOURS[segment.key] }}
            />
            <div className="min-w-0">
              <dt className="text-xs font-medium text-navy-500">{segment.label}</dt>
              <dd className="text-lg font-bold tabular-nums text-navy-900">
                {segment.count}
                <span className="ml-1 text-xs font-medium text-navy-400">
                  {Math.round(segment.pct)}%
                </span>
              </dd>
            </div>
          </div>
        ))}
      </dl>

      {footnote && <p className="mt-3 text-xs text-navy-400">{footnote}</p>}
    </div>
  )
}
