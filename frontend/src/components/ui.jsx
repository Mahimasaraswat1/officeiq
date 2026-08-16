/** Small shared presentational building blocks. */

import { Children, cloneElement, isValidElement, useId } from 'react'

export function Spinner({ label = 'Loading…', className = '' }) {
  return (
    <div className={`flex items-center justify-center gap-2 py-8 ${className}`} role="status">
      <SpinnerIcon className="h-4 w-4 text-slate-500" />
      <span className="text-sm text-slate-500">{label}</span>
    </div>
  )
}

/** The bare mark, for use inside a button or beside other content. */
export function SpinnerIcon({ className = 'h-4 w-4' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path
        d="M14.5 8A6.5 6.5 0 0 0 8 1.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}

/**
 * A grey placeholder in the shape of the content that is coming.
 *
 * Preferred over a spinner for a whole page or list: it keeps the layout from
 * jumping when the data lands, and reads as "nearly there" rather than "busy".
 */
export function Skeleton({ className = '' }) {
  return (
    <div
      className={`animate-pulse rounded bg-slate-200/70 ${className}`}
      aria-hidden="true"
    />
  )
}

/** A few skeleton rows, sized like a list or table body. */
export function SkeletonRows({ rows = 5, className = '' }) {
  return (
    <div className={`space-y-3 p-1 ${className}`} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-3">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  )
}

export function Button({
  variant = 'primary',
  loading = false,
  disabled = false,
  className = '',
  children,
  ...props
}) {
  const variants = {
    primary: 'bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-400',
    secondary:
      'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-500',
    danger: 'bg-red-600 text-white hover:bg-red-500 disabled:bg-red-300',
  }
  return (
    <button
      // A busy button must not be clickable twice, and aria-busy is what tells
      // a screen reader the label has not changed for no reason.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...props}
    >
      {loading && <SpinnerIcon />}
      {children}
    </button>
  )
}

export function Field({ label, error, hint, children }) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  // Wire the control to its hint and error text. Without this the red message
  // below an input is invisible to a screen reader — it sees an invalid field
  // and no reason why.
  const describedBy = [error ? errorId : null, hint && !error ? hintId : null]
    .filter(Boolean)
    .join(' ')

  // Only a single element can be wired up; anything else (a group of
  // checkboxes, say) is left alone rather than half-labelled.
  const child = Children.count(children) === 1 ? Children.only(children) : null
  const wired = isValidElement(child)
  const controlId = wired ? (child.props.id ?? id) : undefined

  const control = wired
    ? cloneElement(child, {
        id: controlId,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy || undefined,
        'aria-errormessage': error ? errorId : undefined,
      })
    : children

  return (
    <div className="block">
      <label
        htmlFor={controlId}
        className="mb-1 block text-sm font-medium text-slate-700"
      >
        {label}
      </label>
      {control}
      {hint && !error && (
        <span id={hintId} className="mt-1 block text-xs text-slate-500">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} className="mt-1 block text-xs text-red-600">
          {error}
        </span>
      )}
    </div>
  )
}

export function Input({ className = '', ...props }) {
  return (
    <input
      className={`w-full rounded-md border-0 px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 placeholder:text-slate-500 focus:ring-2 focus:ring-inset focus:ring-slate-900 aria-[invalid]:ring-red-400 ${className}`}
      {...props}
    />
  )
}

export function Select({ className = '', ...props }) {
  return (
    <select
      className={`w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-inset focus:ring-slate-900 ${className}`}
      {...props}
    />
  )
}

const ALERT_TONES = {
  error: { class: 'bg-red-50 text-red-800 ring-red-200', icon: '!' },
  success: { class: 'bg-emerald-50 text-emerald-800 ring-emerald-200', icon: '✓' },
  info: { class: 'bg-sky-50 text-sky-800 ring-sky-200', icon: 'i' },
}

export function Alert({ tone = 'error', children }) {
  if (!children) return null
  const { class: toneClass, icon } = ALERT_TONES[tone] ?? ALERT_TONES.error

  return (
    <div
      // An error announced only in colour and position never reaches a screen
      // reader. assertive for errors, polite for the rest, so a failed save
      // interrupts but a success notice waits its turn.
      role={tone === 'error' ? 'alert' : 'status'}
      aria-live={tone === 'error' ? 'assertive' : 'polite'}
      className={`flex items-start gap-2 rounded-md px-3 py-2 text-sm whitespace-pre-line ring-1 ${toneClass}`}
    >
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-current/15 text-[10px] font-bold"
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">{children}</span>
    </div>
  )
}

const STATUS_TONES = {
  invited: 'bg-slate-100 text-slate-700',
  registered: 'bg-sky-100 text-sky-800',
  documents_pending: 'bg-amber-100 text-amber-800',
  documents_submitted: 'bg-amber-100 text-amber-800',
  under_review: 'bg-violet-100 text-violet-800',
  tasks_assigned: 'bg-indigo-100 text-indigo-800',
  complete: 'bg-emerald-100 text-emerald-800',
  rejected: 'bg-red-100 text-red-800',
  pending: 'bg-amber-100 text-amber-800',
  accepted: 'bg-emerald-100 text-emerald-800',
  expired: 'bg-slate-100 text-slate-600',
  revoked: 'bg-red-100 text-red-800',
}

export function StatusBadge({ status }) {
  const tone = STATUS_TONES[status] ?? 'bg-slate-100 text-slate-700'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {String(status).replaceAll('_', ' ')}
    </span>
  )
}

export function Card({ title, action, children }) {
  return (
    <section className="rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-white px-5 py-4 shadow-sm ring-1 ring-slate-200">
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold text-slate-900">{value}</dd>
    </div>
  )
}

/**
 * "Nothing here" done properly.
 *
 * A bare line of grey text tells the reader the list is empty but not whether
 * that is normal, nor what to do about it. `title` says what is missing,
 * the body says why, and `action` gives them the next step — so an empty
 * screen becomes a starting point rather than a dead end.
 *
 * Still accepts a plain string child, so the simple cases stay one line.
 */
export function EmptyState({ icon, title, action, children }) {
  return (
    <div className="px-4 py-10 text-center">
      {icon && (
        <div
          aria-hidden="true"
          className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg"
        >
          {icon}
        </div>
      )}
      {title && <p className="text-sm font-medium text-slate-900">{title}</p>}
      {children && (
        <p className={`mx-auto max-w-sm text-sm text-slate-500 ${title ? 'mt-1' : ''}`}>
          {children}
        </p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
