/** The full notification inbox — the bell dropdown's "view all" destination. */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Alert, Button, Card, EmptyState, Select, SkeletonRows } from '../components/ui'
import { relativeTime } from '../components/NotificationBell'
import { useToast } from '../components/Toast'

const PAGE_SIZE = 20

const TYPE_LABELS = {
  document_approved: 'Document approved',
  document_rejected: 'Document rejected',
  document_uploaded: 'Document uploaded',
  tasks_assigned: 'Tasks assigned',
  task_due_soon: 'Task due soon',
  task_overdue: 'Task overdue',
  onboarding_complete: 'Onboarding complete',
  invitation_accepted: 'Invitation accepted',
  verification_failed: 'Verification failed',
  chat_escalated: 'Question escalated',
}

export default function Notifications() {
  const toast = useToast()
  const [page, setPage] = useState(1)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [type, setType] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reminding, setReminding] = useState(false)
  const navigate = useNavigate()
  const { isHr } = useAuth()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const body = await api.listNotifications({
        page,
        page_size: PAGE_SIZE,
        unread_only: unreadOnly || undefined,
        type: type || undefined,
      })
      setData(body)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [page, unreadOnly, type])

  useEffect(() => {
    load()
  }, [load])

  const open = async (item) => {
    if (!item.is_read) await api.markNotificationRead(item.id).catch(() => {})
    if (item.link) navigate(item.link)
    else load()
  }

  const dismiss = async (event, id) => {
    event.stopPropagation()
    await api.dismissNotification(id)
    load()
  }

  const markAll = async () => {
    const { marked_read } = await api.markAllNotificationsRead()
    toast.success(`Marked ${marked_read} notification${marked_read === 1 ? '' : 's'} as read.`)
    load()
  }

  const runReminders = async () => {
    setReminding(true)
    try {
      const { due_soon, overdue } = await api.runReminders()
      toast.success(
        due_soon + overdue === 0
          ? 'No new reminders — everyone already has an unread reminder for their open tasks.'
          : `Sent ${overdue} overdue and ${due_soon} due-soon reminder(s).`,
      )
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setReminding(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Notifications</h1>
          <p className="mt-1 text-sm text-slate-500">
            Everything that happened while you were away.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={markAll}>
            Mark all read
          </Button>
          {isHr && (
            <Button variant="secondary" onClick={runReminders} loading={reminding}>
              Send task reminders
            </Button>
          )}
        </div>
      </div>

      <Alert>{error}</Alert>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(event) => {
              setUnreadOnly(event.target.checked)
              setPage(1)
            }}
            className="rounded border-slate-300"
          />
          Unread only
        </label>
        <Select
          value={type}
          onChange={(event) => {
            setType(event.target.value)
            setPage(1)
          }}
          className="max-w-56"
        >
          <option value="">All types</option>
          {Object.entries(TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      <Card>
        {loading && <SkeletonRows rows={5} />}
        {!loading && data?.items.length === 0 && (
          <EmptyState>
            {unreadOnly || type
              ? 'Nothing matches this filter.'
              : 'No notifications yet.'}
          </EmptyState>
        )}
        {!loading && (
          <ul className="divide-y divide-slate-100">
            {data?.items.map((item) => (
              <li key={item.id}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => open(item)}
                  onKeyDown={(event) => event.key === 'Enter' && open(item)}
                  className={`flex cursor-pointer items-start gap-3 px-2 py-3 transition hover:bg-slate-50 ${
                    item.is_read ? '' : 'bg-sky-50/50'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-900">{item.title}</p>
                    {item.body && (
                      <p className="mt-0.5 text-sm whitespace-pre-line text-slate-600">
                        {item.body}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-slate-500">
                      {TYPE_LABELS[item.type] ?? item.type} · {relativeTime(item.created_at)}
                      {item.actor_name && ` · by ${item.actor_name}`}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(event) => dismiss(event, item.id)}
                    aria-label="Dismiss"
                    className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-200 hover:text-slate-700"
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between text-sm text-slate-600">
          <span>
            Page {data.page} of {data.pages} · {data.total} total
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              disabled={page >= data.pages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
