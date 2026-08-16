/**
 * Header bell: unread badge plus a dropdown of the most recent notifications.
 *
 * The badge polls rather than holding a socket open — Phase 6 has no realtime
 * transport, and a 60s poll is honest about that instead of pretending to be live.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

const POLL_MS = 60_000

const ICONS = {
  document_approved: '✓',
  document_rejected: '!',
  document_uploaded: '↑',
  tasks_assigned: '☑',
  task_due_soon: '◷',
  task_overdue: '!',
  onboarding_complete: '★',
  invitation_accepted: '＋',
  verification_failed: '!',
  chat_escalated: '?',
}

// Warning tones are reserved for the notifications that actually need a
// decision; everything else stays neutral so the urgent ones still stand out.
const TONES = {
  document_rejected: 'bg-red-100 text-red-700',
  task_overdue: 'bg-red-100 text-red-700',
  verification_failed: 'bg-red-100 text-red-700',
  chat_escalated: 'bg-amber-100 text-amber-800',
  task_due_soon: 'bg-amber-100 text-amber-800',
  document_approved: 'bg-emerald-100 text-emerald-700',
  onboarding_complete: 'bg-emerald-100 text-emerald-700',
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const containerRef = useRef(null)
  const navigate = useNavigate()

  const refreshCount = useCallback(async () => {
    try {
      const { unread: count } = await api.unreadCount()
      setUnread(count)
    } catch {
      // A failed poll is not worth interrupting the page for; the next tick retries.
    }
  }, [])

  useEffect(() => {
    refreshCount()
    const timer = setInterval(refreshCount, POLL_MS)
    return () => clearInterval(timer)
  }, [refreshCount])

  // Close on an outside click or Escape, the way a menu is expected to behave.
  useEffect(() => {
    if (!open) return undefined
    const onClick = (event) => {
      if (!containerRef.current?.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next) return
    setLoading(true)
    try {
      const page = await api.listNotifications({ page_size: 8 })
      setItems(page.items)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  const openNotification = async (notification) => {
    setOpen(false)
    if (!notification.is_read) {
      try {
        await api.markNotificationRead(notification.id)
        setUnread((count) => Math.max(0, count - 1))
      } catch {
        // Navigation still matters more than the read receipt.
      }
    }
    if (notification.link) navigate(notification.link)
  }

  const markAll = async () => {
    await api.markAllNotificationsRead()
    setUnread(0)
    setItems((current) => current.map((item) => ({ ...item, is_read: true })))
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={toggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative rounded-md p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
          <path d="M10 2a5 5 0 0 0-5 5v2.6l-1.3 2.6A1 1 0 0 0 4.6 14h10.8a1 1 0 0 0 .9-1.4L15 9.6V7a5 5 0 0 0-5-5Zm0 16a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 10 18Z" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-red-600 px-1 text-[10px] leading-4 font-semibold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-88 max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg bg-white shadow-lg ring-1 ring-slate-200"
        >
          <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-slate-900">Notifications</h2>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAll}
                className="text-xs font-medium text-slate-500 hover:text-slate-900"
              >
                Mark all read
              </button>
            )}
          </header>

          <div className="max-h-96 overflow-y-auto">
            {loading && <p className="px-4 py-8 text-center text-sm text-slate-500">Loading…</p>}
            {!loading && items.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-slate-500">
                Nothing yet. Approvals, uploads and reminders land here.
              </p>
            )}
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => openNotification(item)}
                className={`flex w-full items-start gap-3 border-b border-slate-100 px-4 py-3 text-left transition last:border-0 hover:bg-slate-50 ${
                  item.is_read ? '' : 'bg-sky-50/60'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    TONES[item.type] ?? 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {ICONS[item.type] ?? '•'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-slate-900">{item.title}</span>
                  {item.body && (
                    <span className="mt-0.5 block line-clamp-2 text-xs text-slate-500">
                      {item.body}
                    </span>
                  )}
                  <span className="mt-1 block text-xs text-slate-500">
                    {relativeTime(item.created_at)}
                  </span>
                </span>
                {!item.is_read && (
                  <span
                    className="mt-2 h-2 w-2 shrink-0 rounded-full bg-sky-500"
                    aria-label="Unread"
                  />
                )}
              </button>
            ))}
          </div>

          <footer className="border-t border-slate-200 px-4 py-2 text-center">
            <Link
              to="/notifications"
              onClick={() => setOpen(false)}
              className="text-xs font-medium text-slate-600 hover:text-slate-900"
            >
              View all notifications →
            </Link>
          </footer>
        </div>
      )}
    </div>
  )
}

export function relativeTime(iso) {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
