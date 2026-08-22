/**
 * API client: token storage, automatic refresh on 401, consistent error shape.
 * Mirrors the backend envelope { status, error: { code, message, details } }.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const API = `${BASE_URL}/api/v1`

const ACCESS_KEY = 'officeiq.access_token'
const REFRESH_KEY = 'officeiq.refresh_token'

/**
 * Token storage, honouring "Remember me".
 *
 * Checked keeps the session in localStorage, so it survives closing the
 * browser. Unchecked uses sessionStorage, which the browser discards when the
 * tab closes — the behaviour the checkbox implies, on a shared machine.
 *
 * Reads check both stores so a token written either way is found, and clear()
 * empties both so signing out never leaves one behind.
 */
const stores = () => [localStorage, sessionStorage]

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY) ?? sessionStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY) ?? sessionStorage.getItem(REFRESH_KEY)
  },
  set({ access_token, refresh_token }, { remember = true } = {}) {
    const store = remember ? localStorage : sessionStorage
    // Drop any copy in the other store, or a stale token there would win on
    // the next read and outlive the choice just made.
    const other = remember ? sessionStorage : localStorage
    if (access_token) {
      store.setItem(ACCESS_KEY, access_token)
      other.removeItem(ACCESS_KEY)
    }
    if (refresh_token) {
      store.setItem(REFRESH_KEY, refresh_token)
      other.removeItem(REFRESH_KEY)
    }
  },
  clear() {
    stores().forEach((store) => {
      store.removeItem(ACCESS_KEY)
      store.removeItem(REFRESH_KEY)
    })
  },
}

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }

  /** Flattens field-level validation details into a readable string. */
  get fieldMessages() {
    if (!Array.isArray(this.details)) return null
    return this.details.map((d) => `${d.field}: ${d.message}`).join('\n')
  }
}

async function toError(response) {
  let body
  try {
    body = await response.json()
  } catch {
    return new ApiError(response.status, 'network_error', response.statusText)
  }
  const err = body?.error ?? {}
  return new ApiError(
    response.status,
    err.code ?? 'error',
    err.message ?? 'Something went wrong.',
    err.details,
  )
}

let refreshInFlight = null

