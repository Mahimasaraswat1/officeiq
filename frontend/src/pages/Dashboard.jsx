import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Alert, Button, Card, EmptyState, Input, Select, Spinner, StatusBadge } from '../components/ui'
import DataTable from '../components/DataTable'
import StatCard from '../components/StatCard'
import PipelineBar from '../components/PipelineBar'
import TeamOverview from '../components/TeamOverview'
import { CATEGORY_LABEL } from '../components/TaskList'
import ProgressRing from '../components/ProgressRing'
import { useToast } from '../components/Toast'
import { TrendChart } from '../components/charts'

const ONBOARDING_STEPS = [
  { key: 'invited', label: 'Invitation sent' },
  { key: 'registered', label: 'Account activated' },
  { key: 'documents_pending', label: 'Documents requested', phase: 'Phase 2' },
  { key: 'documents_submitted', label: 'Documents uploaded', phase: 'Phase 2' },
  { key: 'under_review', label: 'HR review', phase: 'Phase 3' },
  { key: 'tasks_assigned', label: 'Tasks & training assigned', phase: 'Phase 4' },
  { key: 'complete', label: 'Onboarding complete' },
]

const WINDOWS = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
]

// Ordered onboarding stages. Position in this list drives the progress bar in
// the new-hires table — it is stage progress, not task completion, because
// task percentages would need one request per row.
const STAGE_ORDER = [
  'invited',
  'registered',
  'documents_pending',
  'documents_submitted',
  'under_review',
  'tasks_assigned',
  'complete',
]

const STAGE_LABEL = {
  invited: 'Invited',
  registered: 'Registered',
  documents_pending: 'Documents pending',
  documents_submitted: 'Documents submitted',
  under_review: 'Under review',
  tasks_assigned: 'Tasks assigned',
  complete: 'Complete',
  rejected: 'Rejected',
}

const stageProgress = (status) => {
  const index = STAGE_ORDER.indexOf(status)
  if (index < 0) return 0
  return Math.round((index / (STAGE_ORDER.length - 1)) * 100)
}

const ICONS = {
  newHires: <path d="M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm-6 6.5C4 14 6.7 12 10 12s6 2 6 4.5V18H4v-1.5z" />,
  completed: <path d="M10 2a8 8 0 100 16 8 8 0 000-16zm3.9 6.1l-4.4 4.4a1 1 0 01-1.4 0L6 10.4l1.4-1.4 1.4 1.4 3.7-3.7 1.4 1.4z" />,
  clock: (
    <>
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M10 2a8 8 0 100 16 8 8 0 000-16zm0 1.6a6.4 6.4 0 110 12.8 6.4 6.4 0 010-12.8z"
      />
      <path d="M9.25 5.5h1.5v4.3l2.9 1.7-.75 1.3-3.65-2.1V5.5z" />
    </>
  ),
  overdue: <path d="M10 1.5l8.5 15H1.5l8.5-15zM9 7v5h2V7H9zm0 6.5v2h2v-2H9z" />,
}

/**
 * Percentage change between the two halves of a daily series.
 *
 * Returns null rather than a number when there is no honest comparison to
 * make — an empty previous period would otherwise render as a meaningless
 * "+100%" or a division by zero.
 */
function trendFromSeries(points, key) {
  if (!points || points.length < 4) return null
  const half = Math.floor(points.length / 2)
  const sum = (slice) => slice.reduce((total, point) => total + (point[key] ?? 0), 0)
  const previous = sum(points.slice(0, half))
  const current = sum(points.slice(half))
  // A zero baseline has no percentage change — "+100%" against nothing is
  // fiction. Say the activity is new instead.
  if (previous === 0) return current > 0 ? 'new' : null
  return Math.round(((current - previous) / previous) * 100)
}

/**
 * Trim a queue for display while preserving its true total.
 *
 * The endpoint is queried with a high limit so the pipeline can identify
 * distinct people with overdue tasks; the on-screen lists stay short, and
 * AttentionSection still reports "and N more" from the untouched total.
 */
const DISPLAY_LIMIT = 5
const capped = (group) => ({ ...group, items: group.items.slice(0, DISPLAY_LIMIT) })

