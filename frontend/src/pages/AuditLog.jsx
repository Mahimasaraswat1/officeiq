import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, EmptyState, Field, Input, Select } from '../components/ui'
import DataTable from '../components/DataTable'

const PAGE_SIZE = 50

export default function AuditLog() {
  const [filters, setFilters] = useState({
    action: '',
    actor: '',
    entity_type: '',
    date_from: '',
    date_to: '',
  })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [facets, setFacets] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    api.auditFacets().then(setFacets).catch(() => setFacets(null))
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    const params = { page, page_size: PAGE_SIZE }
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params[key] = value
    })
    return api
      .listAuditLogs(params)
      .then((result) => {
        setData(result)
        setError('')
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [filters, page])

  useEffect(() => {
    // Debounced: the actor box filters as you type.
    const timer = setTimeout(load, 250)
    return () => clearTimeout(timer)
  }, [load])

  const set = (key) => (event) => {
    setFilters((current) => ({ ...current, [key]: event.target.value }))
    setPage(1)
  }

  const clear = () => {
    setFilters({ action: '', actor: '', entity_type: '', date_from: '', date_to: '' })
    setPage(1)
  }

  const exportCsv = async () => {
    setExporting(true)
    try {
      const params = { format: 'csv' }
      Object.entries(filters).forEach(([key, value]) => {
        if (value) params[key] = value
      })
      await api.downloadReport('audit_trail', params)
    } catch (err) {
      setError(err.message)
    } finally {
      setExporting(false)
    }
  }

  const active = Object.values(filters).filter(Boolean).length

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Audit log</h1>
          <p className="mt-1 text-sm text-slate-500">
            Append-only record of every consequential action. Entries are never edited
            or deleted.
          </p>
        </div>
        <Button variant="secondary" onClick={exportCsv} loading={exporting}>
          Export matching (CSV)
        </Button>
      </div>

      <Alert>{error}</Alert>

      <Card
        title={`Filters${active ? ` (${active} active)` : ''}`}
        action={
          active > 0 && (
            <button
              type="button"
              onClick={clear}
              className="text-sm font-medium text-slate-500 hover:text-slate-900"
            >
              Clear all
            </button>
          )
        }
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Action">
            <Select value={filters.action} onChange={set('action')}>
              <option value="">All actions</option>
              {facets?.actions.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Entity">
            <Select value={filters.entity_type} onChange={set('entity_type')}>
              <option value="">All entities</option>
              {facets?.entity_types.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Actor">
            <Input
              value={filters.actor}
              onChange={set('actor')}
              placeholder="Part of an email"
            />
          </Field>
          <Field label="From">
            <Input type="date" value={filters.date_from} onChange={set('date_from')} />
          </Field>
          <Field label="To">
            <Input type="date" value={filters.date_to} onChange={set('date_to')} />
          </Field>
        </div>
      </Card>

      <div className="overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
        <DataTable
          columns={[
            {
              key: 'when',
              header: 'When',
              primary: true,
              cell: (entry) => new Date(entry.created_at).toLocaleString(),
              className: 'whitespace-nowrap text-slate-600',
            },
            {
              key: 'actor',
              header: 'Actor',
              cell: (entry) => (
                <>
                  {entry.actor_email ?? '—'}
                  {entry.actor_role && (
                    <span className="ml-1 text-xs text-slate-500 uppercase">
                      {entry.actor_role}
                    </span>
                  )}
                </>
              ),
              className: 'text-slate-600',
            },
            {
              key: 'action',
              header: 'Action',
              cell: (entry) => entry.action,
              className: 'font-medium text-slate-900',
            },
            {
              key: 'entity',
              header: 'Entity',
              cell: (entry) => entry.entity_type ?? '—',
              className: 'text-slate-600',
            },
            {
              key: 'ip',
              header: 'IP',
              cell: (entry) => entry.ip_address ?? '—',
              className: 'text-xs text-slate-500',
            },
            {
              key: 'detail',
              header: 'Detail',
              // Truncated JSON is unreadable on a phone, and the card already
              // opens the drawer where it is shown in full.
              hideOnMobile: true,
              cell: (entry) => (entry.detail ? JSON.stringify(entry.detail) : '—'),
              className: 'max-w-xs truncate text-xs text-slate-500',
            },
          ]}
          rows={data?.items ?? []}
          rowKey={(entry) => entry.id}
          onRowClick={setSelected}
          rowLabel={(entry) => `View audit entry: ${entry.action}`}
          loading={loading}
          skeletonRows={8}
          empty={
            <EmptyState icon="🗂️" title="Nothing recorded">
              {active > 0
                ? 'No entries match these filters — try widening the date range.'
                : 'Sign-ins, approvals and exports will appear here as they happen.'}
            </EmptyState>
          }
        />
      </div>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">
            Page {data.page} of {data.pages} · {data.total} entries
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
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

      {selected && <EntryDetail entry={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

/** Truncated JSON in a table cell is unreadable; the full entry gets a panel. */
function EntryDetail({ entry, onClose }) {
  const panelRef = useRef(null)
  const closeRef = useRef(null)
  // Where focus was before the drawer opened, so it can be handed back.
  const openerRef = useRef(null)

  useEffect(() => {
    openerRef.current = document.activeElement
    closeRef.current?.focus()

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return

      // Keep Tab inside the drawer. Without this, focus walks off into the
      // page behind it, which for a screen-reader or keyboard user means the
      // dialog is open but they are silently somewhere else.
      const focusable = panelRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
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
      // Returning focus to the row that opened the drawer means the reader
      // resumes where they were, not at the top of the document.
      openerRef.current?.focus?.()
    }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-slate-900/20"
      onClick={onClose}
      role="presentation"
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-entry-title"
        className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <h2 id="audit-entry-title" className="text-lg font-semibold text-slate-900">
            {entry.action}
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          >
            ✕
          </button>
        </div>

        <dl className="mt-4 space-y-3 text-sm">
          <Row label="When" value={new Date(entry.created_at).toLocaleString()} />
          <Row label="Actor" value={entry.actor_email} />
          <Row label="Role" value={entry.actor_role} />
          <Row label="Entity type" value={entry.entity_type} />
          <Row label="Entity id" value={entry.entity_id} mono />
          <Row label="IP address" value={entry.ip_address} />
          <Row label="User agent" value={entry.user_agent} />
        </dl>

        <h3 className="mt-6 text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Detail
        </h3>
        <pre className="mt-2 overflow-x-auto rounded-md bg-slate-50 p-3 text-xs text-slate-700 ring-1 ring-slate-200">
          {entry.detail ? JSON.stringify(entry.detail, null, 2) : 'No additional detail.'}
        </pre>
      </aside>
    </div>
  )
}

function Row({ label, value, mono }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className={`col-span-2 break-words text-slate-900 ${mono ? 'font-mono text-xs' : ''}`}>
        {value || '—'}
      </dd>
    </div>
  )
}
