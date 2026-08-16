import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Alert, Button, Field, Input } from '../components/ui'

export default function Login() {
  const { user, login, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) return <Navigate to={location.state?.from?.pathname ?? '/'} replace />

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
      navigate(location.state?.from?.pathname ?? '/', { replace: true })
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="inline-block rounded-lg bg-slate-900 px-3 py-2 text-lg font-bold text-white">
            IQ
          </span>
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">Sign in to OfficeIQ</h1>
          <p className="mt-1 text-sm text-slate-500">HR onboarding & team knowledge hub</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200"
        >
          <Alert>{error}</Alert>

          <Field label="Email">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </Field>

          <Field label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>

          <Button type="submit" loading={submitting} className="w-full">
            Sign in
          </Button>

          <p className="text-center text-sm">
            <Link to="/forgot-password" className="text-slate-600 hover:text-slate-900">
              Forgot your password?
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
