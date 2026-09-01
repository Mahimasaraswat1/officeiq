/**
 * The employee's own requests: submit one, track the rest.
 *
 * Leave is the only type wired up so far, so the form is a leave form. When a
 * second type is registered this page gains a type picker and the form becomes
 * a switch — the list, the statuses and the withdraw flow do not change.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, EmptyState, Field, Input, Select, Spinner } from '../components/ui'
import { RequestRow } from '../components/RequestBits'
import ConfirmDialog from '../components/ConfirmDialog'
import { useToast } from '../components/Toast'

/**
 * Leave types, matching the handbook the assistant quotes.
 *
 * Unpaid carries no balance — it is the way forward when a paid balance runs
 * out, which is what the server's refusal message points at.
 */
const LEAVE_KINDS = [
  { value: 'annual', label: 'Annual leave' },
  { value: 'sick', label: 'Sick leave' },
  { value: 'unpaid', label: 'Unpaid leave' },
]

const KIND_LABEL = Object.fromEntries(LEAVE_KINDS.map((k) => [k.value, k.label]))

/**
 * One leave type's standing.
 *
 * The bar is the used proportion, so "how much is left" is legible without
 * reading the numbers — but the numbers are there too, because a bar alone
 * cannot tell you whether 3 days is enough for the trip you are planning.
 */
