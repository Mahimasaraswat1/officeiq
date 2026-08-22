/**
 * Header bell: unread badge plus a dropdown of the most recent notifications.
 *
 * The badge polls rather than holding a socket open — there is no realtime
 * transport in this build, and a 60s poll is honest about that instead of
 * pretending to be live.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

const POLL_MS = 60_000
const PANEL_SIZE = 8

/**
 * How each kind of alert looks.
 *
 * Warning tones are reserved for the notifications that actually need a
 * decision, so the urgent ones still stand out in a long list. Every row also
 * carries its text, so colour is never the only signal.
 */
const TYPE_STYLE = {
  document_rejected: { tile: 'bg-red-50 text-red-600', icon: 'alert' },
  task_overdue: { tile: 'bg-red-50 text-red-600', icon: 'alert' },
  verification_failed: { tile: 'bg-red-50 text-red-600', icon: 'alert' },
  chat_escalated: { tile: 'bg-amber-50 text-amber-700', icon: 'chat' },
  task_due_soon: { tile: 'bg-amber-50 text-amber-700', icon: 'clock' },
  document_approved: { tile: 'bg-emerald-50 text-emerald-600', icon: 'check' },
  onboarding_complete: { tile: 'bg-emerald-50 text-emerald-600', icon: 'check' },
  document_uploaded: { tile: 'bg-accent-50 text-accent-600', icon: 'doc' },
  tasks_assigned: { tile: 'bg-accent-50 text-accent-600', icon: 'list' },
  invitation_accepted: { tile: 'bg-navy-100 text-navy-700', icon: 'user' },
}

const ICON_PATH = {
  alert: <path d="M10 1.5l8.5 15H1.5l8.5-15zM9 7v5h2V7H9zm0 6.5v2h2v-2H9z" />,
  check: <path d="M10 2a8 8 0 100 16 8 8 0 000-16zm3.9 6.1l-4.4 4.4a1 1 0 01-1.4 0L6 10.4l1.4-1.4 1.4 1.4 3.7-3.7 1.4 1.4z" />,
  clock: (
    <>
      <path fillRule="evenodd" clipRule="evenodd" d="M10 2a8 8 0 100 16 8 8 0 000-16zm0 1.6a6.4 6.4 0 110 12.8 6.4 6.4 0 010-12.8z" />
      <path d="M9.25 5.5h1.5v4.3l2.9 1.7-.75 1.3-3.65-2.1V5.5z" />
    </>
  ),
  doc: <path d="M5 2h7l3 3v13H5V2zm6 1.5V6h2.5L11 3.5z" />,
  list: <path d="M4 4h12v2H4V4zm0 5h12v2H4V9zm0 5h8v2H4v-2z" />,
  chat: <path d="M10 2c4.4 0 8 3 8 6.7 0 3.7-3.6 6.7-8 6.7-.9 0-1.8-.1-2.6-.4L3 17l1.2-3.2C2.8 12.5 2 10.7 2 8.7 2 5 5.6 2 10 2z" />,
  user: <path d="M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm0 1.5c-3.3 0-6 2-6 4.5v1h12v-1c0-2.5-2.7-4.5-6-4.5z" />,
}

const isToday = (iso) => new Date(iso).toDateString() === new Date().toDateString()

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const containerRef = useRef(null)
  const buttonRef = useRef(null)
  const panelRef = useRef(null)
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
  // Escape hands focus back to the bell rather than dropping it on the body.
  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) setOpen(false)
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next) return
    setLoading(true)
    try {
      const page = await api.listNotifications({ page_size: PANEL_SIZE })
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

  const today = items.filter((item) => isToday(item.created_at))
  const earlier = items.filter((item) => !isToday(item.created_at))

  const renderGroup = (label, group) =>
    group.length > 0 && (
      <div key={label}>
        <p className="sticky top-0 bg-navy-50/90 px-4 py-1.5 text-xs font-semibold tracking-wide text-navy-500 uppercase backdrop-blur">
          {label}
        </p>
        {group.map((item) => {
          const style = TYPE_STYLE[item.type] ?? { tile: 'bg-navy-100 text-navy-700', icon: 'doc' }
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => openNotification(item)}
              className={`flex w-full items-start gap-3 border-b border-navy-100 px-4 py-3 text-left transition last:border-0 hover:bg-navy-50 ${
                item.is_read ? '' : 'bg-accent-50/40'
              }`}
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${style.tile}`}
              >
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                  {ICON_PATH[style.icon]}
                </svg>
              </span>

              <span className="min-w-0 flex-1">
                <span
                  className={`block text-sm ${item.is_read ? 'text-navy-700' : 'font-semibold text-navy-900'}`}
                >
                  {item.title}
                </span>
                {item.body && (
                  <span className="mt-0.5 line-clamp-2 block text-xs text-navy-500">
                    {item.body}
                  </span>
                )}
                <span className="mt-1 block text-xs text-navy-400">
                  {relativeTime(item.created_at)}
                </span>
              </span>

              {!item.is_read && (
                <span
                  className="mt-2 h-2 w-2 shrink-0 rounded-full bg-accent-600"
                  aria-label="Unread"
                />
              )}
            </button>
          )
        })}
      </div>
    )

  return (
    <div className="relative" ref={containerRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative rounded-xl p-2 text-navy-600 transition hover:bg-navy-100 hover:text-navy-900"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
          <path d="M10 2a5 5 0 00-5 5v2.6l-1.3 2.6A1 1 0 004.6 14h10.8a1 1 0 00.9-1.4L15 9.6V7a5 5 0 00-5-5zm0 16a2.5 2.5 0 002.45-2h-4.9A2.5 2.5 0 0010 18z" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-red-600 px-1 text-[10px] leading-4 font-bold text-white ring-2 ring-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 z-40 mt-2 w-88 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl bg-white shadow-card-hover ring-1 ring-navy-100"
        >
          <header className="flex items-center justify-between gap-2 border-b border-navy-100 px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-bold text-navy-900">
              Notifications
              {unread > 0 && (
                <span className="rounded-full bg-accent-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {unread}
                </span>
              )}
            </h2>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAll}
                className="rounded-lg px-2 py-1 text-xs font-semibold text-accent-600 transition hover:bg-accent-50"
              >
                Mark all read
              </button>
            )}
          </header>

          <div className="max-h-96 overflow-y-auto">
            {loading && (
              <p className="px-4 py-10 text-center text-sm text-navy-500">Loading…</p>
            )}
            {!loading && items.length === 0 && (
              <div className="px-4 py-10 text-center">
                <span aria-hidden="true" className="text-2xl">
                  🔔
                </span>
                <p className="mt-2 text-sm font-semibold text-navy-900">You're all caught up</p>
                <p className="mt-0.5 text-xs text-navy-500">
                  Approvals, uploads and reminders land here.
                </p>
              </div>
            )}
            {!loading && renderGroup('Today', today)}
            {!loading && renderGroup('Earlier', earlier)}
          </div>

          <footer className="border-t border-navy-100 px-4 py-2.5 text-center">
            <Link
              to="/notifications"
              onClick={() => setOpen(false)}
              className="text-xs font-semibold text-navy-600 transition hover:text-navy-900"
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
