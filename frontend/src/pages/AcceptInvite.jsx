import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Button, Field, Input, Spinner } from '../components/ui'

export default function AcceptInvite() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const navigate = useNavigate()

  const [invite, setInvite] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [phone, setPhone] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!token) {
      setLoadError('This invitation link is missing its token.')
      setLoading(false)
      return
    }
    let cancelled = false
    api
      .previewInvitation(token)
      .then((data) => !cancelled && setInvite(data))
      .catch((err) => !cancelled && setLoadError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [token])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await api.acceptInvitation({ token, password, phone: phone || undefined })
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <span className="inline-block rounded-lg bg-slate-900 px-3 py-2 text-lg font-bold text-white">
            IQ
          </span>
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">Welcome to OfficeIQ</h1>
          <p className="mt-1 text-sm text-slate-500">
            Set a password to activate your account and start onboarding.
          </p>
        </div>

        <div className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200">
          {loading && <Spinner label="Checking your invitation…" />}

          {!loading && loadError && (
            <div className="space-y-4 text-center">
              <Alert>{loadError}</Alert>
              <p className="text-sm text-slate-500">
                Ask your HR contact to send a fresh invitation link.
              </p>
              <Link to="/login" className="block text-sm text-slate-600 hover:text-slate-900">
                Back to sign in
              </Link>
            </div>
          )}

          {!loading && invite && (
            <form onSubmit={handleSubmit} className="space-y-4">
              <dl className="grid grid-cols-2 gap-3 rounded-md bg-slate-50 p-4 text-sm">
                <div className="col-span-2">
                  <dt className="text-xs text-slate-500">Name</dt>
                  <dd className="font-medium text-slate-900">
                    {invite.first_name} {invite.last_name}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-xs text-slate-500">Work email</dt>
                  <dd className="font-medium text-slate-900">{invite.email}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Employee code</dt>
                  <dd className="font-medium text-slate-900">{invite.employee_code}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Department</dt>
                  <dd className="font-medium text-slate-900">{invite.department ?? '—'}</dd>
                </div>
              </dl>

              <Alert>{error}</Alert>

              <Field label="Create a password" hint="At least 8 characters, with a letter and a digit.">
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </Field>

              <Field label="Confirm password">
                <Input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </Field>

              <Field label="Phone number (optional)">
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} />
              </Field>

              <Button type="submit" loading={submitting} className="w-full">
                Activate my account
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
