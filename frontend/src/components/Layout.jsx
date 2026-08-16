import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Button } from './ui'
import GlobalSearch from './GlobalSearch'
import NotificationBell from './NotificationBell'

const NAV = [
  { to: '/', label: 'Dashboard', roles: ['admin', 'hr', 'employee'], end: true },
  { to: '/employees', label: 'Employees', roles: ['admin', 'hr'] },
  { to: '/my-onboarding', label: 'My Onboarding', roles: ['employee'] },
  { to: '/my-tasks', label: 'My Tasks', roles: ['employee'] },
  { to: '/assistant', label: 'Ask HR', roles: ['admin', 'hr', 'employee'] },
  { to: '/onboarding-rules', label: 'Rules', roles: ['admin', 'hr'] },
  { to: '/knowledge-base', label: 'Knowledge', roles: ['admin', 'hr'] },
  { to: '/reports', label: 'Reports', roles: ['admin', 'hr'] },
  { to: '/users', label: 'Users', roles: ['admin'] },
  { to: '/audit-logs', label: 'Audit Log', roles: ['admin'] },
  { to: '/notifications', label: 'Notifications', roles: ['admin', 'hr', 'employee'] },
  { to: '/profile', label: 'Profile', roles: ['admin', 'hr', 'employee'] },
]

const ROLE_LABEL = { admin: 'Administrator', hr: 'HR', employee: 'Employee' }

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButtonRef = useRef(null)

  const handleSignOut = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const links = NAV.filter((item) => item.roles.includes(user?.role))

  // Navigating is the point of the menu, so it closes itself on arrival.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  // Escape closes it and hands focus back to the button that opened it,
  // rather than dropping the reader at the top of the document.
  useEffect(() => {
    if (!menuOpen) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        menuButtonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [menuOpen])

  const navLinkClass = ({ isActive }) =>
    `border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition ${
      isActive
        ? 'border-slate-900 text-slate-900'
        : 'border-transparent text-slate-500 hover:text-slate-800'
    }`

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="rounded-md bg-slate-900 px-2 py-1 text-sm font-bold text-white">
              IQ
            </span>
            <span className="text-lg font-semibold text-slate-900">OfficeIQ</span>
          </div>

          <div className="flex flex-1 items-center justify-end gap-3">
            <div className="hidden flex-1 justify-end sm:flex">
              <GlobalSearch />
            </div>
            <NotificationBell />
            <div className="hidden text-right md:block">
              <p className="text-sm font-medium text-slate-900">{user?.full_name}</p>
              <p className="text-xs text-slate-500">{ROLE_LABEL[user?.role] ?? user?.role}</p>
            </div>
            <div className="hidden md:block">
              <Button variant="secondary" onClick={handleSignOut}>
                Sign out
              </Button>
            </div>

            {/* Below md the twelve nav items no longer fit, so they move into
                a menu instead of scrolling off the edge mid-word. */}
            <button
              ref={menuButtonRef}
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              className="rounded-md p-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 md:hidden"
            >
              <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
                {menuOpen ? (
                  <path
                    d="M5 5l10 10M15 5L5 15"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                ) : (
                  <path
                    d="M3 6h14M3 10h14M3 14h14"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                )}
              </svg>
            </button>
          </div>
        </div>

        {/* Below sm the header row has no space for search, so it gets its own
            full-width row rather than disappearing. */}
        <div className="mx-auto max-w-6xl px-4 pb-3 sm:hidden">
          <GlobalSearch />
        </div>

        {/* Horizontal nav: md and up. */}
        <nav
          aria-label="Main"
          className="mx-auto hidden max-w-6xl gap-1 overflow-x-auto px-4 md:flex"
        >
          {links.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navLinkClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Collapsed nav: below md. Rendered only when open so its links stay
            out of the tab order while hidden. */}
        {menuOpen && (
          <nav
            id="mobile-menu"
            aria-label="Main"
            className="border-t border-slate-200 px-4 py-2 md:hidden"
          >
            <ul className="mx-auto max-w-6xl">
              {links.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `block rounded-md px-3 py-2.5 text-sm font-medium transition ${
                        isActive
                          ? 'bg-slate-100 text-slate-900'
                          : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>

            <div className="mx-auto mt-2 flex max-w-6xl items-center justify-between border-t border-slate-200 pt-3">
              <div>
                <p className="text-sm font-medium text-slate-900">{user?.full_name}</p>
                <p className="text-xs text-slate-500">{ROLE_LABEL[user?.role] ?? user?.role}</p>
              </div>
              <Button variant="secondary" onClick={handleSignOut}>
                Sign out
              </Button>
            </div>
          </nav>
        )}
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
