/**
 * Team Overview — a department's onboarding at a glance.
 *
 * "Team" means department, because that is the only grouping the data model
 * actually has: there is no manager-to-report relationship in the backend, so
 * a reporting-line view would have nothing real behind it.
 *
 * Unlike the new-hires table on the dashboard above, this section fetches each
 * member's real task progress (one request per person). That is the point of
 * the section — "Avg. completion" has to be a true average, not a stage
 * estimate — and the cost is bounded by the page size below.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Button, EmptyState, Select, SkeletonRows, StatusBadge } from './ui'
import ConfirmDialog from './ConfirmDialog'
import { useToast } from './Toast'
import StatCard, { TREND_UP_IS_BAD } from './StatCard'

// Enough to see a team without turning the page into a request storm.
const TEAM_PAGE_SIZE = 12

const ICONS = {
  team: <path d="M7 9a3 3 0 100-6 3 3 0 000 6zm7 8a5 5 0 00-10 0v1h10v-1zm3-8a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0zm-1 4a4 4 0 013 3.9V18h-2.5v-1a6.4 6.4 0 00-1.2-3.8c.2 0 .5-.1.7-.2z" />,
  done: <path d="M10 2a8 8 0 100 16 8 8 0 000-16zm3.9 6.1l-4.4 4.4a1 1 0 01-1.4 0L6 10.4l1.4-1.4 1.4 1.4 3.7-3.7 1.4 1.4z" />,
  percent: <path d="M6.5 4a2.5 2.5 0 110 5 2.5 2.5 0 010-5zm7 7a2.5 2.5 0 110 5 2.5 2.5 0 010-5zM15 4.4L5.6 15.8l-1.2-1L13.8 3.4l1.2 1z" />,
  overdue: <path d="M10 1.5l8.5 15H1.5l8.5-15zM9 7v5h2V7H9zm0 6.5v2h2v-2H9z" />,
}

const initials = (member) =>
  `${member.first_name?.[0] ?? ''}${member.last_name?.[0] ?? ''}`.toUpperCase() || '?'

export default function TeamOverview() {
  const [departments, setDepartments] = useState([])
  const [department, setDepartment] = useState('')
  const [members, setMembers] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState(null)
  const [sending, setSending] = useState(false)
  const toast = useToast()

  useEffect(() => {
    api
      .dashboardDepartments()
      .then((rows) => {
        setDepartments(rows)
        // Default to the largest real team rather than the alphabetical first.
        const named = rows.filter((row) => row.department !== 'Unassigned')
        setDepartment((named[0] ?? rows[0])?.department ?? '')
      })
      .catch((err) => setError(err.message))
  }, [])

  const load = useCallback(async () => {
    if (!department) return
    setLoading(true)
    try {
      const page = await api.listEmployees({
        // "Unassigned" is this UI's label for a null department, not a value
        // the API knows, so it is not sent as a filter.
        department: department === 'Unassigned' ? undefined : department,
        page_size: TEAM_PAGE_SIZE,
      })

      const rows = page.items.filter((row) =>
        department === 'Unassigned' ? !row.department : true,
      )

      // One progress call per member, in parallel. A member with no tasks
      // yet still resolves, with total 0.
      const withProgress = await Promise.all(
        rows.map(async (member) => ({
          ...member,
          progress: await api.taskProgress(member.id).catch(() => null),
        })),
      )
      setMembers(withProgress)
      setError('')
    } catch (err) {
      setError(err.message)
      setMembers([])
    } finally {
      setLoading(false)
    }
  }, [department])

  useEffect(() => {
    load()
  }, [load])

  const sendReminders = async () => {
    setSending(true)
    try {
      const { due_soon, overdue } = await api.runReminders()
      toast.success(
        due_soon + overdue === 0
          ? 'No new reminders — everyone already has an unread one.'
          : `Sent ${overdue} overdue and ${due_soon} due-soon reminder(s).`,
      )
      setConfirming(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  const withTasks = (members ?? []).filter((m) => m.progress?.total > 0)
  const overdueMembers = (members ?? []).filter((m) => (m.progress?.overdue ?? 0) > 0)
  const fullyOnboarded = (members ?? []).filter(
    (m) => m.onboarding_status === 'complete',
  ).length
  const averageCompletion = withTasks.length
    ? Math.round(
        withTasks.reduce((sum, m) => sum + m.progress.percent_complete, 0) /
          withTasks.length,
      )
    : null

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-bold tracking-tight text-navy-900">Team overview</h2>
          <p className="text-sm text-navy-500">
            Onboarding progress for one department at a time.
          </p>
        </div>
        <Select
          value={department}
          onChange={(event) => setDepartment(event.target.value)}
          className="max-w-52"
          aria-label="Choose a department"
        >
          {departments.map((row) => (
            <option key={row.department} value={row.department}>
              {row.department} ({row.total})
            </option>
          ))}
        </Select>
      </div>

      <Alert>{error}</Alert>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          tone="accent"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.team}</svg>}
          value={members?.length ?? '—'}
          label="Team members"
        />
        <StatCard
          tone="emerald"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.done}</svg>}
          value={members ? fullyOnboarded : '—'}
          label="Fully onboarded"
        />
        <StatCard
          tone="navy"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.percent}</svg>}
          value={averageCompletion == null ? '—' : `${averageCompletion}%`}
          label="Avg. completion"
          // The average covers only people who have tasks; saying so stops it
          // reading as a whole-team figure when half the team has none.
          hint={
            members && withTasks.length !== members.length
              ? `${withTasks.length} of ${members.length} have tasks assigned`
              : undefined
          }
        />
        <StatCard
          tone="red"
          icon={<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">{ICONS.overdue}</svg>}
          value={members ? overdueMembers.length : '—'}
          label="With overdue tasks"
          trendPolarity={TREND_UP_IS_BAD}
        />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-navy-100/70">
        {loading && <SkeletonRows rows={4} className="p-5" />}

        {!loading && members?.length === 0 && (
          <EmptyState icon="👥" title="Nobody in this department">
            Assign a department on an employee profile and they will appear here.
          </EmptyState>
        )}

        {!loading && members?.length > 0 && (
          <ul className="divide-y divide-navy-100">
            {members.map((member) => {
              const percent = member.progress?.percent_complete ?? 0
              const isOverdue = (member.progress?.overdue ?? 0) > 0
              const hasTasks = (member.progress?.total ?? 0) > 0

              return (
                <li
                  key={member.id}
                  className="flex flex-col gap-3 p-4 transition hover:bg-navy-50/60 sm:flex-row sm:items-center sm:gap-4"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-navy-100 text-sm font-bold text-navy-700">
                    {initials(member)}
                  </span>

                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/employees/${member.id}`}
                      className="block truncate font-semibold text-navy-900 transition hover:text-accent-600"
                    >
                      {member.first_name} {member.last_name}
                    </Link>
                    <p className="truncate text-xs text-navy-500">
                      {member.designation ?? 'No role set'}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 sm:w-44">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-navy-100">
                      <div
                        className="h-full rounded-full transition-[width] duration-500"
                        style={{
                          width: `${percent}%`,
                          backgroundColor: isOverdue
                            ? '#dc2626'
                            : percent === 100
                              ? '#059669'
                              : '#2563eb',
                        }}
                      />
                    </div>
                    <span className="w-9 shrink-0 text-right text-xs font-semibold tabular-nums text-navy-700">
                      {hasTasks ? `${percent}%` : '—'}
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center gap-2 sm:w-56 sm:justify-end">
                    <StatusBadge status={member.onboarding_status} />
                    {/* Only people who are actually late get the prompt. */}
                    {isOverdue && (
                      <Button
                        variant="secondary"
                        className="text-xs"
                        onClick={() => setConfirming(member)}
                      >
                        Send reminder
                      </Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {members && members.length === TEAM_PAGE_SIZE && (
        <p className="text-xs text-navy-400">
          Showing the first {TEAM_PAGE_SIZE} members —{' '}
          <Link to="/employees" className="font-medium text-accent-600 hover:underline">
            see all employees
          </Link>
          .
        </p>
      )}

      {confirming && (
        <ConfirmDialog
          title={`Send reminders for ${confirming.first_name} ${confirming.last_name}?`}
          confirmLabel="Send reminders"
          busy={sending}
          onConfirm={sendReminders}
          onCancel={() => setConfirming(null)}
        >
          <p>
            {confirming.first_name} has{' '}
            <strong className="font-semibold text-navy-900">
              {confirming.progress?.overdue} overdue task
              {confirming.progress?.overdue === 1 ? '' : 's'}
            </strong>
            .
          </p>
          {/* The API has no per-person reminder, so promising one here would
              be a lie about what the button does. */}
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
            This runs the reminder sweep, which notifies <strong>everyone</strong> with
            an overdue or due-soon task — not just {confirming.first_name}. Anyone who
            already has an unread reminder will not get a second one.
          </p>
        </ConfirmDialog>
      )}
    </section>
  )
}
