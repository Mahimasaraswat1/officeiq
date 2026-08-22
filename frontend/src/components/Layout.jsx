import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import GlobalSearch from './GlobalSearch'
import NotificationBell from './NotificationBell'

/**
 * Application shell: a persistent navy sidebar on desktop, the same sidebar as
 * a slide-in drawer below `lg`.
 *
 * Only this file changed to make the switch — every page renders through the
 * <Outlet /> below and keeps the same max-width content column it had under the
 * old top navigation, so no screen needed touching.
 */

const ICON = {
  dashboard: <path d="M3 3h6v6H3V3zm8 0h6v4h-6V3zM3 11h6v6H3v-6zm8-2h6v8h-6V9z" />,
  employees: <path d="M7 9a3 3 0 100-6 3 3 0 000 6zm7 8a5 5 0 00-10 0v1h10v-1zm3-8a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0zm-1 4a4 4 0 013 3.9V18h-2.5v-1a6.4 6.4 0 00-1.2-3.8c.2 0 .5-.1.7-.2z" />,
  onboarding: <path d="M10 2l7 3.5v3c0 4-3 7.7-7 8.7-4-1-7-4.7-7-8.7v-3L10 2zm-1 9.6l-2.3-2.3-1.4 1.4L9 14.4l5.7-5.7-1.4-1.4L9 11.6z" />,
  tasks: <path d="M4 4h12v2H4V4zm0 5h12v2H4V9zm0 5h8v2H4v-2z" />,
  assistant: <path d="M10 2c4.4 0 8 3 8 6.7 0 3.7-3.6 6.7-8 6.7-.9 0-1.8-.1-2.6-.4L3 17l1.2-3.2C2.8 12.5 2 10.7 2 8.7 2 5 5.6 2 10 2z" />,
  rules: <path d="M8 3h9v2H8V3zM3 3h3v3H3V3zm5 6h9v2H8V9zm-5 0h3v3H3V9zm5 6h9v2H8v-2zm-5 0h3v3H3v-3z" />,
  knowledge: <path d="M4 3h5.5a2 2 0 012 2v12a2.5 2.5 0 00-2-1H4V3zm12 0h-4.5a2 2 0 00-2 2v12a2.5 2.5 0 012-1H16V3z" />,
  reports: <path d="M4 12h3v5H4v-5zm4.5-5h3v10h-3V7zM13 3h3v14h-3V3z" />,
  users: <path d="M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm0 1.5c-3.3 0-6 2-6 4.5v1h12v-1c0-2.5-2.7-4.5-6-4.5z" />,
  audit: <path d="M5 2h7l3 3v13H5V2zm6 1.5V6h2.5L11 3.5zM7 9h6v1.5H7V9zm0 3h6v1.5H7V12z" />,
  bell: <path d="M10 2a5 5 0 00-5 5v2.6l-1.3 2.6A1 1 0 004.6 14h10.8a1 1 0 00.9-1.4L15 9.6V7a5 5 0 00-5-5zm0 16a2.5 2.5 0 002.45-2h-4.9A2.5 2.5 0 0010 18z" />,
  profile: <path d="M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm0 1.5c-3.3 0-6 2-6 4.5v1h12v-1c0-2.5-2.7-4.5-6-4.5z" />,
}

const NAV = [
  { to: '/', label: 'Dashboard', icon: ICON.dashboard, roles: ['admin', 'hr', 'employee'], end: true },
  { to: '/employees', label: 'Employees', icon: ICON.employees, roles: ['admin', 'hr'] },
  { to: '/my-onboarding', label: 'My Onboarding', icon: ICON.onboarding, roles: ['employee'] },
  { to: '/my-tasks', label: 'My Tasks', icon: ICON.tasks, roles: ['employee'] },
  { to: '/assistant', label: 'Ask HR', icon: ICON.assistant, roles: ['admin', 'hr', 'employee'] },
  { to: '/onboarding-rules', label: 'Rules', icon: ICON.rules, roles: ['admin', 'hr'] },
  { to: '/knowledge-base', label: 'Knowledge', icon: ICON.knowledge, roles: ['admin', 'hr'] },
  { to: '/reports', label: 'Reports', icon: ICON.reports, roles: ['admin', 'hr'] },
  { to: '/users', label: 'Users', icon: ICON.users, roles: ['admin'] },
  { to: '/audit-logs', label: 'Audit Log', icon: ICON.audit, roles: ['admin'] },
  { to: '/notifications', label: 'Notifications', icon: ICON.bell, roles: ['admin', 'hr', 'employee'] },
  { to: '/profile', label: 'Profile', icon: ICON.profile, roles: ['admin', 'hr', 'employee'] },
]

