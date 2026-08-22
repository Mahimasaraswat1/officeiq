/**
 * A confirmation dialog for actions that are worth a second thought.
 *
 * Focus moves to the confirm button on open and returns to whatever opened the
 * dialog on close, Escape cancels, and Tab is kept inside — so a keyboard user
 * is never left interacting with the page behind an open dialog.
 */

import { useEffect, useRef } from 'react'
import { Button } from './ui'

export default function ConfirmDialog({
  title,
  children,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'primary',
  busy = false,
  onConfirm,
  onCancel,
}) {
  const panelRef = useRef(null)
  const openerRef = useRef(null)

  useEffect(() => {
    openerRef.current = document.activeElement
    // Focus lands on the confirm button via its autoFocus prop below; Button
    // is a plain function component and does not forward refs on React 18.

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCancel()
        return
      }
      if (event.key !== 'Tab') return

      const focusable = panelRef.current?.querySelectorAll(
        'button:not([disabled]), a[href], input, select, textarea',
      )
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      openerRef.current?.focus?.()
    }
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/40 p-4 backdrop-blur-sm"
      onClick={onCancel}
      role="presentation"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-card-hover"
      >
        <h2 id="confirm-title" className="text-base font-bold text-navy-900">
          {title}
        </h2>
        <div className="mt-2 text-sm leading-relaxed text-navy-600">{children}</div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button autoFocus variant={tone} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
