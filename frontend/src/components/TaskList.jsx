import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, EmptyState, Spinner } from './ui'

export const CATEGORY_LABEL = {
  task: 'Task',
  training: 'Training',
  document_checklist: 'Document',
  policy_acknowledgement: 'Policy',
}

const CATEGORY_TONE = {
  task: 'bg-slate-100 text-slate-700',
  training: 'bg-indigo-100 text-indigo-800',
  document_checklist: 'bg-sky-100 text-sky-800',
  policy_acknowledgement: 'bg-violet-100 text-violet-800',
}

const MIN_WAIVER_LENGTH = 10

export function ProgressBar({ progress }) {
  if (!progress) return null
  const percent = progress.percent_complete ?? 0

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-slate-900">
          {progress.completed + progress.waived} of {progress.total} complete
        </p>
        <span className="text-sm tabular-nums text-slate-500">{percent}%</span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full rounded-full transition-all ${
            progress.all_mandatory_done ? 'bg-emerald-500' : 'bg-slate-900'
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {progress.mandatory_outstanding > 0 && (
          <span>{progress.mandatory_outstanding} mandatory outstanding</span>
        )}
        {progress.overdue > 0 && (
          <span className="font-medium text-red-600">{progress.overdue} overdue</span>
        )}
        {progress.waived > 0 && <span>{progress.waived} waived</span>}
      </div>
    </div>
  )
}

function TaskRow({ task, canManage, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [waiving, setWaiving] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  const run = async (fn) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      setWaiving(false)
      setReason('')
      onChanged?.()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  const done = task.status === 'completed'
  const waived = task.status === 'waived'
  const closed = done || waived
  // Document checklist items close themselves when the document is approved.
  const isAutoItem = task.category === 'document_checklist' && task.required_document_type

  return (
    <li className={`px-4 py-3 ${task.is_overdue ? 'bg-red-50/50' : ''}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={closed}
          disabled={busy || waived || isAutoItem}
          onChange={(e) =>
            run(() => api.updateTaskStatus(task.id, e.target.checked ? 'completed' : 'pending'))
          }
          title={
            isAutoItem
              ? 'Completes automatically once the required document is approved'
              : undefined
          }
          className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 disabled:opacity-50"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`text-sm font-medium ${
                closed ? 'text-slate-500 line-through' : 'text-slate-900'
              }`}
            >
              {task.title}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                CATEGORY_TONE[task.category] ?? 'bg-slate-100 text-slate-700'
              }`}
            >
              {CATEGORY_LABEL[task.category] ?? task.category}
            </span>
            {task.is_mandatory && !closed && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                required
              </span>
            )}
            {waived && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                waived
              </span>
            )}
          </div>

          {task.description && (
            <p className="mt-0.5 text-xs text-slate-500">{task.description}</p>
          )}

          <div className="mt-1 flex flex-wrap gap-x-3 text-xs">
            {task.due_date && (
              <span className={task.is_overdue ? 'font-medium text-red-600' : 'text-slate-500'}>
                Due {new Date(task.due_date).toLocaleDateString()}
                {task.is_overdue ? ' — overdue' : ''}
              </span>
            )}
            {task.resource_url && (
              <a
                href={task.resource_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-600 underline hover:text-slate-900"
              >
                Open material
              </a>
            )}
            {isAutoItem && !closed && (
              <span className="text-slate-500">
                Completes when your {task.required_document_type} is approved
              </span>
            )}
          </div>

          {waived && task.waiver_reason && (
            <p className="mt-1 text-xs text-slate-500">Waived: {task.waiver_reason}</p>
          )}
          {error && <p className="mt-1 text-xs text-red-600">{error}</p>}

          {waiving && (
            <div className="mt-2 space-y-2 rounded-md bg-slate-50 p-3">
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                autoFocus
                placeholder="Why is this task being waived for this employee?"
                className="w-full rounded-md border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-inset focus:ring-slate-900"
              />
              <div className="flex gap-2">
                <Button
                  disabled={busy || reason.trim().length < MIN_WAIVER_LENGTH}
                  onClick={() => run(() => api.waiveTask(task.id, reason.trim()))}
                >
                  Confirm waiver
                </Button>
                <Button variant="secondary" onClick={() => setWaiving(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>

        {canManage && !waiving && (
          <div className="flex shrink-0 gap-2">
            {!done && (
              <Button variant="secondary" disabled={busy} onClick={() => setWaiving(true)}>
                Waive
              </Button>
            )}
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                if (confirm(`Remove "${task.title}" from this employee?`)) {
                  run(() => api.deleteTask(task.id))
                }
              }}
            >
              Remove
            </Button>
          </div>
        )}
      </div>
    </li>
  )
}

export default function TaskList({ employeeId, canManage = false, self = false, refreshKey }) {
  const [tasks, setTasks] = useState([])
  const [progress, setProgress] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [taskRows, progressRow] = await Promise.all([
        self ? api.myTasks() : api.listEmployeeTasks(employeeId),
        self ? api.myTaskProgress() : api.taskProgress(employeeId),
      ])
      setTasks(taskRows)
      setProgress(progressRow)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [employeeId, self])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  if (loading) return <Spinner />

  // Group by category so a long list stays scannable.
  const grouped = tasks.reduce((acc, task) => {
    ;(acc[task.category] ??= []).push(task)
    return acc
  }, {})

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>
      <ProgressBar progress={progress} />

      {tasks.length === 0 ? (
        <EmptyState>
          No tasks assigned yet. They appear once onboarding documents are approved.
        </EmptyState>
      ) : (
        Object.entries(grouped).map(([category, rows]) => (
          <section key={category}>
            <h4 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              {CATEGORY_LABEL[category] ?? category}
            </h4>
            <ul className="divide-y divide-slate-100 rounded-lg bg-white ring-1 ring-slate-200">
              {rows.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  canManage={canManage}
                  onChanged={load}
                />
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