function HrDashboard() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      api.dashboardSummary({ days }),
      api.dashboardFunnel(),
      // Twice the window, so the series can be split into this period and the
      // one before it to derive a real trend without a new backend endpoint.
      api.dashboardTrends({ days: days * 2 }),
      // The cap is the endpoint's maximum; it bounds how many distinct people
      // with overdue tasks the pipeline can identify. See the footnote below.
      api.dashboardAttention({ limit: 50 }),
      api.dashboardDepartments(),
    ])
      .then(([summary, funnel, trends, attention, departments]) => {
        if (!cancelled) setData({ summary, funnel, trends, attention, departments })
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [days])

  if (loading && !data) return <Spinner label="Loading your dashboard…" />
  if (error) return <Alert>{error}</Alert>
  if (!data) return null

  const { summary, funnel, trends, attention, departments } = data

  const stageCount = (key) =>
    funnel.stages.find((stage) => stage.status === key)?.count ?? 0

  // People with at least one overdue task, not the count of overdue tasks —
  // a person with three late items is one person in the pipeline.
  const overdueEmployeeIds = new Set(
    attention.overdue_tasks.items.map((item) => item.employee_id),
  )
  const overdueCapped =
    attention.overdue_tasks.total > attention.overdue_tasks.items.length

  const notStarted = stageCount('invited')
  const completed = stageCount('complete')
  const inProgressStages = [
    'registered',
    'documents_pending',
    'documents_submitted',
    'under_review',
    'tasks_assigned',
  ].reduce((total, key) => total + stageCount(key), 0)
  // Carved out of in-progress so the four segments still partition the total.
  const overduePeople = Math.min(overdueEmployeeIds.size, inProgressStages)

  const newHires = trends.points
    .slice(Math.floor(trends.points.length / 2))
    .reduce((total, point) => total + point.profiles_created, 0)

  const totalAttention =
    attention.documents_pending_review.total +
    attention.failed_verifications.total +
    attention.overdue_tasks.total +
    attention.stalled_onboardings.total

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <Select
          value={days}
          onChange={(event) => setDays(Number(event.target.value))}
          className="max-w-44 rounded-xl"
          aria-label="Reporting window"
        >
          {WINDOWS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>

      {/* --- Four headline stats -------------------------------------- */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          tone="accent"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.newHires}</svg>}
          value={newHires}
          label={`New hires · last ${days} days`}
          trend={trendFromSeries(trends.points, 'profiles_created')}
        />
        <StatCard
          tone="emerald"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.completed}</svg>}
          value={summary.completed_in_window}
          label={`Completed onboardings · last ${days} days`}
          trend={trendFromSeries(trends.points, 'completions')}
        />
        <StatCard
          tone="navy"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.clock}</svg>}
          value={
            summary.average_days_to_complete == null
              ? '—'
              : `${summary.average_days_to_complete}d`
          }
          label="Avg. onboarding time"
          // No historical series exists for this metric, so no trend is shown
          // rather than a fabricated one.
          hint={summary.average_days_to_complete == null ? 'No completions yet' : undefined}
        />
        <StatCard
          tone="red"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.overdue}</svg>}
          value={summary.tasks_overdue}
          label="Overdue tasks"
          hint={summary.tasks_open > 0 ? `${summary.tasks_open} open in total` : undefined}
        />
      </div>

      {/* --- Pipeline -------------------------------------------------- */}
      <section className="rounded-2xl bg-white p-6 shadow-card ring-1 ring-navy-100/70">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-bold tracking-tight text-navy-900">
              Onboarding pipeline
            </h2>
            <p className="text-sm text-navy-500">
              Where all {funnel.total} {funnel.total === 1 ? 'person' : 'people'} stand today.
            </p>
          </div>
          <Link
            to="/employees"
            className="text-sm font-semibold text-accent-600 transition hover:text-accent-700"
          >
            View all →
          </Link>
        </div>

        <PipelineBar
          counts={{
            completed,
            in_progress: inProgressStages - overduePeople,
            overdue: overduePeople,
            not_started: notStarted,
          }}
          footnote={
            overdueCapped
              ? `Overdue counts people with at least one late task, identified from the ${attention.overdue_tasks.items.length} most urgent of ${attention.overdue_tasks.total} overdue tasks — so it may undercount.`
              : 'Overdue counts people with at least one late task, carved out of in progress so the bar totals everyone.'
          }
        />
      </section>

      {/* --- New hires ------------------------------------------------- */}
      <NewHiresTable />

      {/* --- Team overview --------------------------------------------- */}
      <TeamOverview />

      {/* --- Attention queue ------------------------------------------- */}
      <section className="rounded-2xl bg-white p-6 shadow-card ring-1 ring-navy-100/70">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-base font-bold tracking-tight text-navy-900">
            Needs attention{totalAttention ? ` (${totalAttention})` : ''}
          </h2>
        </div>

        {totalAttention === 0 ? (
          <EmptyState icon="✅" title="You are all caught up">
            No documents to review, failed checks, overdue tasks or stalled onboardings.
          </EmptyState>
        ) : (
          <div className="space-y-5">
            <AttentionSection
              title="Documents awaiting review"
              group={capped(attention.documents_pending_review)}
              render={(item) => ({
                key: item.document_id,
                to: `/employees/${item.employee_id}`,
                primary: `${item.employee_name} · ${item.document_type}`,
                secondary: `${item.original_filename} · waiting ${item.days_waiting} day${
                  item.days_waiting === 1 ? '' : 's'
                }`,
              })}
            />
            <AttentionSection
              title="Failed ID verifications"
              group={capped(attention.failed_verifications)}
              tone="danger"
              render={(item) => ({
                key: `${item.employee_id}-${item.occurred_at}`,
                to: `/employees/${item.employee_id}`,
                primary: `${item.employee_name} · ${item.check_type.toUpperCase()}`,
                secondary: item.message ?? item.reason_code,
              })}
            />
            <AttentionSection
              title="Overdue tasks"
              group={capped(attention.overdue_tasks)}
              tone="danger"
              render={(item) => ({
                key: item.task_id,
                to: `/employees/${item.employee_id}`,
                primary: `${item.title} — ${item.employee_name}`,
                secondary: `${item.days_overdue} day${
                  item.days_overdue === 1 ? '' : 's'
                } overdue${item.is_mandatory ? ' · mandatory' : ''}`,
              })}
            />
            <AttentionSection
              title="Stalled onboardings"
              group={capped(attention.stalled_onboardings)}
              render={(item) => ({
                key: item.employee_id,
                to: `/employees/${item.employee_id}`,
                primary: item.employee_name,
                secondary: `No movement for ${item.days_since_update} days`,
                badge: item.onboarding_status,
              })}
            />
          </div>
        )}
      </section>

      {/* --- Activity & departments ------------------------------------ */}
      <div>
        <h2 className="mb-3 text-base font-bold tracking-tight text-navy-900">
          Activity over the last {days} days
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          <TrendChart points={trends.points.slice(-days)} valueKey="profiles_created" label="Profiles created" />
          <TrendChart points={trends.points.slice(-days)} valueKey="documents_uploaded" label="Documents uploaded" />
          <TrendChart points={trends.points.slice(-days)} valueKey="questions_asked" label="Questions asked" />
        </div>
      </div>

      <section className="rounded-2xl bg-white p-6 shadow-card ring-1 ring-navy-100/70">
        <h2 className="mb-4 text-base font-bold tracking-tight text-navy-900">By department</h2>
        {departments.length === 0 ? (
          <EmptyState icon="🏢" title="No departments yet">
            Set a department on an employee profile and the breakdown appears here.
          </EmptyState>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-navy-500">
                <th className="pb-2 font-medium">Department</th>
                <th className="pb-2 text-right font-medium">In progress</th>
                <th className="pb-2 text-right font-medium">Complete</th>
                <th className="pb-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {departments.map((row) => (
                <tr key={row.department} className="border-t border-navy-100">
                  <td className="py-2 text-navy-900">{row.department}</td>
                  <td className="py-2 text-right tabular-nums text-navy-600">{row.in_progress}</td>
                  <td className="py-2 text-right tabular-nums text-navy-600">{row.complete}</td>
                  <td className="py-2 text-right font-semibold tabular-nums text-navy-900">
                    {row.total}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

/** Searchable, filterable list of employees with their stage progress. */
function NewHiresTable() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    // Debounced so typing fires one request rather than one per keystroke.
    const timer = setTimeout(() => {
      api
        .listEmployees({ search, onboarding_status: status, page, page_size: 8 })
        .then((result) => !cancelled && setData(result))
        .catch(() => !cancelled && setData(null))
        .finally(() => !cancelled && setLoading(false))
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [search, status, page])

  const columns = [
    {
      key: 'employee',
      header: 'New hire',
      primary: true,
      cell: (row) => (
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-navy-100 text-xs font-bold text-navy-700">
            {`${row.first_name?.[0] ?? ''}${row.last_name?.[0] ?? ''}`.toUpperCase()}
          </span>
          <div className="min-w-0">
            <Link
              to={`/employees/${row.id}`}
              className="block truncate font-semibold text-navy-900 hover:text-accent-600"
            >
              {row.first_name} {row.last_name}
            </Link>
            <span className="block truncate text-xs text-navy-500">{row.work_email}</span>
          </div>
        </div>
      ),
    },
    {
      key: 'department',
      header: 'Department',
      cell: (row) => row.department ?? '—',
      className: 'text-navy-600',
    },
    {
      key: 'progress',
      header: 'Progress',
      cell: (row) => {
        const pct = stageProgress(row.onboarding_status)
        return (
          <div className="flex items-center gap-2 sm:w-40">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-navy-100">
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{
                  width: `${pct}%`,
                  backgroundColor: pct === 100 ? '#059669' : '#2563eb',
                }}
              />
            </div>
            <span className="w-9 shrink-0 text-right text-xs font-semibold tabular-nums text-navy-700">
              {pct}%
            </span>
          </div>
        )
      },
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <StatusBadge status={row.onboarding_status} />,
    },
    {
      key: 'joining',
      header: 'Joining',
      cell: (row) => row.date_of_joining ?? '—',
      className: 'text-navy-600',
    },
  ]

  return (
    <section className="overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-navy-100/70">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-navy-100 p-5">
        <div>
          <h2 className="text-base font-bold tracking-tight text-navy-900">New hires</h2>
          <p className="text-sm text-navy-500">
            {data ? `${data.total} ${data.total === 1 ? 'person' : 'people'}` : 'Loading…'}
          </p>
        </div>
        <Link to="/employees/new">
          <Button className="shadow-card transition duration-200 hover:-translate-y-0.5 hover:shadow-card-hover">
            + Assign new onboarding
          </Button>
        </Link>
      </div>

      <div className="flex flex-col gap-3 border-b border-navy-100 p-5 sm:flex-row">
        <Input
          placeholder="Search by name, code or email…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          className="rounded-xl sm:max-w-xs"
        />
        <Select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value)
            setPage(1)
          }}
          className="rounded-xl sm:max-w-52"
          aria-label="Filter by onboarding status"
        >
          <option value="">All statuses</option>
          {[...STAGE_ORDER, 'rejected'].map((value) => (
            <option key={value} value={value}>
              {STAGE_LABEL[value]}
            </option>
          ))}
        </Select>
      </div>

      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        rowKey={(row) => row.id}
        loading={loading}
        skeletonRows={5}
        empty={
          search || status ? (
            <EmptyState icon="🔍" title="No matches">
              No new hires match these filters.
            </EmptyState>
          ) : (
            <EmptyState
              icon="👥"
              title="No employees yet"
              action={
                <Link to="/employees/new">
                  <Button>Assign new onboarding</Button>
                </Link>
              }
            >
              Create a profile and OfficeIQ emails an invitation to complete onboarding.
            </EmptyState>
          )
        }
      />

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between gap-3 border-t border-navy-100 p-4 text-sm">
          <span className="text-navy-500">
            Page {data.page} of {data.pages}
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
    </section>
  )
}

