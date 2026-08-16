import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Button, Field, Input, Select } from './ui'
import TaskList from './TaskList'
import { useToast } from './Toast'

const CATEGORIES = [
  { value: 'task', label: 'Task' },
  { value: 'training', label: 'Training' },
  { value: 'policy_acknowledgement', label: 'Policy acknowledgement' },
]

const BLANK = { title: '', description: '', category: 'task', due_date: '', is_mandatory: false }

/** HR-side task management for one employee. */
export default function EmployeeTasksPanel({ employeeId, onChanged }) {
  const toast = useToast()
  const [refreshKey, setRefreshKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState(BLANK)

  const refresh = () => {
    setRefreshKey((k) => k + 1)
    onChanged?.()
  }

  const runAssignment = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.assignTasks(employeeId)
      toast.success(
        result.assigned_count > 0
          ? `${result.message} Matched rules: ${result.matched_rules.join(', ') || 'none'}.`
          : result.message,
      )
      refresh()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  const addTask = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const payload = { ...form }
      if (!payload.due_date) delete payload.due_date
      if (!payload.description) delete payload.description
      await api.addManualTask(employeeId, payload)
      setForm(BLANK)
      setAdding(false)
      toast.success('Task added.')
      refresh()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  const update = (field) => (e) =>
    setForm({ ...form, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          Assignment runs automatically once all required documents are approved.{' '}
          <Link to="/onboarding-rules" className="underline hover:text-slate-900">
            Edit the rules
          </Link>
          .
        </p>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={busy} onClick={runAssignment}>
            Run assignment
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => setAdding((v) => !v)}>
            {adding ? 'Cancel' : 'Add task'}
          </Button>
        </div>
      </div>

      {adding && (
        <form onSubmit={addTask} className="space-y-3 rounded-lg bg-slate-50 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Title">
              <Input value={form.title} onChange={update('title')} required autoFocus />
            </Field>
            <Field label="Category">
              <Select value={form.category} onChange={update('category')}>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Description">
            <Input value={form.description} onChange={update('description')} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Due date">
              <Input type="date" value={form.due_date} onChange={update('due_date')} />
            </Field>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.is_mandatory}
                onChange={update('is_mandatory')}
                className="h-4 w-4 rounded border-slate-300"
              />
              Mandatory
            </label>
          </div>
          <div className="flex justify-end">
            <Button type="submit" disabled={busy}>
              Add task
            </Button>
          </div>
        </form>
      )}

      <TaskList employeeId={employeeId} canManage refreshKey={refreshKey} />
    </div>
  )
}
