import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import { ToastProvider } from './components/Toast'

import Login from './pages/Login'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import AcceptInvite from './pages/AcceptInvite'
import Dashboard from './pages/Dashboard'
import EmployeeList from './pages/EmployeeList'
import EmployeeCreate from './pages/EmployeeCreate'
import EmployeeDetail from './pages/EmployeeDetail'
import MyOnboarding from './pages/MyOnboarding'
import Profile from './pages/Profile'
import UserAdmin from './pages/UserAdmin'
import AuditLog from './pages/AuditLog'
import OnboardingRules from './pages/OnboardingRules'
import MyTasks from './pages/MyTasks'
import Assistant from './pages/Assistant'
import KnowledgeBase from './pages/KnowledgeBase'
import Notifications from './pages/Notifications'
import Reports from './pages/Reports'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
          {/* Public */}
          <Route path="/login" element={<Login />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/accept-invite" element={<AcceptInvite />} />

          {/* Signed in */}
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/assistant" element={<Assistant />} />
              <Route path="/notifications" element={<Notifications />} />

              <Route element={<RequireAuth roles={['employee']} />}>
                <Route path="/my-onboarding" element={<MyOnboarding />} />
                <Route path="/my-tasks" element={<MyTasks />} />
              </Route>

              <Route element={<RequireAuth roles={['admin', 'hr']} />}>
                <Route path="/onboarding-rules" element={<OnboardingRules />} />
                <Route path="/knowledge-base" element={<KnowledgeBase />} />
                <Route path="/employees" element={<EmployeeList />} />
                <Route path="/employees/new" element={<EmployeeCreate />} />
                <Route path="/employees/:id" element={<EmployeeDetail />} />
                <Route path="/reports" element={<Reports />} />
              </Route>

              <Route element={<RequireAuth roles={['admin']} />}>
                <Route path="/users" element={<UserAdmin />} />
                <Route path="/audit-logs" element={<AuditLog />} />
              </Route>
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