function AttentionSection({ title, group, render, tone }) {
  if (group.total === 0) return null
  const hidden = group.total - group.items.length

  return (
    <section>
      <h3 className="flex items-center gap-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        {title}
        <span
          className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${
            tone === 'danger' ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600'
          }`}
        >
          {group.total}
        </span>
      </h3>
      <ul className="mt-1 divide-y divide-slate-100">
        {group.items.map((item) => {
          const row = render(item)
          return (
            <li key={row.key} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <Link
                  to={row.to}
                  className="block truncate text-sm font-medium text-slate-900 hover:underline"
                >
                  {row.primary}
                </Link>
                {row.secondary && (
                  <p className="truncate text-xs text-slate-500">{row.secondary}</p>
                )}
              </div>
              {row.badge && <StatusBadge status={row.badge} />}
            </li>
          )
        })}
      </ul>
      {hidden > 0 && (
        // Say what the cap hid, so a long backlog never reads as a short one.
        <p className="mt-1 text-xs text-slate-500">and {hidden} more</p>
      )}
    </section>
  )
}

const CATEGORY_TONE = {
  task: 'bg-navy-100 text-navy-700',
  training: 'bg-indigo-100 text-indigo-800',
  document_checklist: 'bg-sky-100 text-sky-800',
  policy_acknowledgement: 'bg-violet-100 text-violet-800',
}

const isOpen = (task) => task.status === 'pending' || task.status === 'in_progress'

/** Overdue first, then soonest due, then undated — the order to work in. */
function byUrgency(a, b) {
  if (!a.due_date && !b.due_date) return 0
  if (!a.due_date) return 1
  if (!b.due_date) return -1
  return a.due_date < b.due_date ? -1 : 1
}

function EmployeeDashboard() {
  const [record, setRecord] = useState(null)
  const [tasks, setTasks] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(null)
  const toast = useToast()

  const load = useCallback(async () => {
    try {
      const [employee, myTasks] = await Promise.all([
        api.myEmployeeRecord(),
        // Tasks only exist after assignment, so an empty list is normal.
        api.myTasks().catch(() => []),
      ])
      setRecord(employee)
      setTasks(Array.isArray(myTasks) ? myTasks : (myTasks?.items ?? []))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Progress is derived from the task list this component already holds, so
  // ticking a box moves the ring immediately instead of waiting for a refetch.
  const closed = tasks.filter((t) => t.status === 'completed' || t.status === 'waived')
  const percent = tasks.length ? Math.round((closed.length / tasks.length) * 100) : 0
  const today = new Date().toISOString().slice(0, 10)
  const overdue = tasks.filter((t) => isOpen(t) && t.due_date && t.due_date < today)
  const openTasks = tasks.filter(isOpen).sort(byUrgency)
  const nextTask = openTasks[0]
  const allDone = tasks.length > 0 && closed.length === tasks.length
  const mandatoryLeft = tasks.filter((t) => t.is_mandatory && isOpen(t)).length

  const toggle = async (task, done) => {
    const previous = tasks
    setSaving(task.id)
    // Optimistic: the checkbox and the ring respond at once, and the list is
    // put back exactly as it was if the request fails.
    setTasks((current) =>
      current.map((row) =>
        row.id === task.id ? { ...row, status: done ? 'completed' : 'pending' } : row,
      ),
    )
    try {
      await api.updateTaskStatus(task.id, done ? 'completed' : 'pending')
    } catch (err) {
      setTasks(previous)
      toast.error(err.message)
    } finally {
      setSaving(null)
    }
  }

  if (loading) return <Spinner label="Loading your onboarding…" />
  if (error) return <Alert>{error}</Alert>
  if (!record) return null

  return (
    <div className="space-y-6">
      {/* --- Hero ------------------------------------------------------- */}
      <section
        className={`overflow-hidden rounded-2xl p-6 shadow-card ring-1 sm:p-8 ${
          allDone
            ? 'bg-gradient-to-br from-emerald-600 to-emerald-700 ring-emerald-700/20'
            : 'bg-white ring-navy-100/70'
        }`}
      >
        {allDone ? (
          <CelebrationHero name={record.first_name} total={tasks.length} />
        ) : (
          <div className="flex flex-col items-center gap-6 sm:flex-row sm:gap-8">
            <ProgressRing
              percent={percent}
              label={tasks.length ? `${closed.length} of ${tasks.length}` : 'No tasks yet'}
              tone={overdue.length ? 'red' : 'accent'}
            />

            <div className="min-w-0 flex-1 text-center sm:text-left">
              <h2 className="text-xl font-bold tracking-tight text-navy-900">
                {tasks.length === 0
                  ? 'Your checklist is on its way'
                  : 'Continue your onboarding'}
              </h2>

              {tasks.length === 0 ? (
                <p className="mt-1.5 text-sm text-navy-500">
                  HR assigns your tasks once your documents are approved. Nothing to do
                  right now.
                </p>
              ) : (
                <>
                  <p className="mt-1.5 text-sm text-navy-500">
                    {mandatoryLeft > 0
                      ? `${mandatoryLeft} mandatory item${mandatoryLeft === 1 ? '' : 's'} left before your onboarding can be signed off.`
                      : 'All mandatory items are done — the rest are optional.'}
                  </p>

                  {nextTask && (
                    <div className="mt-4 rounded-xl border border-navy-100 bg-navy-50/70 p-4 text-left">
                      <p className="text-xs font-semibold tracking-wide text-navy-500 uppercase">
                        Up next
                      </p>
                      <p className="mt-1 font-semibold text-navy-900">{nextTask.title}</p>
                      {nextTask.description && (
                        <p className="mt-0.5 line-clamp-2 text-sm text-navy-600">
                          {nextTask.description}
                        </p>
                      )}
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Button onClick={() => toggle(nextTask, true)} loading={saving === nextTask.id}>
                          Mark as done
                        </Button>
                        {nextTask.resource_url && (
                          <a
                            href={nextTask.resource_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-sm font-semibold text-accent-600 hover:text-accent-700"
                          >
                            Open resource →
                          </a>
                        )}
                        {nextTask.due_date && (
                          <span className="text-xs text-navy-500">
                            Due {nextTask.due_date}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </>
              )}

              {overdue.length > 0 && (
                <div
                  role="alert"
                  className="mt-4 flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200"
                >
                  <span aria-hidden="true" className="mt-0.5 font-bold">!</span>
                  <span>
                    <strong className="font-semibold">
                      {overdue.length} task{overdue.length === 1 ? ' is' : 's are'} overdue.
                    </strong>{' '}
                    {overdue.length === 1
                      ? `"${overdue[0].title}" was due ${overdue[0].due_date}.`
                      : 'They are listed first below.'}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* --- Checklist -------------------------------------------------- */}
      {tasks.length > 0 && (
        <section className="overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-navy-100/70">
          <div className="flex items-center justify-between gap-3 border-b border-navy-100 p-5">
            <div>
              <h2 className="text-base font-bold tracking-tight text-navy-900">
                Your checklist
              </h2>
              <p className="text-sm text-navy-500">
                {closed.length} of {tasks.length} complete
              </p>
            </div>
            <Link
              to="/my-tasks"
              className="text-sm font-semibold text-accent-600 transition hover:text-accent-700"
            >
              Full view →
            </Link>
          </div>

          <ul className="divide-y divide-navy-100">
            {[...tasks]
              .sort((a, b) => {
                // Open items first (most urgent at the top), done items after.
                const aDone = !isOpen(a)
                const bDone = !isOpen(b)
                if (aDone !== bDone) return aDone ? 1 : -1
                return byUrgency(a, b)
              })
              .map((task) => {
                const done = !isOpen(task)
                const late = isOpen(task) && task.due_date && task.due_date < today
                return (
                  <li
                    key={task.id}
                    className={`flex items-start gap-3 p-4 transition ${
                      done ? 'bg-navy-50/40' : 'hover:bg-navy-50/60'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={done}
                      // A waived item was closed by HR with a reason; an
                      // employee un-ticking it would be overruling them.
                      disabled={task.status === 'waived' || saving === task.id}
                      onChange={(event) => toggle(task, event.target.checked)}
                      aria-label={`Mark "${task.title}" ${done ? 'not done' : 'done'}`}
                      className="mt-0.5 h-5 w-5 shrink-0 rounded-md border-navy-300 text-accent-600 transition"
                    />

                    <div className="min-w-0 flex-1">
                      <p
                        className={`font-medium transition ${
                          done ? 'text-navy-400 line-through' : 'text-navy-900'
                        }`}
                      >
                        {task.title}
                      </p>
                      {task.description && !done && (
                        <p className="mt-0.5 text-sm text-navy-500">{task.description}</p>
                      )}
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            CATEGORY_TONE[task.category] ?? CATEGORY_TONE.task
                          }`}
                        >
                          {CATEGORY_LABEL[task.category] ?? task.category}
                        </span>
                        {task.is_mandatory && !done && (
                          <span className="rounded-full bg-navy-100 px-2 py-0.5 text-xs font-medium text-navy-600">
                            Mandatory
                          </span>
                        )}
                        {task.status === 'waived' && (
                          <span className="rounded-full bg-navy-100 px-2 py-0.5 text-xs font-medium text-navy-600">
                            Waived by HR
                          </span>
                        )}
                        {task.due_date && !done && (
                          <span
                            className={`text-xs ${late ? 'font-semibold text-red-600' : 'text-navy-500'}`}
                          >
                            {late ? 'Overdue — ' : 'Due '}
                            {task.due_date}
                          </span>
                        )}
                      </div>
                    </div>
                  </li>
                )
              })}
          </ul>
        </section>
      )}

      {/* --- Stage + details -------------------------------------------- */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Onboarding stage">
          <ol className="space-y-3">
            {ONBOARDING_STEPS.map((step, index) => {
              const currentIndex = ONBOARDING_STEPS.findIndex(
                (s) => s.key === record.onboarding_status,
              )
              const isDone = index < currentIndex
              const current = index === currentIndex
              return (
                <li key={step.key} className="flex items-start gap-3">
                  <span
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      isDone
                        ? 'bg-emerald-500 text-white'
                        : current
                          ? 'bg-accent-600 text-white'
                          : 'bg-navy-100 text-navy-500'
                    }`}
                  >
                    {isDone ? '✓' : index + 1}
                  </span>
                  <p
                    className={`text-sm ${current ? 'font-semibold text-navy-900' : 'text-navy-600'}`}
                  >
                    {step.label}
                  </p>
                </li>
              )
            })}
          </ol>
        </Card>

        <Card title="Your details">
          <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
            <Detail label="Employee code" value={record.employee_code} />
            <Detail label="Work email" value={record.work_email} />
            <Detail label="Department" value={record.department} />
            <Detail label="Designation" value={record.designation} />
            <Detail label="Date of joining" value={record.date_of_joining} />
            <Detail label="Phone" value={record.phone} />
          </dl>
        </Card>
      </div>
    </div>
  )
}

