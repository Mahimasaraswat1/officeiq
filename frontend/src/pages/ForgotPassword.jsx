import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Button, Field, Input } from '../components/ui'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const response = await api.forgotPassword(email)
      setSent(response.message)
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-2xl font-semibold text-slate-900">Reset password</h1>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200"
        >
          <Alert>{error}</Alert>
          <Alert tone="success">{sent}</Alert>

          {!sent && (
            <>
              <Field
                label="Email"
                hint="We'll send a reset link if an account exists for this address."
              >
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                />
              </Field>
              <Button type="submit" loading={submitting} className="w-full">
                Send reset link
              </Button>
            </>
          )}

          <p className="text-center text-sm">
            <Link to="/login" className="text-slate-600 hover:text-slate-900">
              Back to sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
