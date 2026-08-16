import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button } from './ui'

const MIN_REASON_LENGTH = 10

/** HR approve/reject controls for a single document (PRD A.7.4). */
export default function DocumentReviewActions({ document, onReviewed }) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const decided = document.status === 'approved' || document.status === 'rejected'
  const tooEarly = document.status === 'uploaded' || document.status === 'processing'

  const run = async (fn) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      setRejecting(false)
      setReason('')
      onReviewed?.()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  if (tooEarly) {
    return (
      <p className="text-xs text-slate-500">
        Extraction is still running — review becomes available once it finishes.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <Alert>{error}</Alert>

      {decided && (
        <div
          className={`rounded-md px-3 py-2 text-sm ring-1 ${
            document.status === 'approved'
              ? 'bg-emerald-50 text-emerald-800 ring-emerald-200'
              : 'bg-red-50 text-red-800 ring-red-200'
          }`}
        >
          <p className="font-medium">
            {document.status === 'approved' ? 'Approved' : 'Rejected'}
            {document.reviewed_at &&
              ` on ${new Date(document.reviewed_at).toLocaleString()}`}
          </p>
          {document.rejection_reason && (
            <p className="mt-1 whitespace-pre-line">{document.rejection_reason}</p>
          )}
        </div>
      )}

      {!rejecting ? (
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={busy || document.status === 'approved'}
            onClick={() => run(() => api.approveDocument(document.id))}
          >
            Approve
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => setRejecting(true)}
          >
            {document.status === 'rejected' ? 'Change reason' : 'Reject'}
          </Button>
        </div>
      ) : (
        <div className="space-y-2 rounded-md bg-red-50 p-3 ring-1 ring-red-200">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-red-900">
              Why is this being rejected?
            </span>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              autoFocus
              placeholder="e.g. The Aadhaar number is unreadable — please upload a sharper scan."
              className="w-full rounded-md border-0 px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-red-300 focus:ring-2 focus:ring-inset focus:ring-red-600"
            />
          </label>
          <p className="text-xs text-red-700">
            The employee sees this message, so say what they need to fix.
            {reason.trim().length < MIN_REASON_LENGTH &&
              ` (${MIN_REASON_LENGTH - reason.trim().length} more characters needed)`}
          </p>
          <div className="flex gap-2">
            <Button
              variant="danger"
              loading={busy}
              disabled={reason.trim().length < MIN_REASON_LENGTH}
              onClick={() => run(() => api.rejectDocument(document.id, reason.trim()))}
            >
              Confirm rejection
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setRejecting(false)
                setReason('')
                setError('')
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
