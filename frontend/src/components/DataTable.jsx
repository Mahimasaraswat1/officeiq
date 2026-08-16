/**
 * One table definition, two layouts.
 *
 * Above `sm` this renders an ordinary `<table>`. Below it, each row becomes a
 * card: the column marked `primary` is the heading, and the rest are shown as
 * label/value pairs.
 *
 * The problem it solves: the previous tables scrolled sideways inside their
 * container on a phone, which pushed the columns that matter most — an
 * employee's onboarding status, a user's role — off the screen with no hint
 * that anything was hidden. A card shows every field.
 *
 * Columns are declared once, so the two layouts cannot drift apart.
 *
 * A column is:
 *   key      unique string
 *   header   column heading; '' marks an action column (no label on mobile)
 *   cell     (row) => node
 *   primary  true on the one column that titles the card
 *   align    'right' to right-align in the table
 *   hideOnMobile  drop from the card when it is noise on a small screen
 */

import { EmptyState, SkeletonRows } from './ui'

export default function DataTable({
  columns,
  rows,
  rowKey,
  onRowClick,
  rowLabel,
  loading = false,
  skeletonRows = 6,
  empty = 'Nothing to show.',
}) {
  if (loading) return <SkeletonRows rows={skeletonRows} className="p-5" />
  if (!rows?.length) {
    return typeof empty === 'string' ? <EmptyState>{empty}</EmptyState> : empty
  }

  const clickable = typeof onRowClick === 'function'
  const primary = columns.find((column) => column.primary) ?? columns[0]
  const secondary = columns.filter(
    (column) => column !== primary && !column.hideOnMobile,
  )

  // Enter and Space activate a clickable row, matching what a button does.
  const keyActivate = (row) => (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onRowClick(row)
    }
  }

  return (
    <>
      {/* --- Table: sm and up ------------------------------------------- */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={`px-5 py-3 font-medium ${
                    column.align === 'right' ? 'text-right' : ''
                  }`}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={clickable ? () => onRowClick(row) : undefined}
                onKeyDown={clickable ? keyActivate(row) : undefined}
                tabIndex={clickable ? 0 : undefined}
                aria-label={clickable && rowLabel ? rowLabel(row) : undefined}
                className={
                  clickable
                    ? 'cursor-pointer hover:bg-slate-50 focus-visible:bg-slate-100'
                    : 'hover:bg-slate-50'
                }
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`px-5 py-3 ${column.align === 'right' ? 'text-right' : ''} ${
                      column.className ?? ''
                    }`}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* --- Cards: below sm --------------------------------------------- */}
      <ul className="divide-y divide-slate-100 sm:hidden">
        {rows.map((row) => {
          const content = (
            <>
              <div className="text-sm font-medium text-slate-900">
                {primary.cell(row)}
              </div>
              <dl className="mt-2 space-y-1.5">
                {secondary.map((column) => (
                  <div key={column.key} className="flex items-start justify-between gap-3">
                    {/* An action column has no heading, so it gets no label
                        and takes the full width instead. */}
                    {column.header ? (
                      <>
                        <dt className="shrink-0 text-xs text-slate-500">{column.header}</dt>
                        <dd className="min-w-0 text-right text-sm break-words text-slate-700">
                          {column.cell(row)}
                        </dd>
                      </>
                    ) : (
                      <dd className="w-full">{column.cell(row)}</dd>
                    )}
                  </div>
                ))}
              </dl>
            </>
          )

          return (
            <li key={rowKey(row)}>
              {clickable ? (
                <div
                  role="button"
                  tabIndex={0}
                  aria-label={rowLabel ? rowLabel(row) : undefined}
                  onClick={() => onRowClick(row)}
                  onKeyDown={keyActivate(row)}
                  className="w-full cursor-pointer px-4 py-3 text-left hover:bg-slate-50 focus-visible:bg-slate-100"
                >
                  {content}
                </div>
              ) : (
                <div className="px-4 py-3">{content}</div>
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}
