import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Alert, Button, Field, Input } from '../components/ui'

/**
 * Role cards — one per role the backend actually defines (admin, hr, employee).
 *
 * These are a visual affordance, not an authentication input: the API
 * authenticates on email and password alone and derives the role from the
 * stored account, so nothing here can grant access. Picking a card themes the
 * form and — for roles that have a seeded demo account — offers to fill the
 * address in, which is what makes the demo quick to walk through.
 */
const ROLES = [
  {
    key: 'admin',
    label: 'Admin',
    blurb: 'Full access',
    accent: 'role-admin',
    demoEmail: 'admin@officeiq.dev',
    icon: (
      <path d="M10 2l6 3v5c0 3.6-2.5 6.9-6 8-3.5-1.1-6-4.4-6-8V5l6-3z" />
    ),
  },
  {
    key: 'hr',
    label: 'HR',
    blurb: 'Onboarding & review',
    accent: 'role-hr',
    demoEmail: 'hr@officeiq.dev',
    icon: (
      <path d="M7 9a3 3 0 100-6 3 3 0 000 6zm7 8a5 5 0 00-10 0v1h10v-1zm3-8a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0zm-1 4a4 4 0 013 3.9V18h-2.5v-1a6.4 6.4 0 00-1.2-3.8c.2 0 .5-.1.7-.2z" />
    ),
  },
  {
    key: 'employee',
    label: 'Employee',
    blurb: 'My onboarding',
    accent: 'role-employee',
    demoEmail: null, // employees sign in with their own invited account
    icon: (
      <path d="M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm0 1.5c-3.3 0-6 2-6 4.5v1h12v-1c0-2.5-2.7-4.5-6-4.5z" />
    ),
  },
]

/**
 * Headline figures for the hero panel.
 *
 * PLACEHOLDER DATA. The login screen is unauthenticated and every analytics
 * endpoint requires an HR session, so there is nothing real to read here
 * without adding a public statistics route to the backend — out of scope for a
 * styling change. The panel labels them as illustrative rather than implying
 * they describe this workspace.
 */
const HERO_STATS = [
  { value: '3.5×', label: 'Faster onboarding' },
  { value: '94%', label: 'Completion rate' },
  { value: '4.8/5', label: 'Satisfaction' },
]

export default function Login() {
  const [role, setRole] = useState('hr')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const { user, login, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // An already-signed-in visitor is sent straight on, rather than being shown
  // a sign-in form they do not need.
  if (!loading && user) return <Navigate to={location.state?.from?.pathname ?? '/'} replace />

  const selected = ROLES.find((r) => r.key === role) ?? ROLES[1]

  const chooseRole = (next) => {
    setRole(next.key)
    // Only overwrite an address the person has not started typing themselves.
    const isDemoAddress = ROLES.some((r) => r.demoEmail === email)
    if (next.demoEmail && (email === '' || isDemoAddress)) setEmail(next.demoEmail)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await login(email, password, { remember })
      navigate(location.state?.from?.pathname ?? '/', { replace: true })
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-white lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <HeroPanel />

      {/* --- Form ------------------------------------------------------- */}
      <main className="flex items-center justify-center px-5 py-10 sm:px-8 lg:py-16">
        <div className="w-full max-w-md">
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 sm:text-3xl">
            Welcome back
          </h1>
          <p className="mt-1.5 text-sm text-navy-500">
            Sign in to continue to your workspace.
          </p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            <fieldset>
              <legend className="mb-2.5 text-sm font-semibold text-navy-800">
                I'm signing in as
              </legend>
              <div className="grid grid-cols-3 gap-2.5">
                {ROLES.map((option) => {
                  const active = option.key === role
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => chooseRole(option)}
                      aria-pressed={active}
                      style={active ? { borderColor: `var(--color-${option.accent})` } : undefined}
                      className={`group flex flex-col items-center gap-1.5 rounded-xl border-2 px-2 py-3 transition duration-200 ${
                        active
                          ? 'bg-white shadow-card'
                          : 'border-navy-100 bg-navy-50/60 hover:-translate-y-0.5 hover:border-navy-200 hover:bg-white hover:shadow-card'
                      }`}
                    >
                      <span
                        className="flex h-8 w-8 items-center justify-center rounded-lg transition"
                        style={{
                          backgroundColor: active
                            ? `var(--color-${option.accent})`
                            : 'var(--color-navy-100)',
                          color: active ? '#fff' : 'var(--color-navy-500)',
                        }}
                      >
                        <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                          {option.icon}
                        </svg>
                      </span>
                      <span
                        className={`text-xs font-semibold ${active ? 'text-navy-900' : 'text-navy-600'}`}
                      >
                        {option.label}
                      </span>
                      <span className="hidden text-[10px] leading-tight text-navy-400 sm:block">
                        {option.blurb}
                      </span>
                    </button>
                  )
                })}
              </div>

              {/* Honesty in the UI itself: two of the four cards have no
                  seeded account, so the demo cannot be walked through them. */}
              {!selected.demoEmail && (
                <p className="mt-2 text-xs text-navy-500">
                  No demo account is seeded for {selected.label}. Sign in with any
                  credentials — your role comes from your account, not this choice.
                </p>
              )}
            </fieldset>

            <Alert>{error}</Alert>

            <Field label="Work email">
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                placeholder="you@company.com"
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
                placeholder="••••••••"
                required
              />
            </Field>

            <div className="flex items-center justify-between gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-navy-600">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  className="h-4 w-4 rounded border-navy-300 text-accent-600 transition"
                />
                Remember me
              </label>
              <Link
                to="/forgot-password"
                className="text-sm font-medium text-accent-600 transition hover:text-accent-700"
              >
                Forgot password?
              </Link>
            </div>

            {/* The button wears the selected role's colour, so the choice above
                is reflected in the action it leads to. */}
            <Button
              type="submit"
              loading={submitting}
              className="w-full py-2.5 text-[15px] shadow-card transition duration-200 hover:-translate-y-0.5 hover:shadow-card-hover disabled:opacity-70 disabled:hover:translate-y-0"
              style={{ backgroundColor: `var(--color-${selected.accent})` }}
            >
              Sign in
            </Button>
          </form>

          <p className="mt-8 text-center text-xs text-navy-400">
            Protected by role-based access control. Every sign-in is recorded in
            the audit log.
          </p>
        </div>
      </main>
    </div>
  )
}