/** Shown once every assigned item is closed. */
function CelebrationHero({ name, total }) {
  return (
    <div className="flex flex-col items-center gap-4 py-4 text-center">
      <span className="text-5xl" aria-hidden="true">
        🎉
      </span>
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white">
          You're all done{name ? `, ${name}` : ''}!
        </h2>
        <p className="mt-1.5 text-sm text-emerald-50">
          All {total} onboarding {total === 1 ? 'item is' : 'items are'} complete. HR will
          take it from here.
        </p>
      </div>
      <Link to="/assistant">
        <span className="inline-flex items-center rounded-xl bg-white px-4 py-2 text-sm font-semibold text-emerald-700 shadow-card transition hover:-translate-y-0.5 hover:shadow-card-hover">
          Ask HR a question
        </span>
      </Link>
    </div>
  )
}

function Detail({ label, value }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-900">{value || '—'}</dd>
    </div>
  )
}

export default function Dashboard() {
  const { user, isHr } = useAuth()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">
          Welcome back, {user?.full_name?.split(' ')[0]}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {isHr
            ? 'Track onboarding progress across your organisation.'
            : 'Here is where your onboarding stands.'}
        </p>
      </div>
      {isHr ? <HrDashboard /> : <EmployeeDashboard />}
    </div>
  )
}
