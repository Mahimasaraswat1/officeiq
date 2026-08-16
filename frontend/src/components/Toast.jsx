/**
 * Transient success notices.
 *
 * Success and failure want opposite treatment. A success is news you needed
 * for a second — "saved", "downloaded" — and an inline banner that never goes
 * away then sits there pushing the page down until you navigate. A failure is
 * the opposite: it has to persist, and it belongs next to the thing that
 * failed so you can see what to fix.
 *
 * So toasts carry successes, and `Alert` keeps the errors inline.
 *
 * The viewport is a single `aria-live="polite"` region: announcements queue
 * behind whatever the reader is already hearing rather than interrupting, and
 * because the region is always mounted, a toast added later is still read out.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

const DEFAULT_DURATION_MS = 4500

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const show = useCallback(
    (message, { tone = 'success', duration = DEFAULT_DURATION_MS } = {}) => {
      if (!message) return undefined
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      setToasts((current) => [...current, { id, message, tone }])

      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        )
      }
      return id
    },
    [dismiss],
  )

  // Clear any pending timers if the provider itself goes away.
  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.clear()
    }
  }, [])

  const value = useMemo(() => ({ show, dismiss }), [show, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

const TONES = {
  success: 'bg-emerald-600 text-white',
  info: 'bg-slate-900 text-white',
  error: 'bg-red-600 text-white',
}

function ToastViewport({ toasts, onDismiss }) {
  return (
    <div
      // Always mounted so the live region exists before anything is added to
      // it — a region created at the same moment as its content is commonly
      // not announced at all.
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:bottom-auto sm:top-4 sm:items-end"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg px-4 py-3 shadow-lg ${
            TONES[toast.tone] ?? TONES.success
          }`}
        >
          <span className="min-w-0 flex-1 text-sm">{toast.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss notification"
            className="-mr-1 shrink-0 rounded px-1 text-white/80 transition hover:bg-white/15 hover:text-white"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}

/** `const toast = useToast()` then `toast.success('Saved.')`. */
export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used inside a <ToastProvider>')
  }
  const { show, dismiss } = context

  return useMemo(
    () => ({
      show,
      dismiss,
      success: (message, options) => show(message, { ...options, tone: 'success' }),
      info: (message, options) => show(message, { ...options, tone: 'info' }),
      error: (message, options) => show(message, { ...options, tone: 'error' }),
    }),
    [show, dismiss],
  )
}
