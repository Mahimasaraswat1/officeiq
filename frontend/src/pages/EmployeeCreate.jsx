import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Button, Card, Field, Input } from '../components/ui'

const BLANK = {
  first_name: '',
  last_name: '',
  work_email: '',
  personal_email: '',
  phone: '',
  department: '',
  designation: '',
  date_of_joining: '',
  reporting_manager: '',
  employee_code: '',
}

export default function EmployeeCreate() {
  const navigate = useNavigate()
  const [form, setForm] = useState(BLANK)
  const [sendInvite, setSendInvite] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)

    // Drop empty strings so optional fields stay null rather than "".
    const payload = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== ''))
    payload.send_invite = sendInvite

    try {
      const created = await api.createEmployee(payload)
      navigate(`/employees/${created.id}`, { replace: true })
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link to="/employees" className="text-sm text-slate-500 hover:text-slate-900">
          ← Back to employees
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-slate-900">Add an employee</h1>
        <p className="mt-1 text-sm text-slate-500">
          Creating a profile sends an onboarding invitation to the work email.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <Card>
          <div className="space-y-4">
            <Alert>{error}</Alert>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="First name">
                <Input value={form.first_name} onChange={update('first_name')} required autoFocus />
              </Field>
              <Field label="Last name">
                <Input value={form.last_name} onChange={update('last_name')} required />
              </Field>
            </div>

            <Field label="Work email" hint="The invitation is sent here and becomes their login.">
              <Input
                type="email"
                value={form.work_email}
                onChange={update('work_email')}
                required
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Personal email (optional)">
                <Input
                  type="email"
                  value={form.personal_email}
                  onChange={update('personal_email')}
                />
              </Field>
              <Field label="Phone (optional)">
                <Input value={form.phone} onChange={update('phone')} />
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Department">
                <Input value={form.department} onChange={update('department')} />
              </Field>
              <Field label="Designation">
                <Input value={form.designation} onChange={update('designation')} />
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Date of joining">
                <Input
                  type="date"
                  value={form.date_of_joining}
                  onChange={update('date_of_joining')}
                />
              </Field>
              <Field label="Reporting manager">
                <Input value={form.reporting_manager} onChange={update('reporting_manager')} />
              </Field>
            </div>

            <Field label="Employee code (optional)" hint="Generated automatically when left blank.">
              <Input value={form.employee_code} onChange={update('employee_code')} />
            </Field>

            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={sendInvite}
                onChange={(e) => setSendInvite(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300"
              />
              Send the onboarding invitation now
            </label>

            <div className="flex justify-end gap-2 pt-2">
              <Link to="/employees">
                <Button type="button" variant="secondary">
                  Cancel
                </Button>
              </Link>
              <Button type="submit" loading={submitting}>
                Create employee
              </Button>
            </div>
          </div>
        </Card>
      </form>
    </div>
  )
}
