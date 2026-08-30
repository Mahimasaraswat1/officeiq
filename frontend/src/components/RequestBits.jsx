/**
 * Pieces shared by the employee's request list and the approval queue.
 *
 * Both screens render the same rows and must agree on what a status means, so
 * the chip and the row live here rather than being written twice.
 */

import { Button } from './ui'

export const STATUS_CHIP = {
  pending: 'bg-amber-50 text-amber-800 ring-amber-200',
  approved: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  rejected: 'bg-red-50 text-red-700 ring-red-200',
  cancelled: 'bg-navy-100 text-navy-600 ring-navy-200',
}

const STATUS_LABEL = {
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  cancelled: 'Withdrawn',
}

export function StatusChip({ status }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${
        STATUS_CHIP[status] ?? STATUS_CHIP.cancelled
      }`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

export const formatWhen = (iso) =>
  new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

/**
 * One request.
 *
 * `showEmployee` switches it between the two audiences: the employee already
 * knows whose request it is, the approver needs the name first.
 *
 * Which actions appear comes from can_decide/can_cancel on the row itself. The
 * server owns the self-approval rule; re-deriving it here would let the two
 * drift and show HR a button that always 403s.
 */
export function RequestRow({ request, showEmployee = false, onApprove, onReject, onCancel }) {
  const { payload = {} } = request
  return (
    <li className="border-b border-navy-100 py-4 last:border-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {showEmployee && (
              <span className="font-semibold text-navy-900">{request.employee_name}</span>
            )}
            <span className={showEmployee ? 'text-navy-600' : 'font-semibold text-navy-900'}>
              {request.summary}
            </span>
            <StatusChip status={request.status} />
          </div>

          <p className="mt-1 text-sm text-navy-500">
            <span className="font-mono text-xs">{request.request_code}</span>
            {' · submitted '}
            {formatWhen(request.submitted_at)}
            {showEmployee && ` · ${request.employee_code}`}
          </p>

          {payload.reason && (
            <p className="mt-2 rounded-lg bg-navy-50 px-3 py-2 text-sm text-navy-700">
              {payload.reason}
            </p>
          )}

          {request.decision_note && (
            <p className="mt-2 text-sm text-navy-600">
              <span className="font-semibold">
                {request.status === 'rejected' ? 'Reason' : 'Note'}:
              </span>{' '}
              {request.decision_note}
            </p>
          )}

          {request.decided_at && (
            <p className="mt-1 text-xs text-navy-400">
              {STATUS_LABEL[request.status]} by {request.decided_by_name ?? 'HR'} on{' '}
              {formatWhen(request.decided_at)}
            </p>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          {request.can_decide && (
            <>
              <Button className="px-2.5 py-1.5 text-xs" onClick={() => onApprove(request)}>
                Approve
              </Button>
              <Button
                variant="secondary"
                className="px-2.5 py-1.5 text-xs"
                onClick={() => onReject(request)}
              >
                Reject
              </Button>
            </>
          )}
          {request.can_cancel && onCancel && (
            <Button
              variant="secondary"
              className="px-2.5 py-1.5 text-xs"
              onClick={() => onCancel(request)}
            >
              Withdraw
            </Button>
          )}
          {/* An approver's own request: say why there is no button, rather than
              leaving a gap that reads as a bug. */}
          {request.status === 'pending' && !request.can_decide && showEmployee && (
            <span className="text-xs text-navy-400">Awaiting an admin</span>
          )}
        </div>
      </div>
    </li>
  )
}
