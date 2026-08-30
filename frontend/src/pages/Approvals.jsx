/**
 * The approval queue.
 *
 * Oldest first: the longest wait is the most urgent, and a queue sorted newest
 * first quietly starves the requests that have been sitting longest.
 *
 * Rejection opens a dialog rather than approving inline, because the server
 * requires a reason — and the reason is the whole point of a rejection.
 */

import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, EmptyState, Field, Input, Spinner, Stat } from '../components/ui'
import { RequestRow } from '../components/RequestBits'
import { useToast } from '../components/Toast'

const FILTERS = [
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'cancelled', label: 'Withdrawn' },
  { value: '', label: 'All' },
]

/** Rejection needs a reason, so it gets its own small dialog. */
function RejectDialog({ request, busy, onCancel, onConfirm }) {
  const [note, setNote] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Reject request"
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-card-hover"
      >
        <h2 className="text-lg font-bold text-navy-900">Reject this request?</h2>
        <p className="mt-1 text-sm text-navy-500">
          {request.employee_name} · {request.summary}
        </p>
        <form
          className="mt-4 space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            onConfirm(note.trim())
          }}
        >
          <Field label="Reason" hint="The employee sees this, so say what would change your mind.">
            <Input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              required
              autoFocus
              maxLength={2000}
              placeholder="Team is short-staffed that week"
            />
          </Field>
          <div className="flex gap-2">
            <Button type="submit" variant="danger" loading={busy} disabled={!note.trim()}>
              Reject
            </Button>
            <Button type="button" variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Approvals() {
  const toast = useToast()
  const [status, setStatus] = useState('pending')
  const [rows, setRows] = useState([])
  const [counts, setCounts] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [rejecting, setRejecting] = useState(null)

  const load = useCallback(async () => {
    try {
      const [queue, countRow] = await Promise.all([
        api.requestQueue(status ? { status } : undefined),
        api.requestCounts(),
      ])
      setRows(queue)
      setCounts(countRow)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn, message) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      toast.success(message)
      setRejecting(null)
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">Approvals</h1>
        <p className="mt-1 text-sm text-navy-500">
          Requests waiting on a decision, longest wait first. You cannot decide your own
          request — an admin reviews those.
        </p>
      </div>

      <Alert>{error}</Alert>

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Pending" value={counts?.pending ?? 0} />
        <Stat label="Approved" value={counts?.approved ?? 0} />
        <Stat label="Rejected" value={counts?.rejected ?? 0} />
        <Stat label="Withdrawn" value={counts?.cancelled ?? 0} />
      </dl>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f.value || 'all'}
            type="button"
            aria-pressed={status === f.value}
            onClick={() => {
              setLoading(true)
              setStatus(f.value)
            }}
            className={`rounded-xl px-3 py-1.5 text-sm font-medium transition ${
              status === f.value
                ? 'bg-accent-600 text-white'
                : 'bg-white text-navy-700 ring-1 ring-navy-200 hover:bg-navy-50'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <Card>
        {rows.length === 0 ? (
          <EmptyState icon="✅" title="Nothing here">
            {status === 'pending'
              ? 'No requests are waiting on a decision.'
              : 'No requests with that status yet.'}
          </EmptyState>
        ) : (
          <ul>
            {rows.map((r) => (
              <RequestRow
                key={r.id}
                request={r}
                showEmployee
                onApprove={(req) =>
                  act(() => api.approveRequest(req.id), `${req.request_code} approved.`)
                }
                onReject={setRejecting}
              />
            ))}
          </ul>
        )}
      </Card>

      {rejecting && (
        <RejectDialog
          request={rejecting}
          busy={busy}
          onCancel={() => setRejecting(null)}
          onConfirm={(note) =>
            act(
              () => api.rejectRequest(rejecting.id, note),
              `${rejecting.request_code} rejected.`,
            )
          }
        />
      )}
    </div>
  )
}
