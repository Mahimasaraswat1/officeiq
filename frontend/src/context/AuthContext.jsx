import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, tokens } from '../lib/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // Restore the session on first paint if a token is already stored.
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!tokens.access) {
        setLoading(false)
        return
      }
      try {
        const me = await api.me()
        if (!cancelled) setUser(me)
      } catch {
        tokens.clear()
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    restore()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password, { remember = true } = {}) => {
    const data = await api.login(email, password)
    tokens.set(data, { remember })
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(async () => {
    try {
      if (tokens.refresh) await api.logout(tokens.refresh)
    } catch {
      // Signing out locally matters more than the server round-trip succeeding.
    } finally {
      tokens.clear()
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({
      user,
      setUser,
      loading,
      login,
      logout,
      isAdmin: user?.role === 'admin',
      isHr: user?.role === 'hr' || user?.role === 'admin',
      isEmployee: user?.role === 'employee',
    }),
    [user, loading, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
