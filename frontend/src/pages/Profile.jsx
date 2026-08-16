import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Alert, Button, Card, EmptyState, Field, Input, Spinner } from '../components/ui'
import { relativeTime } from '../components/NotificationBell'
import { useToast } from '../components/Toast'

const ROLE_LABEL = { admin: 'Administrator', hr: 'HR', employee: 'Employee' }

export default function Profile() {
  const { user, setUser } = useAuth()
  const toast = useToast()

  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [profileState, setProfileState] = useState({ error: '', saving: false })

  const [passwords, setPasswords] = useState({ current: '', next: '', confirm: '' })
  const [passwordState, setPasswordState] = useState({ error: '', saving: false })

  const saveProfile = async (event) => {
    event.preventDefault()
    setProfileState({ error: '', saving: true })
    try {
      const updated = await api.updateProfile({ full_name: fullName })
      setUser(updated)
      setProfileState({ error: '', saving: false })
      toast.success('Profile updated.')
    } catch (err) {
      setProfileState({ error: err.fieldMessages ?? err.message, saving: false })
    }
  }

  const changePassword = async (event) => {
    event.preventDefault()
    if (passwords.next !== passwords.confirm) {
      setPasswordState({ error: 'The two passwords do not match.', saving: false })
      return
    }
    setPasswordState({ error: '', saving: true })
    try {
      const response = await api.changePassword({
        current_password: passwords.current,
        new_password: passwords.next,
      })
      setPasswords({ current: '', next: '', confirm: '' })
      setPasswordState({ error: '', saving: false })
      toast.success(response.message)
    } catch (err) {
      setPasswordState({ error: err.fieldMessages ?? err.message, saving: false })
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Profile</h1>

      <Card title="Account">
        <form onSubmit={saveProfile} className="space-y-4">
          <Alert>{profileState.error}</Alert>
          
          <Field label="Email" hint="Your sign-in address cannot be changed here.">
            <Input value={user?.email ?? ''} disabled />
          </Field>

          <Field label="Full name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </Field>

          <dl className="grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 text-sm">
            <div>
              <dt className="text-xs text-slate-500">Role</dt>
              <dd className="font-medium text-slate-900">
                {ROLE_LABEL[user?.role] ?? user?.role}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Last sign-in</dt>
              <dd className="font-medium text-slate-900">
                {user?.last_login_at ? new Date(user.last_login_at).toLocaleString() : '—'}
              </dd>
            </div>
          </dl>

          <div className="flex justify-end">
            <Button type="submit" loading={profileState.saving}>
              Save profile
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Change password">
        <form onSubmit={changePassword} className="space-y-4">
          <Alert>{passwordState.error}</Alert>
          
          <Field label="Current password">
            <Input
              type="password"
              value={passwords.current}
              onChange={(e) => setPasswords({ ...passwords, current: e.target.value })}
              autoComplete="current-password"
              required
            />
          </Field>

          <Field label="New password" hint="At least 8 characters, with a letter and a digit.">
            <Input
              type="password"
              value={passwords.next}
              onChange={(e) => setPasswords({ ...passwords, next: e.target.value })}
              autoComplete="new-password"
              required
            />
          </Field>

          <Field label="Confirm new password">
            <Input
              type="password"
              value={passwords.confirm}
              onChange={(e) => setPasswords({ ...passwords, confirm: e.target.value })}
              autoComplete="new-password"
              required
            />
          </Field>

          <div className="flex justify-end">
            <Button type="submit" loading={passwordState.saving}>
              Update password
            </Button>
          </div>
        </form>
      </Card>

      <Sessions />
      <Activity />
    </div>
  )
}

function Sessions() {
  const toast = useToast()
  const [sessions, setSessions] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api
      .listSessions()
      .then(setSessions)
      .catch((err) => setError(err.message))
  }, [])

  useEffect(load, [load])

  const revoke = async (id) => {
    try {
      const response = await api.revokeSession(id)
      toast.success(response.message)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const revokeAll = async () => {
    try {
      const response = await api.revokeAllSessions()
      toast.success(response.message)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <Card
      title="Signed-in devices"
      action={
        sessions?.length > 0 && (
          <button
            type="button"
            onClick={revokeAll}
            className="text-sm font-medium text-red-600 hover:text-red-700"
          >
            Sign out everywhere
          </button>
        )
      }
    >
      <Alert>{error}</Alert>

      {sessions === null && <Spinner />}
      {sessions?.length === 0 && (
        <EmptyState icon="💻" title="Only this device">
          No other devices are signed in to your account right now.
        </EmptyState>
      )}
      {sessions?.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {sessions.map((session) => (
            <li key={session.id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">
                  {describeAgent(session.user_agent)}
                </p>
                <p className="text-xs text-slate-500">
                  {session.ip_address ?? 'Unknown IP'} · last used{' '}
                  {session.last_used_at ? relativeTime(session.last_used_at) : 'never'} ·
                  signed in {relativeTime(session.created_at)}
                </p>
              </div>
              <Button variant="secondary" onClick={() => revoke(session.id)}>
                Sign out
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-slate-500">
        Signing a device out revokes its refresh token. An access token already issued
        keeps working until it expires, which is a matter of minutes.
      </p>
    </Card>
  )
}

/** Turn a raw user-agent string into something a person can recognise. */
function describeAgent(agent) {
  if (!agent) return 'Unknown device'
  const browser =
    /Edg\//.test(agent) ? 'Edge'
    : /OPR\//.test(agent) ? 'Opera'
    : /Chrome\//.test(agent) ? 'Chrome'
    : /Safari\//.test(agent) ? 'Safari'
    : /Firefox\//.test(agent) ? 'Firefox'
    : null
  const platform =
    /iPhone|iPad/.test(agent) ? 'iOS'
    : /Android/.test(agent) ? 'Android'
    : /Mac OS X/.test(agent) ? 'macOS'
    : /Windows/.test(agent) ? 'Windows'
    : /Linux/.test(agent) ? 'Linux'
    : null

  if (browser && platform) return `${browser} on ${platform}`
  if (browser) return browser
  // Not a recognised browser — show the raw string rather than guess.
  return agent.length > 60 ? `${agent.slice(0, 60)}…` : agent
}

function Activity() {
  const [entries, setEntries] = useState(null)

  useEffect(() => {
    api
      .myActivity({ limit: 15 })
      .then(setEntries)
      .catch(() => setEntries([]))
  }, [])

  return (
    <Card title="Recent account activity">
      {entries === null && <Spinner />}
      {entries?.length === 0 && (
        <EmptyState icon="🕓" title="No activity yet">
          Your sign-ins and account changes will be listed here.
        </EmptyState>
      )}
      {entries?.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-center justify-between py-2 text-sm">
              <span className="text-slate-900">{entry.action.replaceAll('_', ' ')}</span>
              <span className="text-xs text-slate-500">
                {entry.ip_address ? `${entry.ip_address} · ` : ''}
                {relativeTime(entry.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-slate-500">
        Only actions you performed. Administrators see the organisation-wide trail in
        the audit log.
      </p>
    </Card>
  )
}