function Wordmark({ tone = 'dark' }) {
  const isDark = tone === 'dark'
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-xl text-sm font-extrabold ${
          isDark ? 'bg-navy-800 text-white' : 'bg-white/15 text-white ring-1 ring-white/25'
        }`}
      >
        IQ
      </span>
      <span
        className={`text-lg font-bold tracking-tight ${isDark ? 'text-navy-900' : 'text-white'}`}
      >
        OfficeIQ
      </span>
    </div>
  )
}

function HeroPanel() {
  return (
    <aside className="relative overflow-hidden bg-gradient-to-br from-navy-800 via-navy-900 to-navy-950 px-6 py-10 sm:px-10 lg:flex lg:flex-col lg:justify-between lg:py-16">
      {/* Soft light blooms, kept behind the content and non-interactive. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 -right-16 h-72 w-72 rounded-full bg-accent-500/20 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-32 -left-20 h-80 w-80 rounded-full bg-accent-600/10 blur-3xl"
      />

      <div className="relative">
        <Wordmark tone="light" />
      </div>

      <div className="relative mt-8 lg:mt-0">
        <h2 className="max-w-md text-2xl leading-tight font-bold tracking-tight text-white sm:text-3xl lg:text-4xl">
          Onboarding that finishes itself.
        </h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-navy-300 sm:text-base">
          Documents verified, tasks assigned and questions answered — so a new
          hire's first week is about the work, not the paperwork.
        </p>

        <dl className="mt-8 grid max-w-md grid-cols-3 gap-3 sm:gap-4">
          {HERO_STATS.map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl bg-white/8 px-3 py-3.5 ring-1 ring-white/10 backdrop-blur-sm transition duration-200 hover:bg-white/12"
            >
              <dt className="sr-only">{stat.label}</dt>
              <dd>
                <span className="block text-xl font-bold text-white sm:text-2xl">
                  {stat.value}
                </span>
                <span className="mt-0.5 block text-[11px] leading-tight text-navy-300">
                  {stat.label}
                </span>
              </dd>
            </div>
          ))}
        </dl>

        {/* Never let illustrative numbers read as this workspace's own. */}
        <p className="mt-3 max-w-md text-[11px] text-navy-400">
          Illustrative figures — not this workspace's data.
        </p>
      </div>

      <p className="relative mt-8 hidden text-xs text-navy-400 lg:block">
        © {new Date().getFullYear()} OfficeIQ
      </p>
    </aside>
  )
}
