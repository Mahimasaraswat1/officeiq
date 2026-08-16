import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Alert, Button, Card, EmptyState, Field, Input, Select } from '../components/ui'
import DataTable from '../components/DataTable'
import { useToast } from '../components/Toast'

const BLANK = { email: '', full_name: '', password: '', role: 'hr' }

export default function UserAdmin() {
  const toast = useToast()
  const { user: currentUser } = useAuth()

  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [form, setForm] = useState(BLANK)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api.listUsers({ page_size: 100 })
      setUsers(data.items)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  const handleCreate = async (event) => {
    event.preventDefault()
    setError('')
    setCreating(true)
    try {
      await api.createUser(form)
      setForm(BLANK)
      toast.success('User created.')
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setCreating(false)
    }
  }

  const toggleActive = async (target) => {
    setError('')
    try {
      await api.updateUser(target.id, { is_active: !target.is_active })
      toast.success(`${target.email} ${target.is_active ? 'deactivated' : 'reactivated'}.`)
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Users</h1>
        <p className="mt-1 text-sm text-slate-500">
          Admin and HR accounts. Employee accounts are created through the invitation flow.
        </p>
      </div>

      <Alert>{error}</Alert>

      <Card title="Create an Admin or HR account">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Email">
              <Input type="email" value={form.email} onChange={update('email')} required />
            </Field>
            <Field label="Full name">
              <Input value={form.full_name} onChange={update('full_name')} required />
            </Field>
            <Field label="Temporary password" hint="At least 8 characters, a letter and a digit.">
              <Input
                type="password"
                value={form.password}
                onChange={update('password')}
                required
              />
            </Field>
            <Field label="Role">
              <Select value={form.role} onChange={update('role')}>
                <option value="hr">HR</option>
                <option value="admin">Admin</option>
              </Select>
            </Field>
          </div>
          <div className="flex justify-end">
            <Button type="submit" loading={creating}>
              Create user
            </Button>
          </div>
        </form>
      </Card>

      <div className="overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
        <DataTable
          columns={[
            {
              key: 'name',
              header: 'Name',
              primary: true,
              cell: (row) => row.full_name,
              className: 'font-medium text-slate-900',
            },
            { key: 'email', header: 'Email', cell: (row) => row.email, className: 'text-slate-600' },
            {
              key: 'role',
              header: 'Role',
              cell: (row) => row.role,
              className: 'text-slate-600 uppercase',
            },
            {
              key: 'status',
              header: 'Status',
              cell: (row) => (
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    row.is_active
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {row.is_active ? 'active' : 'inactive'}
                </span>
              ),
            },
            {
              key: 'last_login',
              header: 'Last sign-in',
              cell: (row) =>
                row.last_login_at ? new Date(row.last_login_at).toLocaleString() : '—',
              className: 'text-slate-600',
            },
            {
              // No header: this is the action column, so the card shows the
              // button on its own rather than labelling it.
              key: 'actions',
              header: '',
              align: 'right',
              cell: (row) =>
                row.id !== currentUser?.id && (
                  <Button variant="secondary" onClick={() => toggleActive(row)}>
                    {row.is_active ? 'Deactivate' : 'Reactivate'}
                  </Button>
                ),
            },
          ]}
          rows={users}
          rowKey={(row) => row.id}
          loading={loading}
          skeletonRows={5}
          empty={
            <EmptyState icon="🔑" title="No staff accounts">
              Admin and HR accounts appear here. Employees get their accounts through
              the onboarding invitation instead.
            </EmptyState>
          }
        />
      </div>
    </div>
  )
}
