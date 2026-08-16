import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Button, EmptyState, Input, Select, StatusBadge } from '../components/ui'
import DataTable from '../components/DataTable'

const STATUSES = [
  'invited',
  'registered',
  'documents_pending',
  'documents_submitted',
  'under_review',
  'tasks_assigned',
  'complete',
  'rejected',
]

const columns = [
  {
    key: 'employee',
    header: 'Employee',
    primary: true,
    cell: (employee) => (
      <>
        <Link
          to={`/employees/${employee.id}`}
          className="font-medium text-slate-900 hover:underline"
        >
          {employee.first_name} {employee.last_name}
        </Link>
        <p className="text-xs text-slate-500">{employee.work_email}</p>
      </>
    ),
  },
  { key: 'code', header: 'Code', cell: (e) => e.employee_code, className: 'text-slate-600' },
  {
    key: 'department',
    header: 'Department',
    cell: (e) => e.department ?? '—',
    className: 'text-slate-600',
  },
  { key: 'status', header: 'Status', cell: (e) => <StatusBadge status={e.onboarding_status} /> },
  {
    key: 'joining',
    header: 'Joining',
    cell: (e) => e.date_of_joining ?? '—',
    className: 'text-slate-600',
  },
]

export default function EmployeeList() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    // Debounce so typing in the search box doesn't fire a request per keystroke.
    const timer = setTimeout(() => {
      api
        .listEmployees({ search, onboarding_status: status, page, page_size: 20 })
        .then((result) => !cancelled && setData(result))
        .catch((err) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setLoading(false))
    }, 250)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [search, status, page])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Employees</h1>
          <p className="mt-1 text-sm text-slate-500">
            {data ? `${data.total} record${data.total === 1 ? '' : 's'}` : 'Loading…'}
          </p>
        </div>
        <Link to="/employees/new">
          <Button>Add employee</Button>
        </Link>
      </div>

      <Alert>{error}</Alert>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Input
          placeholder="Search by name, code, or email…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          className="sm:max-w-xs"
        />
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
          className="sm:max-w-48"
        >
          <option value="">All statuses</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {value.replaceAll('_', ' ')}
            </option>
          ))}
        </Select>
      </div>

      <div className="overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(employee) => employee.id}
          loading={loading}
          empty={
            search || status ? (
              <EmptyState icon="🔍" title="No matches">
                No employees match these filters. Try a different search or clear the
                status filter.
              </EmptyState>
            ) : (
              <EmptyState
                icon="👥"
                title="No employees yet"
                action={
                  <Link to="/employees/new">
                    <Button>Add employee</Button>
                  </Link>
                }
              >
                Create a profile and OfficeIQ will email an invitation to complete
                onboarding.
              </EmptyState>
            )
          }
        />
      </div>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">
            Page {data.page} of {data.pages}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              disabled={page >= data.pages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