function BalanceCard({ balance }) {
  const { entitled_days, carried_forward_days, used_days, available_days } = balance
  const total = entitled_days + carried_forward_days
  const usedPercent = total > 0 ? Math.min(100, (used_days / total) * 100) : 0
  const low = total > 0 && available_days <= total * 0.15

  return (
    <div className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-navy-100">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-navy-900">
          {KIND_LABEL[balance.leave_kind] ?? balance.leave_kind}
        </p>
        <p className="text-xs text-navy-500">{balance.year}</p>
      </div>

      <p className="mt-2">
        <span
          className={`text-3xl font-bold tabular-nums ${low ? 'text-amber-600' : 'text-navy-900'}`}
        >
          {available_days}
        </span>
        <span className="ml-1 text-sm text-navy-500">of {total} days left</span>
      </p>

      <div
        className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-navy-100"
        role="img"
        aria-label={`${used_days} of ${total} days used`}
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            low ? 'bg-amber-500' : 'bg-accent-600'
          }`}
          style={{ width: `${usedPercent}%` }}
        />
      </div>

      <p className="mt-2 text-xs text-navy-500">
        {used_days} used
        {carried_forward_days > 0 && ` · ${carried_forward_days} carried forward`}
      </p>
    </div>
  )
}

const todayISO = () => new Date().toISOString().slice(0, 10)

const BLANK = {
  leave_kind: 'annual',
  start_date: '',
  end_date: '',
  half_day: false,
  reason: '',
}

function LeaveForm({ onSubmit, onCancel, busy, balances }) {
  const [form, setForm] = useState(BLANK)
  const set = (key) => (event) =>
    setForm((f) => ({ ...f, [key]: event.target.value }))

  // A half day is one date by definition, so tying the two fields together
  // stops the server rejecting something the form let the user build.
  const setHalfDay = (event) => {
    const half_day = event.target.checked
    setForm((f) => ({ ...f, half_day, end_date: half_day ? f.start_date : f.end_date }))
  }
  const setStart = (event) => {
    const start_date = event.target.value
    setForm((f) => ({
      ...f,
      start_date,
      end_date: f.half_day || !f.end_date || f.end_date < start_date ? start_date : f.end_date,
    }))
  }

  // Unpaid has no balance row, so this is undefined for it — and the
  // "available" line correctly disappears rather than showing zero.
  const selected = balances?.find((b) => b.leave_kind === form.leave_kind)

  const days = useMemo(() => {
    if (form.half_day) return 0.5
    if (!form.start_date || !form.end_date) return null
    const ms = new Date(form.end_date) - new Date(form.start_date)
    return ms < 0 ? null : ms / 86_400_000 + 1
  }, [form.start_date, form.end_date, form.half_day])

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit({ type: 'leave', payload: { ...form } })
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Leave type">
          <Select value={form.leave_kind} onChange={set('leave_kind')}>
            {LEAVE_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Half day only" hint="A half day covers a single date.">
          <label className="flex h-10 items-center gap-2 text-sm text-navy-700">
            <input
              type="checkbox"
              checked={form.half_day}
              onChange={setHalfDay}
              className="h-4 w-4 rounded border-navy-300 text-accent-600"
            />
            Just half a day
          </label>
        </Field>

        <Field label="First day">
          <Input
            type="date"
            value={form.start_date}
            onChange={setStart}
            min={todayISO()}
            required
          />
        </Field>

        <Field label="Last day">
          <Input
            type="date"
            value={form.end_date}
            onChange={set('end_date')}
            min={form.start_date || todayISO()}
            disabled={form.half_day}
            required
          />
        </Field>
      </div>

      <Field label="Reason" hint="Your approver sees this.">
        <Input
          value={form.reason}
          onChange={set('reason')}
          required
          maxLength={1000}
          placeholder="Family wedding"
        />
      </Field>

      {days != null && (
        <p className="text-sm text-navy-600">
          This request covers <strong>{days}</strong> {days === 1 ? 'day' : 'days'}
          {selected && (
            <>
              {' '}· <strong>{selected.available_days}</strong> day
              {selected.available_days === 1 ? '' : 's'} available
              {days > selected.available_days && (
                <span className="font-semibold text-amber-700">
                  {' '}— more than you have left. Unpaid leave is always available.
                </span>
              )}
            </>
          )}
          .
        </p>
      )}

      <div className="flex gap-2">
        <Button type="submit" loading={busy}>
          Submit request
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

export default function MyRequests() {
  const toast = useToast()
  const [requests, setRequests] = useState([])
  const [balances, setBalances] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [noRecord, setNoRecord] = useState(false)
  const [adding, setAdding] = useState(false)
  const [withdrawing, setWithdrawing] = useState(null)

  const load = useCallback(async () => {
    try {
      const [rows, balance] = await Promise.all([api.myRequests(), api.myLeaveBalance()])
      setRequests(rows)
      setBalances(balance.balances)
      setError('')
    } catch (err) {
      // An admin account with no employee profile has nothing to request
      // against. That is a normal state for this project's seeded admin, not
      // an error worth painting red.
      if (err.status === 404) setNoRecord(true)
      else setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn, message) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      toast.success(message)
      setAdding(false)
      setWithdrawing(null)
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  const open = requests.filter((r) => r.status === 'pending')
  const settled = requests.filter((r) => r.status !== 'pending')

  if (loading) return <Spinner />

  if (noRecord) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy-900">My requests</h1>
        </div>
        <Card>
          <EmptyState icon="👤" title="No employee profile on this account">
            Requests are submitted against an employee record, and this login is not
            linked to one. Ask HR to link it if you need to raise a request yourself.
          </EmptyState>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">My requests</h1>
        <p className="mt-1 text-sm text-navy-500">
          Ask for leave and follow what happened to it. Anything still pending can be
          withdrawn, and so can approved leave that has not started yet.
        </p>
      </div>

      <Alert>{error}</Alert>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {balances.map((balance) => (
          <BalanceCard key={balance.leave_kind} balance={balance} />
        ))}
        <div className="rounded-2xl bg-navy-50 p-4 ring-1 ring-navy-100">
          <p className="text-sm font-semibold text-navy-900">Unpaid leave</p>
          <p className="mt-2 text-sm text-navy-600">
            Always available. Use it when a paid balance is exhausted — it needs the
            same approval, but draws down nothing.
          </p>
          <p className="mt-3 text-xs text-navy-500">
            {open.length} request{open.length === 1 ? '' : 's'} awaiting a decision
          </p>
        </div>
      </div>

      {!adding && <Button onClick={() => setAdding(true)}>Request leave</Button>}

      {adding && (
        <Card title="Request leave">
          <LeaveForm
            busy={busy}
            balances={balances}
            onCancel={() => {
              setAdding(false)
              setError('')
            }}
            onSubmit={(body) => act(() => api.submitRequest(body), 'Request submitted.')}
          />
        </Card>
      )}

      <Card title="Awaiting a decision">
        {open.length === 0 ? (
          <EmptyState icon="📋" title="Nothing pending">
            Anything you submit shows up here until it is approved or rejected.
          </EmptyState>
        ) : (
          <ul>
            {open.map((r) => (
              <RequestRow key={r.id} request={r} onCancel={setWithdrawing} />
            ))}
          </ul>
        )}
      </Card>

      {settled.length > 0 && (
        <Card title="Decided">
          <ul>
            {settled.map((r) => (
              // onCancel is passed here too: approved leave that has not
              // started yet is still withdrawable, and the row decides whether
              // to offer it from can_cancel. Omitting the handler made the
              // feature unreachable no matter what the server said.
              <RequestRow key={r.id} request={r} onCancel={setWithdrawing} />
            ))}
          </ul>
        </Card>
      )}

      {withdrawing && (
        <ConfirmDialog
          title="Withdraw this request?"
          confirmLabel="Withdraw"
          tone="danger"
          busy={busy}
          onCancel={() => setWithdrawing(null)}
          onConfirm={() =>
            act(() => api.cancelRequest(withdrawing.id), 'Request withdrawn.')
          }
        >
          {withdrawing.summary}
          {withdrawing.status === 'approved'
            ? ' — the days go back onto your balance. This cannot be undone, but you can submit a new request afterwards.'
            : ' — this cannot be undone, but you can submit a new request afterwards.'}
        </ConfirmDialog>
      )}
    </div>
  )
}
