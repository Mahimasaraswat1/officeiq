/**
 * Report downloads. The catalogue is role-filtered server-side, so this page
 * only ever renders reports the signed-in user can actually run.
 */

import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, Field, Input, Select, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'

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

const FORMAT_LABELS = {
  xlsx: 'Excel',
  pdf: 'PDF',
  csv: 'CSV',
}

const FORMAT_HINTS = {
  xlsx: 'Filtered and frozen headers — best for sorting and pivoting.',
  pdf: 'Formatted for printing or attaching to a compliance pack.',
  csv: 'Plain table, no title block — best for importing elsewhere.',
}

export default function Reports() {
  const toast = useToast()
  const [catalogue, setCatalogue] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  // Employee-scoped filters, shared by the reports that support them.
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  // Audit-scoped filters.
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  useEffect(() => {
    api
      .listReports()
      .then(setCatalogue)
      .catch((err) => setError(err.message))
  }, [])

  const run = async (spec, format) => {
    setBusy(`${spec.key}:${format}`)
    setError('')
    try {
      const params = { format }
      if (spec.supports_employee_filters) {
        if (department) params.department = department
        if (status) params.status = status
      }
      if (spec.supports_audit_filters) {
        if (action) params.action = action
        if (actor) params.actor = actor
      }
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo

      const filename = await api.downloadReport(spec.key, params)
      toast.success(`Downloaded ${filename}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  if (!catalogue && !error) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
        <p className="mt-1 text-sm text-slate-500">
          Export onboarding data as a spreadsheet or a document. Every export is
          recorded in the audit log.
        </p>
      </div>

      <Alert>{error}</Alert>

      <Card title="Filters">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Department" hint="Applies to employee reports.">
            <Input
              value={department}
              onChange={(event) => setDepartment(event.target.value)}
              placeholder="All departments"
            />
          </Field>
          <Field label="Onboarding status">
            <Select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">All statuses</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value.replaceAll('_', ' ')}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Action" hint="Applies to the audit trail.">
            <Input
              value={action}
              onChange={(event) => setAction(event.target.value)}
              placeholder="e.g. document_approved"
            />
          </Field>
          <Field label="Actor" hint="Applies to the audit trail.">
            <Input
              value={actor}
              onChange={(event) => setActor(event.target.value)}
              placeholder="Part of an email address"
            />
          </Field>
          <Field label="From date">
            <Input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
            />
          </Field>
          <Field label="To date">
            <Input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
            />
          </Field>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          A report only uses the filters it supports — each card below says which.
        </p>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {catalogue?.reports.map((spec) => (
          <section
            key={spec.key}
            className="flex flex-col justify-between rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200"
          >
            <div>
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-900">{spec.label}</h2>
                {spec.admin_only && (
                  <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800">
                    Admin only
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-slate-600">{spec.description}</p>
              <p className="mt-2 text-xs text-slate-500">
                Uses:{' '}
                {[
                  spec.supports_employee_filters && 'department, status',
                  spec.supports_audit_filters && 'action, actor',
                  'date range',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {spec.formats.map((format) => (
                <Button
                  key={format}
                  variant="secondary"
                  title={FORMAT_HINTS[format]}
                  loading={busy === `${spec.key}:${format}`}
                  disabled={busy !== ''}
                  onClick={() => run(spec, format)}
                >
                  {FORMAT_LABELS[format] ?? format}
                </Button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