async function refreshAccessToken() {
  const refresh_token = tokens.refresh
  if (!refresh_token) return false

  // Collapse concurrent 401s into a single refresh call.
  refreshInFlight ??= fetch(`${API}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token }),
  })
    .then(async (response) => {
      if (!response.ok) return false
      const data = await response.json()
      // Write the refreshed token back to whichever store the session
      // already lives in, or a "don't remember me" login would quietly
      // become persistent on its first refresh.
      const remember = localStorage.getItem(REFRESH_KEY) !== null
      tokens.set({ access_token: data.access_token }, { remember })
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null
    })

  return refreshInFlight
}

async function request(path, { method = 'GET', body, auth = true, retry = true } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth && tokens.access) headers.Authorization = `Bearer ${tokens.access}`

  const response = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && auth && retry && tokens.refresh) {
    if (await refreshAccessToken()) {
      return request(path, { method, body, auth, retry: false })
    }
    tokens.clear()
  }

  if (!response.ok) throw await toError(response)
  if (response.status === 204) return null
  return response.json()
}

/**
 * Fetch a binary file and hand it to the browser as a download.
 *
 * A plain <a href> cannot carry the Authorization header, and putting a token
 * in the query string would leak it into browser history and server logs — so
 * the bytes come back through fetch and are saved from a temporary object URL.
 */
async function download(path, retry = true) {
  const headers = {}
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`

  const response = await fetch(`${API}${path}`, { headers })

  if (response.status === 401 && retry && tokens.refresh) {
    if (await refreshAccessToken()) return download(path, false)
    tokens.clear()
  }
  if (!response.ok) throw await toError(response)

  // Prefer the filename the server chose; it carries the report key and date.
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  const filename = match ? match[1] : 'officeiq-report'

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  return filename
}

/**
 * Multipart upload via XHR — fetch cannot report upload progress, and a large
 * scan on a slow connection needs a progress bar to feel responsive.
 */
async function upload(path, file, documentType, onProgress, retry = true) {
  const send = () =>
    new Promise((resolve, reject) => {
      const form = new FormData()
      form.append('file', file)
      form.append('document_type', documentType)

      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${API}${path}`)
      if (tokens.access) xhr.setRequestHeader('Authorization', `Bearer ${tokens.access}`)

      if (onProgress) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            onProgress(Math.round((event.loaded / event.total) * 100))
          }
        }
      }

      xhr.onload = () => {
        let body
        try {
          body = JSON.parse(xhr.responseText)
        } catch {
          body = null
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body)
          return
        }
        const err = body?.error ?? {}
        reject(
          new ApiError(
            xhr.status,
            err.code ?? 'error',
            err.message ?? 'Upload failed.',
            err.details,
          ),
        )
      }
      xhr.onerror = () => reject(new ApiError(0, 'network_error', 'Network error during upload.'))
      xhr.send(form)
    })

  try {
    return await send()
  } catch (error) {
    if (error.status === 401 && retry && (await refreshAccessToken())) {
      return upload(path, file, documentType, onProgress, false)
    }
    throw error
  }
}

const qs = (params) => {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const str = search.toString()
  return str ? `?${str}` : ''
}

export const api = {
  // --- Auth ---
  login: (email, password) =>
    request('/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  logout: (refresh_token) => request('/auth/logout', { method: 'POST', body: { refresh_token } }),
  me: () => request('/auth/me'),
  forgotPassword: (email) =>
    request('/auth/forgot-password', { method: 'POST', body: { email }, auth: false }),
  resetPassword: (token, new_password) =>
    request('/auth/reset-password', {
      method: 'POST',
      body: { token, new_password },
      auth: false,
    }),

  // --- Onboarding (public) ---
  previewInvitation: (token) =>
    request(`/onboarding/invitation${qs({ token })}`, { auth: false }),
  acceptInvitation: (payload) =>
    request('/onboarding/accept', { method: 'POST', body: payload, auth: false }),

  // --- Employees ---
  listEmployees: (params) => request(`/employees${qs(params)}`),
  createEmployee: (payload) => request('/employees', { method: 'POST', body: payload }),
  getEmployee: (id) => request(`/employees/${id}`),
  updateEmployee: (id, payload) => request(`/employees/${id}`, { method: 'PATCH', body: payload }),
  deleteEmployee: (id) => request(`/employees/${id}`, { method: 'DELETE' }),
  myEmployeeRecord: () => request('/employees/me'),
  updateMyEmployeeRecord: (payload) =>
    request('/employees/me', { method: 'PATCH', body: payload }),
  listInvitations: (id) => request(`/employees/${id}/invitations`),
  resendInvite: (id) => request(`/employees/${id}/invite`, { method: 'POST' }),
  revokeInvite: (id) => request(`/employees/${id}/invite/revoke`, { method: 'POST' }),

  // --- Documents (Phase 2) ---
  listDocuments: (employeeId, params) =>
    request(`/employees/${employeeId}/documents${qs(params)}`),
  uploadDocument: (employeeId, file, documentType, onProgress) =>
    upload(`/employees/${employeeId}/documents`, file, documentType, onProgress),
  getDocument: (id) => request(`/documents/${id}`),
  deleteDocument: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  reprocessDocument: (id) => request(`/documents/${id}/reprocess`, { method: 'POST' }),
  getDownloadUrl: (id) => request(`/documents/${id}/download-url`),
  correctField: (documentId, fieldId, corrected_value) =>
    request(`/documents/${documentId}/fields/${fieldId}`, {
      method: 'PATCH',
      body: { corrected_value },
    }),
  applyExtraction: (documentId, payload = {}) =>
    request(`/documents/${documentId}/apply-to-profile`, { method: 'POST', body: payload }),

  // --- Verification & review (Phase 3) ---
  verifyDocument: (id) => request(`/documents/${id}/verify`, { method: 'POST' }),
  runFaceMatch: (employeeId) =>
    request(`/employees/${employeeId}/face-match`, { method: 'POST' }),
  listVerifications: (employeeId) => request(`/employees/${employeeId}/verifications`),
  listFaceMatches: (employeeId) => request(`/employees/${employeeId}/face-matches`),
  verificationSummary: (employeeId) =>
    request(`/employees/${employeeId}/verification-summary`),
  approveDocument: (id, note) =>
    request(`/documents/${id}/approve`, { method: 'POST', body: { note: note ?? null } }),
  rejectDocument: (id, reason) =>
    request(`/documents/${id}/reject`, { method: 'POST', body: { reason } }),
  completeOnboarding: (employeeId) =>
    request(`/employees/${employeeId}/complete-onboarding`, { method: 'POST' }),

  // --- Tasks, training & rules (Phase 4) ---
  listTaskTemplates: (params) => request(`/task-templates${qs(params)}`),
  createTaskTemplate: (payload) => request('/task-templates', { method: 'POST', body: payload }),
  updateTaskTemplate: (id, payload) =>
    request(`/task-templates/${id}`, { method: 'PATCH', body: payload }),
  deleteTaskTemplate: (id) => request(`/task-templates/${id}`, { method: 'DELETE' }),

  listAssignmentRules: (params) => request(`/assignment-rules${qs(params)}`),
  createAssignmentRule: (payload) =>
    request('/assignment-rules', { method: 'POST', body: payload }),
  updateAssignmentRule: (id, payload) =>
    request(`/assignment-rules/${id}`, { method: 'PATCH', body: payload }),
  deleteAssignmentRule: (id) => request(`/assignment-rules/${id}`, { method: 'DELETE' }),
  previewAssignment: (payload) =>
    request('/assignment-rules/preview', { method: 'POST', body: payload }),

  listEmployeeTasks: (employeeId, params) =>
    request(`/employees/${employeeId}/tasks${qs(params)}`),
  taskProgress: (employeeId) => request(`/employees/${employeeId}/task-progress`),
  assignTasks: (employeeId) =>
    request(`/employees/${employeeId}/assign-tasks`, { method: 'POST' }),
  addManualTask: (employeeId, payload) =>
    request(`/employees/${employeeId}/tasks`, { method: 'POST', body: payload }),
  updateTaskStatus: (taskId, status, notes) =>
    request(`/tasks/${taskId}`, { method: 'PATCH', body: { status, notes: notes ?? null } }),
  waiveTask: (taskId, reason) =>
    request(`/tasks/${taskId}/waive`, { method: 'POST', body: { reason } }),
  deleteTask: (taskId) => request(`/tasks/${taskId}`, { method: 'DELETE' }),
  myTasks: () => request('/my-tasks'),
  myTaskProgress: () => request('/my-task-progress'),

  // --- Knowledge base & AI assistant (Phase 5) ---
  knowledgeStats: () => request('/knowledge/stats'),
  listKnowledgeDocuments: (params) => request(`/knowledge/documents${qs(params)}`),
  getKnowledgeDocument: (id) => request(`/knowledge/documents/${id}`),
  createKnowledgeDocument: (payload) =>
    request('/knowledge/documents', { method: 'POST', body: payload }),
  updateKnowledgeDocument: (id, payload) =>
    request(`/knowledge/documents/${id}`, { method: 'PATCH', body: payload }),
  reingestKnowledgeDocument: (id) =>
    request(`/knowledge/documents/${id}/reingest`, { method: 'POST' }),
  deleteKnowledgeDocument: (id) =>
    request(`/knowledge/documents/${id}`, { method: 'DELETE' }),
  searchKnowledge: (payload) =>
    request('/knowledge/search', { method: 'POST', body: payload }),

  ask: (payload) => request('/chat/ask', { method: 'POST', body: payload }),
  listConversations: () => request('/chat/conversations'),
  getConversation: (id) => request(`/chat/conversations/${id}`),
  deleteConversation: (id) => request(`/chat/conversations/${id}`, { method: 'DELETE' }),
  chatAnalytics: () => request('/chat/analytics'),

  // --- Dashboard, search & notifications (Phase 6) ---
  dashboardSummary: (params) => request(`/dashboard/summary${qs(params)}`),
  dashboardFunnel: () => request('/dashboard/funnel'),
  dashboardDepartments: () => request('/dashboard/departments'),
  dashboardTrends: (params) => request(`/dashboard/trends${qs(params)}`),
  dashboardAttention: (params) => request(`/dashboard/attention${qs(params)}`),

  search: (q, params) => request(`/search${qs({ q, ...params })}`),

  listNotifications: (params) => request(`/notifications${qs(params)}`),
  unreadCount: () => request('/notifications/unread-count'),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request('/notifications/read-all', { method: 'POST' }),
  dismissNotification: (id) => request(`/notifications/${id}`, { method: 'DELETE' }),
  runReminders: () => request('/notifications/run-reminders', { method: 'POST' }),

  // --- Users & profile ---
  getProfile: () => request('/profile'),
  updateProfile: (payload) => request('/profile', { method: 'PATCH', body: payload }),
  changePassword: (payload) => request('/profile/password', { method: 'POST', body: payload }),
  listUsers: (params) => request(`/users${qs(params)}`),
  createUser: (payload) => request('/users', { method: 'POST', body: payload }),
  updateUser: (id, payload) => request(`/users/${id}`, { method: 'PATCH', body: payload }),

  // --- Sessions & personal activity (Phase 7) ---
  listSessions: () => request('/profile/sessions'),
  revokeSession: (id) => request(`/profile/sessions/${id}`, { method: 'DELETE' }),
  revokeAllSessions: () => request('/profile/sessions/revoke-all', { method: 'POST' }),
  myActivity: (params) => request(`/profile/activity${qs(params)}`),

  // --- Audit ---
  listAuditLogs: (params) => request(`/audit-logs${qs(params)}`),
  auditFacets: () => request('/audit-logs/facets'),
  getAuditEntry: (id) => request(`/audit-logs/${id}`),

  // --- Reports (Phase 7) ---
  listReports: () => request('/reports'),
  reportUrl: (key, params) => `${API}/reports/${key}${qs(params)}`,
  downloadReport: (key, params) => download(`/reports/${key}${qs(params)}`),
}
