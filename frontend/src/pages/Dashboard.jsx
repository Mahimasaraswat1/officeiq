import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Alert, Card, EmptyState, Select, Spinner, Stat, StatusBadge } from '../components/ui'
import { ProgressBar } from '../components/TaskList'
import { FunnelBars, TrendChart } from '../components/charts'

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
      api.dashboardTrends({ days }),
      api.dashboardAttention({ limit: 5 }),
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

  if (loading && !data) return <Spinner />
  if (error) return <Alert>{error}</Alert>
  if (!data) return null

  const { summary, funnel, trends, attention, departments } = data
  const totalAttention =
    attention.documents_pending_review.total +
    attention.failed_verifications.total +
    attention.overdue_tasks.total +
    attention.stalled_onboardings.total

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Select
          value={days}
          onChange={(event) => setDays(Number(event.target.value))}
          className="max-w-40"
          aria-label="Reporting window"
        >
          {WINDOWS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>

      {/* Headline numbers are a KPI row, not a chart — four bars would say less. */}
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Total employees" value={summary.employees_total} />
        <Stat label="Onboarding in progress" value={summary.onboarding_in_progress} />
        <Stat
          label="Completed in window"
          value={summary.completed_in_window}
        />
        <Stat
          label="Avg days to onboard"
          value={summary.average_days_to_complete ?? '—'}
        />
      </dl>

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Docs awaiting review" value={summary.documents_pending_review} />
        <Stat label="Overdue tasks" value={summary.tasks_overdue} />
        <Stat
          label="Task completion"
          value={`${Math.round(summary.task_completion_rate * 100)}%`}
        />
        <Stat
          label="Assistant resolution"
          value={
            summary.questions_total
              ? `${Math.round(summary.chat_resolution_rate * 100)}%`
              : '—'
          }
        />
      </dl>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Onboarding funnel">
          {funnel.total === 0 ? (
            <EmptyState>
              No employees yet.{' '}
              <Link to="/employees/new" className="font-medium text-slate-900 underline">
                Create the first profile
              </Link>
              .
            </EmptyState>
          ) : (
            <>
              <FunnelBars stages={funnel.stages} />
              {funnel.total > funnel.stages.reduce((sum, s) => sum + s.count, 0) && (
                <p className="mt-3 text-xs text-slate-500">
                  {funnel.total - funnel.stages.reduce((sum, s) => sum + s.count, 0)} rejected
                  or withdrawn, not shown as a stage.
                </p>
              )}
            </>
          )}
        </Card>

        <Card title="By department">
          {departments.length === 0 ? (
            <EmptyState icon="🏢" title="No departments yet">
              Set a department on an employee profile and the breakdown appears here.
            </EmptyState>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="pb-2 font-medium">Department</th>
                  <th className="pb-2 text-right font-medium">In progress</th>
                  <th className="pb-2 text-right font-medium">Complete</th>
                  <th className="pb-2 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {departments.map((row) => (
                  <tr key={row.department} className="border-t border-slate-100">
                    <td className="py-2 text-slate-900">{row.department}</td>
                    <td className="py-2 text-right tabular-nums text-slate-600">
                      {row.in_progress}
                    </td>
                    <td className="py-2 text-right tabular-nums text-slate-600">
                      {row.complete}
                    </td>
                    <td className="py-2 text-right font-medium tabular-nums text-slate-900">
                      {row.total}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {/* Small multiples rather than one plot: three unrelated scales on one
          y-axis would invent a relationship the data does not have. */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-900">
          Activity over the last {days} days
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          <TrendChart points={trends.points} valueKey="profiles_created" label="Profiles created" />
          <TrendChart
            points={trends.points}
            valueKey="documents_uploaded"
            label="Documents uploaded"
          />
          <TrendChart points={trends.points} valueKey="questions_asked" label="Questions asked" />
        </div>
      </div>

      <Card
        title={`Needs attention${totalAttention ? ` (${totalAttention})` : ''}`}
        action={
          <Link to="/employees" className="text-sm font-medium text-slate-600 hover:text-slate-900">
            All employees →
          </Link>
        }
      >
        {totalAttention === 0 ? (
          <EmptyState icon="✅" title="You are all caught up">
            No documents to review, failed checks, overdue tasks or stalled onboardings.
          </EmptyState>
        ) : (
          <div className="space-y-5">
            <AttentionSection
              title="Documents awaiting review"
              group={attention.documents_pending_review}
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
              group={attention.failed_verifications}
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
              group={attention.overdue_tasks}
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
              group={attention.stalled_onboardings}
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
      </Card>
    </div>
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

function EmployeeDashboard() {
  const [record, setRecord] = useState(null)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.myEmployeeRecord(),
      // Tasks only exist after assignment, so a 404 here is normal.
      api.myTaskProgress().catch(() => null),
    ])
      .then(([employee, taskProgress]) => {
        if (cancelled) return
        setRecord(employee)
        setProgress(taskProgress)
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <Spinner />
  if (error) return <Alert>{error}</Alert>

  const currentIndex = ONBOARDING_STEPS.findIndex((s) => s.key === record.onboarding_status)

  return (
    <div className="space-y-6">
      <Card title="Your onboarding progress">
        <ol className="space-y-3">
          {ONBOARDING_STEPS.map((step, index) => {
            const done = index < currentIndex
            const current = index === currentIndex
            return (
              <li key={step.key} className="flex items-start gap-3">
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    done
                      ? 'bg-emerald-500 text-white'
                      : current
                        ? 'bg-slate-900 text-white'
                        : 'bg-slate-200 text-slate-500'
                  }`}
                >
                  {done ? '✓' : index + 1}
                </span>
                <div>
                  <p
                    className={`text-sm ${current ? 'font-semibold text-slate-900' : 'text-slate-600'}`}
                  >
                    {step.label}
                  </p>
                  {step.phase && !done && !current && (
                    <p className="text-xs text-slate-500">Coming in {step.phase}</p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </Card>

      {progress?.total > 0 && (
        <Card
          title="Your tasks"
          action={
            <Link to="/my-tasks" className="text-sm font-medium text-slate-600 hover:text-slate-900">
              View all →
            </Link>
          }
        >
          <ProgressBar progress={progress} />
        </Card>
      )}

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
