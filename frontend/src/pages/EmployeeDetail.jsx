import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import DocumentUpload from '../components/DocumentUpload'
import DocumentList from '../components/DocumentList'
import VerificationPanel from '../components/VerificationPanel'
import EmployeeTasksPanel from '../components/EmployeeTasksPanel'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Select,
  Spinner,
  StatusBadge,
} from '../components/ui'
import { useToast } from '../components/Toast'

const STATUSES = [
  'invited',
  'registered',
  'documents_pending',
  'documents_submitted',
  'under_review',
  'tasks_assigned',
  'complete',
  'rejected',
]

const EDITABLE = [
  ['first_name', 'First name'],
  ['last_name', 'Last name'],
  ['personal_email', 'Personal email'],
  ['phone', 'Phone'],
  ['department', 'Department'],
  ['designation', 'Designation'],
  ['date_of_joining', 'Date of joining'],
  ['reporting_manager', 'Reporting manager'],
]

export default function EmployeeDetail() {
  const toast = useToast()
  const { id } = useParams()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()

  const [employee, setEmployee] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [form, setForm] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [documentsKey, setDocumentsKey] = useState(0)
  const [verificationKey, setVerificationKey] = useState(0)

  const load = useCallback(async () => {
    setError('')
    try {
      const [record, invites] = await Promise.all([
        api.getEmployee(id),
        api.listInvitations(id),
      ])
      setEmployee(record)
      setInvitations(invites)
      setForm(
        Object.fromEntries(EDITABLE.map(([key]) => [key, record[key] ?? ''])).valueOf(),
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  const runAction = async (action, successMessage) => {
    setError('')
    setSaving(true)
    try {
      await action()
      toast.success(successMessage)
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleSave = (event) => {
    event.preventDefault()
    // Send only what actually changed.
    const changes = Object.fromEntries(
      Object.entries(form).filter(([key, value]) => (value || null) !== (employee[key] || null)),
    )
    if (Object.keys(changes).length === 0) {
      toast.success('Nothing to save.')
      return
    }
    runAction(() => api.updateEmployee(id, changes), 'Employee details saved.')
  }

  const handleDelete = () => {
    if (!confirm('Delete this employee profile permanently? This cannot be undone.')) return
    runAction(async () => {
      await api.deleteEmployee(id)
      navigate('/employees', { replace: true })
    }, 'Deleted.')
  }

  if (loading) return <Spinner />
  if (!employee) return <Alert>{error || 'Employee not found.'}</Alert>

  const hasPendingInvite = invitations.some((invite) => invite.status === 'pending')

  return (
    <div className="space-y-6">
      <div>
        <Link to="/employees" className="text-sm text-slate-500 hover:text-slate-900">
          ← Back to employees
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">
            {employee.first_name} {employee.last_name}
          </h1>
          <StatusBadge status={employee.onboarding_status} />
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {employee.employee_code} · {employee.work_email}
        </p>
      </div>

      <Alert>{error}</Alert>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Profile details">
            <form onSubmit={handleSave} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {EDITABLE.map(([key, label]) => (
                  <Field key={key} label={label}>
                    <Input
                      type={key === 'date_of_joining' ? 'date' : 'text'}
                      value={form[key] ?? ''}
                      onChange={update(key)}
                    />
                  </Field>
                ))}
              </div>
              <div className="flex justify-end">
                <Button type="submit" loading={saving}>
                  Save changes
                </Button>
              </div>
            </form>
          </Card>

          <div className="mt-6">
            <Card title="Tasks & training">
              <EmployeeTasksPanel employeeId={id} onChanged={load} />
            </Card>
          </div>

          <div className="mt-6">
            <Card title="Documents">
              <div className="space-y-5">
                <DocumentUpload
                  employeeId={id}
                  onUploaded={() => setDocumentsKey((k) => k + 1)}
                />
                <DocumentList
                  employeeId={id}
                  canManage
                  canReview
                  refreshKey={documentsKey}
                  onChanged={() => {
                    load()
                    setVerificationKey((k) => k + 1)
                  }}
                />
              </div>
            </Card>
          </div>
        </div>

        <div className="space-y-6">
          <Card title="Onboarding status">
            <Field label="Current stage">
              <Select
                value={employee.onboarding_status}
                disabled={saving}
                onChange={(e) =>
                  runAction(
                    () => api.updateEmployee(id, { onboarding_status: e.target.value }),
                    'Onboarding status updated.',
                  )
                }
              >
                {STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value.replaceAll('_', ' ')}
                  </option>
                ))}
              </Select>
            </Field>
            {employee.onboarding_completed_at && (
              <p className="mt-3 text-xs text-slate-500">
                Completed {new Date(employee.onboarding_completed_at).toLocaleString()}
              </p>
            )}
          </Card>

          <Card title="Invitations">
            {employee.user_id ? (
              <p className="text-sm text-emerald-700">
                This employee has activated their account.
              </p>
            ) : (
              <div className="space-y-3">
                <Button
                  variant="secondary"
                  disabled={saving}
                  className="w-full"
                  onClick={() =>
                    runAction(() => api.resendInvite(id), 'Invitation sent.')
                  }
                >
                  {hasPendingInvite ? 'Resend invitation' : 'Send invitation'}
                </Button>
                {hasPendingInvite && (
                  <Button
                    variant="secondary"
                    disabled={saving}
                    className="w-full"
                    onClick={() =>
                      runAction(() => api.revokeInvite(id), 'Invitation revoked.')
                    }
                  >
                    Revoke outstanding invitation
                  </Button>
                )}
              </div>
            )}

            {invitations.length === 0 ? (
              <EmptyState icon="✉️" title="No invitations sent">
                Send one so this employee can set a password and sign in.
              </EmptyState>
            ) : (
              <ul className="mt-4 divide-y divide-slate-100 text-sm">
                {invitations.map((invite) => (
                  <li key={invite.id} className="flex items-center justify-between py-2">
                    <span className="text-xs text-slate-500">
                      {new Date(invite.created_at).toLocaleDateString()}
                    </span>
                    <StatusBadge status={invite.status} />
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Verification">
            <VerificationPanel
              key={verificationKey}
              employeeId={id}
              onChanged={() => {
                load()
                setDocumentsKey((k) => k + 1)
              }}
            />
          </Card>

          {isAdmin && (
            <Card title="Danger zone">
              <Button variant="danger" className="w-full" disabled={saving} onClick={handleDelete}>
                Delete employee profile
              </Button>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