const ROLE_LABEL = { admin: 'Administrator', hr: 'HR', employee: 'Employee' }

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const drawerRef = useRef(null)
  const toggleRef = useRef(null)

  const links = NAV.filter((item) => item.roles.includes(user?.role))

  const handleSignOut = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  // Arriving somewhere is the drawer's whole purpose, so it closes itself.
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  // While the drawer covers the page, Escape closes it, Tab stays inside it,
  // and the page behind does not scroll under the reader's finger.
  useEffect(() => {
    if (!drawerOpen) return undefined

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setDrawerOpen(false)
        toggleRef.current?.focus()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = drawerRef.current?.querySelectorAll('a[href], button:not([disabled])')
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [drawerOpen])

  return (
    <div className="min-h-screen bg-navy-50/50">
      {/* --- Persistent sidebar: lg and up ------------------------------ */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:flex lg:w-64 lg:flex-col">
        <SidebarContent links={links} user={user} onSignOut={handleSignOut} />
      </aside>

      {/* --- Drawer: below lg ------------------------------------------ */}
      {drawerOpen && (
        <div className="lg:hidden">
          <div
            className="fixed inset-0 z-40 bg-navy-950/50 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
            role="presentation"
          />
          <aside
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Main navigation"
            className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col shadow-2xl"
          >
            <SidebarContent
              id="app-sidebar"
              links={links}
              user={user}
              onSignOut={handleSignOut}
              onClose={() => setDrawerOpen(false)}
            />
          </aside>
        </div>
      )}

      {/* --- Content column -------------------------------------------- */}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 border-b border-navy-100 bg-white/85 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
            <button
              ref={toggleRef}
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-expanded={drawerOpen}
              aria-controls="app-sidebar"
              aria-label="Open navigation"
              className="rounded-xl p-2 text-navy-600 transition hover:bg-navy-100 hover:text-navy-900 lg:hidden"
            >
              <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
                <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>

            {/* The wordmark lives in the sidebar on desktop; below lg the
                sidebar is hidden, so the top bar carries it. */}
            <span className="text-base font-bold tracking-tight text-navy-900 lg:hidden">
              OfficeIQ
            </span>

            <div className="ml-auto flex flex-1 items-center justify-end gap-2 sm:gap-3">
              <div className="hidden min-w-0 flex-1 justify-end sm:flex">
                <GlobalSearch />
              </div>
              {/* Identity and sign-out live in the sidebar footer (and in the
                  drawer below lg), so the header does not repeat them. */}
              <NotificationBell />
            </div>
          </div>

          {/* Below sm the header row has no space for search, so it gets its
              own full-width row rather than disappearing. */}
          <div className="px-4 pb-3 sm:hidden">
            <GlobalSearch />
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** The sidebar's contents, shared by the desktop rail and the mobile drawer. */
function SidebarContent({ links, user, onSignOut, onClose, id }) {
  return (
    <div id={id} className="flex h-full flex-col bg-navy-900 text-navy-300">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 text-sm font-extrabold text-white ring-1 ring-white/15">
          IQ
        </span>
        <span className="text-lg font-bold tracking-tight text-white">OfficeIQ</span>

        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="ml-auto rounded-lg p-1.5 text-navy-300 transition hover:bg-white/10 hover:text-white"
          >
            <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
              <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pb-4">
        <ul className="space-y-0.5">
          {links.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition duration-200 ${
                    isActive
                      ? 'bg-accent-600 text-white shadow-card'
                      : 'text-navy-300 hover:bg-white/8 hover:text-white'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <svg
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      aria-hidden="true"
                      className={`h-[18px] w-[18px] shrink-0 transition ${
                        isActive ? 'text-white' : 'text-navy-400 group-hover:text-white'
                      }`}
                    >
                      {item.icon}
                    </svg>
                    <span className="truncate">{item.label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-white/10 p-3">
        <div className="flex items-center gap-3 rounded-xl px-2 py-2">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold text-white">
            {(user?.full_name ?? '?')
              .split(' ')
              .map((part) => part[0])
              .slice(0, 2)
              .join('')
              .toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-white">{user?.full_name}</p>
            <p className="truncate text-xs text-navy-400">
              {ROLE_LABEL[user?.role] ?? user?.role}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onSignOut}
          className="mt-1 w-full rounded-xl px-3 py-2 text-left text-sm font-medium text-navy-300 transition hover:bg-white/8 hover:text-white"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
