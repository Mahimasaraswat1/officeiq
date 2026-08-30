/**
 * Company holiday calendar.
 *
 * One page for both audiences: everyone reads it, HR and Admin also edit it.
 * Rather than build a separate admin screen, the edit affordances appear inline
 * for the roles that have them — the list is the same list, so HR sees exactly
 * what an employee sees.
 *
 * The "upcoming" split is driven by `days_until`/`is_past` from the server, not
 * by comparing dates in the browser. A client clock in another timezone would
 * otherwise disagree with the API about which holidays have passed.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { Alert, Button, Card, EmptyState, Field, Input, Select, Spinner, Stat } from '../components/ui'
import ConfirmDialog from '../components/ConfirmDialog'
import { useToast } from '../components/Toast'

const TYPE_LABEL = {
  public: 'Public holiday',
  restricted: 'Optional',
  company: 'Company',
}

/**
 * Chip styling per holiday type.
 *
 * Optional holidays are the ones people misread — they are not automatic days
 * off — so they carry the only warm tone on the page, and the label says
 * "Optional" rather than relying on colour alone.
 */
const TYPE_CHIP = {
  public: 'bg-accent-50 text-accent-700 ring-accent-100',
  restricted: 'bg-amber-50 text-amber-800 ring-amber-200',
  company: 'bg-navy-100 text-navy-700 ring-navy-200',
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const formatDate = (iso) => {
  const [y, m, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[m - 1].slice(0, 3)} ${y}`
}

const monthOf = (iso) => Number(iso.split('-')[1]) - 1

/** "in 3 days" / "Today" / "Tomorrow" — the countdown people actually want. */
function countdown(days) {
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days < 7) return `in ${days} days`
  if (days < 14) return 'next week'
  return `in ${Math.round(days / 7)} weeks`
}

function TypeChip({ type }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${
        TYPE_CHIP[type] ?? TYPE_CHIP.company
      }`}
    >
      {TYPE_LABEL[type] ?? type}
    </span>
  )
}

/** The single next holiday, called out above the list. */
function NextUp({ holiday }) {
  if (!holiday) return null
  return (
    <div className="rounded-2xl bg-navy-900 px-5 py-4 text-white shadow-card">
      <p className="text-xs font-semibold tracking-wide text-navy-300 uppercase">Next holiday</p>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-xl font-bold tracking-tight">{holiday.name}</span>
        <span className="text-sm text-navy-200">
          {holiday.weekday}, {formatDate(holiday.holiday_date)}
        </span>
      </div>
      <p className="mt-1 text-sm font-medium text-accent-300">
        {countdown(holiday.days_until)}
      </p>
    </div>
  )
}

function HolidayRow({ holiday, canManage, onEdit, onDelete }) {
  const past = holiday.is_past
  return (
    <li
      className={`flex items-center gap-4 border-b border-navy-100 py-3 last:border-0 ${
        past ? 'opacity-55' : ''
      }`}
    >
      {/* Date block: the thing being scanned for, so it leads. */}
      <div
        className={`flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-xl ${
          past ? 'bg-navy-50 text-navy-500' : 'bg-accent-50 text-accent-700'
        }`}
        aria-hidden="true"
      >
        <span className="text-base leading-none font-bold">
          {Number(holiday.holiday_date.split('-')[2])}
        </span>
        <span className="mt-0.5 text-[10px] font-semibold tracking-wide uppercase">
          {MONTHS[monthOf(holiday.holiday_date)].slice(0, 3)}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-semibold text-navy-900">{holiday.name}</p>
          <TypeChip type={holiday.type} />
          {!holiday.is_active && (
            <span className="rounded-full bg-navy-100 px-2 py-0.5 text-xs font-semibold text-navy-600">
              Removed
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-navy-500">
          {holiday.weekday}
          {holiday.description ? ` · ${holiday.description}` : ''}
        </p>
      </div>

      {!past && holiday.days_until != null && (
        <span className="hidden shrink-0 text-sm font-medium text-navy-500 sm:block">
          {countdown(holiday.days_until)}
        </span>
      )}

      {canManage && holiday.is_active && (
        <div className="flex shrink-0 gap-1">
          <Button variant="secondary" className="px-2.5 py-1.5 text-xs" onClick={() => onEdit(holiday)}>
            Edit
          </Button>
          <Button variant="secondary" className="px-2.5 py-1.5 text-xs" onClick={() => onDelete(holiday)}>
            Remove
          </Button>
        </div>
      )}
    </li>
  )
}

const BLANK = { name: '', holiday_date: '', type: 'public', description: '' }

/** Add/edit form. Shown inline rather than in a modal — it is four fields. */
function HolidayForm({ initial, onSave, onCancel, busy }) {
  const [form, setForm] = useState(() =>
    initial
      ? {
          name: initial.name,
          holiday_date: initial.holiday_date,
          type: initial.type,
          description: initial.description ?? '',
        }
      : BLANK,
  )
  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }))

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault()
        onSave({ ...form, description: form.description.trim() || null })
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Holiday name">
          <Input
            value={form.name}
            onChange={set('name')}
            required
            maxLength={120}
            placeholder="Diwali"
            autoFocus
          />
        </Field>
        <Field label="Date">
          <Input type="date" value={form.holiday_date} onChange={set('holiday_date')} required />
        </Field>
        <Field
          label="Type"
          hint="Optional holidays are listed but not automatic days off."
        >
          <Select value={form.type} onChange={set('type')}>
            <option value="public">Public holiday</option>
            <option value="restricted">Optional</option>
            <option value="company">Company</option>
          </Select>
        </Field>
        <Field label="Note (optional)">
          <Input
            value={form.description}
            onChange={set('description')}
            maxLength={2000}
            placeholder="Festival of lights"
          />
        </Field>
      </div>
      <div className="flex gap-2">
        <Button type="submit" loading={busy}>
          {initial ? 'Save changes' : 'Add holiday'}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

