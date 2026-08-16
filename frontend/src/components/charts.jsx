/**
 * Inline-SVG charts for the HR dashboard. No charting library — these are two
 * fixed forms drawn by hand, which keeps the bundle small and the marks exactly
 * to spec.
 *
 * Both charts plot a *single* series, so there is no legend: the card title
 * already names what is plotted, and one colour never has to stand for identity.
 * Every value a tooltip shows is also reachable without hovering — the funnel
 * labels each bar, and each trend card ships a table view — so the hover layer
 * enhances rather than gates.
 */

import { useId, useState } from 'react'

// One data hue for every chart. Ordered categories are NOT ramped: a darker bar
// for a bigger value would double-encode length as colour and say nothing new.
const DATA = '#4f46e5'
const GRID = '#e2e8f0'
const SURFACE = '#ffffff'

const compact = (n) =>
  n >= 10_000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : n.toLocaleString()

/**
 * Horizontal bars for an ordered set of stages. Bars grow from a shared
 * baseline on the left, with the value labelled at the tip.
 */
export function FunnelBars({ stages }) {
  const max = Math.max(1, ...stages.map((s) => s.count))

  return (
    <ol className="space-y-2.5">
      {stages.map((stage) => {
        const pct = (stage.count / max) * 100
        return (
          <li key={stage.status} className="grid grid-cols-[9.5rem_1fr] items-center gap-3">
            <span className="truncate text-xs text-slate-600" title={stage.label}>
              {stage.label}
            </span>
            <div className="flex items-center gap-2">
              {/* The track is the baseline; the bar is capped at 14px so the
                  row keeps its air rather than filling the slot. */}
              <div className="h-3.5 flex-1 rounded-r-[4px] bg-slate-100">
                <div
                  className="h-3.5 rounded-r-[4px] transition-[width] duration-300"
                  style={{
                    width: `${Math.max(pct, stage.count > 0 ? 2 : 0)}%`,
                    backgroundColor: DATA,
                  }}
                  role="img"
                  aria-label={`${stage.label}: ${stage.count}`}
                />
              </div>
              <span className="w-8 shrink-0 text-right text-xs font-medium tabular-nums text-slate-900">
                {stage.count}
              </span>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/**
 * A single-series area + line over time, sized to sit three-across as small
 * multiples. Small multiples rather than one multi-series chart: the three
 * measures have unrelated scales, and putting them on one plot would mean a
 * second y-axis.
 */
export function TrendChart({ points, valueKey, label, height = 72 }) {
  const gradientId = useId()
  const [hover, setHover] = useState(null)

  const values = points.map((p) => p[valueKey])
  const max = Math.max(1, ...values)
  const total = values.reduce((sum, v) => sum + v, 0)

  const width = 300
  const padY = 6
  const usable = height - padY * 2
  const step = points.length > 1 ? width / (points.length - 1) : width

  const x = (i) => (points.length > 1 ? i * step : width / 2)
  const y = (v) => padY + usable - (v / max) * usable

  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p[valueKey])}`).join(' ')
  const area = `${line} L${x(points.length - 1)},${height} L${x(0)},${height} Z`

  const last = points[points.length - 1]
  const active = hover ?? points.length - 1

  const handleMove = (event) => {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    // The crosshair snaps to the nearest day — nobody aims at a 2px line.
    setHover(Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1)))))
  }

  return (
    <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-medium text-slate-500">{label}</h3>
        <span className="text-lg font-semibold tabular-nums text-slate-900">
          {compact(total)}
        </span>
      </div>

      <div
        className="relative mt-2"
        onPointerMove={handleMove}
        onPointerLeave={() => setHover(null)}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="w-full"
          style={{ height }}
          role="img"
          aria-label={`${label}: ${total} over ${points.length} days`}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={DATA} stopOpacity="0.16" />
              <stop offset="100%" stopColor={DATA} stopOpacity="0.01" />
            </linearGradient>
          </defs>

          {/* Hairline baseline, one step off the surface and recessive. */}
          <line x1="0" y1={height - 0.5} x2={width} y2={height - 0.5} stroke={GRID} strokeWidth="1" />
          <path d={area} fill={`url(#${gradientId})`} />
          <path
            d={line}
            fill="none"
            stroke={DATA}
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />

          {hover !== null && (
            <line
              x1={x(hover)}
              y1="0"
              x2={x(hover)}
              y2={height}
              stroke={GRID}
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
          )}

          {/* End marker carries a surface ring so it stays legible over the line. */}
          <circle
            cx={x(active)}
            cy={y(points[active][valueKey])}
            r="4"
            fill={DATA}
            stroke={SURFACE}
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        <p className="mt-1 text-xs text-slate-500">
          {hover === null ? (
            <>
              {compact(last[valueKey])} on {formatDay(last.date)}
            </>
          ) : (
            <>
              <span className="font-medium text-slate-900">
                {compact(points[hover][valueKey])}
              </span>{' '}
              on {formatDay(points[hover].date)}
            </>
          )}
        </p>
      </div>

      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-600">
          Table view
        </summary>
        <table className="mt-2 w-full text-xs">
          <tbody>
            {points
              .filter((p) => p[valueKey] > 0)
              .map((p) => (
                <tr key={p.date} className="border-t border-slate-100">
                  <td className="py-1 text-slate-500">{formatDay(p.date)}</td>
                  <td className="py-1 text-right tabular-nums text-slate-900">
                    {p[valueKey]}
                  </td>
                </tr>
              ))}
            {total === 0 && (
              <tr>
                <td className="py-1 text-slate-500">No activity in this window.</td>
              </tr>
            )}
          </tbody>
        </table>
      </details>
    </div>
  )
}

function formatDay(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}