export default function Holidays() {
  const { user } = useAuth()
  const toast = useToast()
  const canManage = user?.role === 'admin' || user?.role === 'hr'

  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState(currentYear)
  const [holidays, setHolidays] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState(null)
  const [removing, setRemoving] = useState(null)

  const load = useCallback(async () => {
    try {
      const [rows, summaryRow] = await Promise.all([
        api.listHolidays({ year }),
        api.holidaySummary({ year }),
      ])
      setHolidays(rows)
      setSummary(summaryRow)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [year])

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
      setEditing(null)
      setRemoving(null)
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  const upcoming = useMemo(() => holidays.filter((h) => !h.is_past), [holidays])
  const past = useMemo(() => holidays.filter((h) => h.is_past), [holidays])
  const nextUp = year === currentYear ? upcoming[0] : null

  // A couple of years either side covers planning without a date picker.
  const years = [currentYear - 1, currentYear, currentYear + 1]

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy-900">Holiday calendar</h1>
          <p className="mt-1 text-sm text-navy-500">
            Company holidays for the year. Optional holidays are listed but are not
            automatic days off — check with your manager before planning around one.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="holiday-year" className="text-sm font-medium text-navy-600">
            Year
          </label>
          <Select
            id="holiday-year"
            value={year}
            onChange={(event) => {
              setLoading(true)
              setYear(Number(event.target.value))
            }}
            className="w-28"
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <Alert>{error}</Alert>

      <NextUp holiday={nextUp} />

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Holidays this year" value={summary?.total ?? 0} />
        <Stat label="Still to come" value={summary?.upcoming ?? 0} />
        <Stat label="Public" value={summary?.public ?? 0} />
        <Stat label="Optional" value={summary?.restricted ?? 0} />
      </dl>

      {canManage && !adding && !editing && (
        <Button onClick={() => setAdding(true)}>Add holiday</Button>
      )}

      {canManage && (adding || editing) && (
        <Card title={editing ? `Edit ${editing.name}` : 'Add a holiday'}>
          <HolidayForm
            key={editing?.id ?? 'new'}
            initial={editing}
            busy={busy}
            onCancel={() => {
              setAdding(false)
              setEditing(null)
              setError('')
            }}
            onSave={(payload) =>
              editing
                ? act(() => api.updateHoliday(editing.id, payload), 'Holiday updated.')
                : act(() => api.createHoliday(payload), 'Holiday added.')
            }
          />
        </Card>
      )}

      <Card title={`Upcoming${year === currentYear ? '' : ` in ${year}`}`}>
        {upcoming.length === 0 ? (
          <EmptyState icon="📅" title="Nothing left this year">
            {canManage
              ? 'Add the next year’s holidays so employees can plan ahead.'
              : 'Check back when HR publishes the next calendar.'}
          </EmptyState>
        ) : (
          <ul>
            {upcoming.map((holiday) => (
              <HolidayRow
                key={holiday.id}
                holiday={holiday}
                canManage={canManage}
                onEdit={setEditing}
                onDelete={setRemoving}
              />
            ))}
          </ul>
        )}
      </Card>

      {past.length > 0 && (
        <Card title="Earlier this year">
          <ul>
            {past.map((holiday) => (
              <HolidayRow
                key={holiday.id}
                holiday={holiday}
                canManage={canManage}
                onEdit={setEditing}
                onDelete={setRemoving}
              />
            ))}
          </ul>
        </Card>
      )}

      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.name}?`}
          confirmLabel="Remove"
          tone="danger"
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={() =>
            act(() => api.deleteHoliday(removing.id), `${removing.name} removed.`)
          }
        >
          It disappears from the calendar for everyone. Past calendars keep their record of
          it, so this does not rewrite history.
        </ConfirmDialog>
      )}
    </div>
  )
}
