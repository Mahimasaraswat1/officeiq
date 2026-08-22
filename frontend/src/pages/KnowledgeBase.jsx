import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Select,
  Spinner,
  Stat,
} from '../components/ui'
import { useToast } from '../components/Toast'
import ConfirmDialog from '../components/ConfirmDialog'

const CATEGORIES = [
  { value: 'policy', label: 'General policy' },
  { value: 'leave', label: 'Leave' },
  { value: 'payroll', label: 'Payroll' },
  { value: 'benefits', label: 'Benefits' },
  { value: 'onboarding', label: 'Onboarding' },
  { value: 'it', label: 'IT' },
  { value: 'other', label: 'Other' },
]

/**
 * Colour per category.
 *
 * The reference design colour-codes by *file type* (PDF, DOC, Sheet, Slides).
 * These documents have no file type: they are text stored in the database and
 * chunked for retrieval, not uploaded files. Category is the real
 * classification, so the colour keys off that — and every tile shows the
 * category name too, so the colour is never the only signal.
 */
const CATEGORY_STYLE = {
  policy: { tile: 'bg-navy-100 text-navy-700', dot: 'bg-navy-500' },
  leave: { tile: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
  payroll: { tile: 'bg-amber-50 text-amber-700', dot: 'bg-amber-500' },
  benefits: { tile: 'bg-violet-50 text-violet-700', dot: 'bg-violet-500' },
  onboarding: { tile: 'bg-accent-50 text-accent-700', dot: 'bg-accent-600' },
  it: { tile: 'bg-cyan-50 text-cyan-700', dot: 'bg-cyan-500' },
  other: { tile: 'bg-slate-100 text-slate-700', dot: 'bg-slate-400' },
}

const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label]))

const VIEW_KEY = 'officeiq.library_view'

const STATUS_TONES = {
  pending: 'bg-slate-100 text-slate-700',
  ingesting: 'bg-sky-100 text-sky-800',
  ready: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-100 text-red-800',
}

const BLANK = {
  title: '',
  category: 'policy',
  source_reference: '',
  version: '',
  content: '',
  is_published: true,
}

const clean = (obj) =>
  Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== '' && v !== undefined))

function DocumentForm({ onCreated }) {
  const [form, setForm] = useState(BLANK)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const update = (field) => (e) =>
    setForm({ ...form, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const created = await api.createKnowledgeDocument({
        ...clean(form),
        is_published: form.is_published,
      })
      setForm(BLANK)
      onCreated?.(created)
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Title">
          <Input value={form.title} onChange={update('title')} required />
        </Field>
        <Field label="Category">
          <Select value={form.category} onChange={update('category')}>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Source reference" hint="Shown beside answers, e.g. 'Handbook §4.1'">
          <Input value={form.source_reference} onChange={update('source_reference')} />
        </Field>
        <Field label="Version">
          <Input value={form.version} onChange={update('version')} placeholder="2026.1" />
        </Field>
      </div>

      <Field
        label="Policy text"
        hint="Keep ALL-CAPS or Markdown headings — the text is split on them, so answers can cite the right section."
      >
        <textarea
          value={form.content}
          onChange={update('content')}
          rows={12}
          required
          placeholder={'ANNUAL LEAVE ENTITLEMENT\n\nFull-time employees receive 21 days…'}
          className="w-full rounded-md border-0 px-3 py-2 font-mono text-xs text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-inset focus:ring-slate-900"
        />
      </Field>

      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={form.is_published}
          onChange={update('is_published')}
          className="h-4 w-4 rounded border-slate-300"
        />
        Published — unpublished documents are never used to answer questions
      </label>

      <div className="flex justify-end">
        <Button type="submit" loading={busy}>
          Add document
        </Button>
      </div>
    </form>
  )
}

function SearchPreview() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState(false)

  const run = async (event) => {
    event.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    try {
      setResults(await api.searchKnowledge({ query, top_k: 5 }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        See exactly which passages a question retrieves — the fastest way to diagnose a
        wrong or missing answer.
      </p>
      <form onSubmit={run} className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. how many leave days can I carry forward"
        />
        <Button type="submit" loading={busy}>
          Search
        </Button>
      </form>

      {results && (
        <div className="space-y-2">
          {results.total === 0 ? (
            <EmptyState>
              Nothing matched above the relevance threshold — the assistant would escalate
              this question to HR.
            </EmptyState>
          ) : (
            results.results.map((r) => (
              <div key={r.chunk_id} className="rounded-md bg-slate-50 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-900">
                    {r.document_title}
                    {r.heading ? ` — ${r.heading}` : ''}
                  </span>
                  <span className="text-xs tabular-nums text-slate-500">
                    similarity {r.similarity.toFixed(3)}
                  </span>
                </div>
                <p className="mt-1 line-clamp-3 text-xs whitespace-pre-line text-slate-600">
                  {r.content}
                </p>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/**
 * A document indexed by the local hashing embedder is *not* searchable in any
 * meaningful sense — it matches words, not meaning — yet its status still
 * reads "ready". That combination once hid a knowledge base that silently
 * answered nothing, so the placeholder index is called out explicitly
 * wherever the status appears.
 *
 * `embedding_model` is the honest signal: "voyage:voyage-3" is a real model,
 * "local:n/a" is the test stub, and null means it was never embedded at all.
 */
const isPlaceholderIndex = (doc) =>
  !doc.embedding_model || doc.embedding_model.startsWith('local:')

/**
 * Documents that cannot be retrieved, and why.
 *
 * A document's vectors belong to whichever embedder produced them. When the
 * active embedder differs, the two live in unrelated vector spaces and no
 * similarity threshold can match them — search returns nothing while the
 * document still reports "ready". That combination is impossible to diagnose
 * from the UI, so it is stated here in the terms needed to fix it.
 */
function StaleIndexBanner({ documents, activeProvider }) {
  const affected = documents.filter((doc) => {
    if (!doc.embedding_model) return true
    if (!activeProvider) return isPlaceholderIndex(doc)
    return !doc.embedding_model.startsWith(`${activeProvider}:`)
  })
  if (affected.length === 0) return null

  const onLocal = activeProvider === 'local'
  const count = affected.length

  return (
    <div
      role="status"
      className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900 ring-1 ring-amber-200"
    >
      <p className="font-semibold">
        {count} document{count === 1 ? '' : 's'}{' '}
        {onLocal
          ? 'indexed with the local test embedder'
          : `indexed by a different embedder than the active one (${activeProvider})`}
      </p>
      <p className="mt-1 text-amber-800">
        {onLocal ? (
          <>
            Their status says “ready”, but the local embedder matches wording rather
            than meaning, so the assistant will usually fail to retrieve them. Set{' '}
            <code className="rounded bg-amber-100 px-1">VOYAGE_API_KEY</code> and{' '}
            <code className="rounded bg-amber-100 px-1">EMBEDDING_PROVIDER=voyage</code>,
            then re-index each one.
          </>
        ) : (
          <>
            Their status says “ready”, but the assistant cannot find them at any
            threshold — their vectors came from a different model. Re-index them, or
            switch back to the embedder that produced them.
          </>
        )}
      </p>
      <p className="mt-1.5 text-xs text-amber-800">
        Affected:{' '}
        {affected
          .map((d) => `${d.title} [${d.embedding_model || 'never embedded'}]`)
          .join(', ')}
      </p>
    </div>
  )
}
const DOC_ICON = <path d="M5 2h7l3 3v13H5V2zm6 1.5V6h2.5L11 3.5zM7 9h6v1.5H7V9zm0 3h6v1.5H7V12z" />

/**
 * The document library: search, category filters, and a grid/list toggle.
 *
 * Filtering and search run client-side because the endpoint returns the whole
 * collection in one response — there is no pagination to respect, and doing it
 * here keeps typing instant.
 */
function DocumentLibrary({ documents, onAct }) {
  const [view, setView] = useState(
    () => localStorage.getItem(VIEW_KEY) || 'grid',
  )
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [deleting, setDeleting] = useState(null)

  const chooseView = (next) => {
    setView(next)
    // Remembered, so the choice survives a reload.
    localStorage.setItem(VIEW_KEY, next)
  }

  const term = search.trim().toLowerCase()
  const visible = documents.filter((doc) => {
    if (category && doc.category !== category) return false
    if (!term) return true
    return (
      doc.title.toLowerCase().includes(term) ||
      (doc.source_reference ?? '').toLowerCase().includes(term)
    )
  })

  const countFor = (value) =>
    value ? documents.filter((doc) => doc.category === value).length : documents.length

  const actions = (doc) => (
    <>
      <button
        type="button"
        onClick={() =>
          onAct(
            () => api.updateKnowledgeDocument(doc.id, { is_published: !doc.is_published }),
            doc.is_published ? 'Unpublished.' : 'Published.',
          )
        }
        className="rounded-lg px-2 py-1 text-xs font-semibold text-navy-600 transition hover:bg-navy-100 hover:text-navy-900"
      >
        {doc.is_published ? 'Unpublish' : 'Publish'}
      </button>
      <button
        type="button"
        onClick={() => onAct(() => api.reingestKnowledgeDocument(doc.id), 'Re-indexed.')}
        className="rounded-lg px-2 py-1 text-xs font-semibold text-navy-600 transition hover:bg-navy-100 hover:text-navy-900"
      >
        Re-index
      </button>
      <button
        type="button"
        onClick={() => setDeleting(doc)}
        className="rounded-lg px-2 py-1 text-xs font-semibold text-red-600 transition hover:bg-red-50"
      >
        Delete
      </button>
    </>
  )

  const Meta = ({ doc }) => (
    <div className="flex flex-wrap items-center gap-1.5">
      {/* A placeholder index must never wear the reassuring green "ready". */}
      <span
        title={
          isPlaceholderIndex(doc)
            ? `Indexed with ${doc.embedding_model ?? 'no embedder'} — not reliably searchable`
            : `Indexed with ${doc.embedding_model}`
        }
        className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
          isPlaceholderIndex(doc) && doc.status === 'ready'
            ? 'bg-amber-100 text-amber-900'
            : (STATUS_TONES[doc.status] ?? 'bg-navy-100 text-navy-700')
        }`}
      >
        {isPlaceholderIndex(doc) && doc.status === 'ready' ? 'not searchable' : doc.status}
      </span>
      {isPlaceholderIndex(doc) && (
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">
          {doc.embedding_model ?? 'never embedded'}
        </span>
      )}
      <span className="text-xs text-navy-500">
        {doc.chunk_count} passage{doc.chunk_count === 1 ? '' : 's'}
      </span>
      {!doc.is_published && (
        <span className="rounded-full bg-navy-100 px-2 py-0.5 text-xs font-semibold text-navy-600">
          Draft
        </span>
      )}
    </div>
  )

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-bold tracking-tight text-navy-900">
            Document library
          </h2>
          <p className="text-sm text-navy-500">
            {visible.length} of {documents.length} document
            {documents.length === 1 ? '' : 's'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search documents…"
            aria-label="Search documents"
            className="w-48 rounded-xl sm:w-64"
          />
          {/* Grid / list toggle */}
          <div
            role="group"
            aria-label="View style"
            className="flex rounded-xl bg-navy-100 p-0.5"
          >
            {[
              { key: 'grid', label: 'Grid', icon: <path d="M3 3h6v6H3V3zm8 0h6v6h-6V3zM3 11h6v6H3v-6zm8 0h6v6h-6v-6z" /> },
              { key: 'list', label: 'List', icon: <path d="M3 4h14v2H3V4zm0 5h14v2H3V9zm0 5h14v2H3v-2z" /> },
            ].map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => chooseView(option.key)}
                aria-pressed={view === option.key}
                aria-label={`${option.label} view`}
                className={`rounded-[10px] p-1.5 transition ${
                  view === option.key
                    ? 'bg-white text-navy-900 shadow-card'
                    : 'text-navy-500 hover:text-navy-800'
                }`}
              >
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4" aria-hidden="true">
                  {option.icon}
                </svg>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Category filters — the real folders these documents have. */}
      <div className="flex flex-wrap gap-2">
        {[{ value: '', label: 'All' }, ...CATEGORIES].map((option) => {
          const active = category === option.value
          const count = countFor(option.value)
          return (
            <button
              key={option.value || 'all'}
              type="button"
              onClick={() => setCategory(option.value)}
              aria-pressed={active}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition duration-200 ${
                active
                  ? 'bg-navy-900 text-white shadow-card'
                  : 'bg-white text-navy-600 ring-1 ring-navy-100 hover:-translate-y-0.5 hover:shadow-card'
              }`}
            >
              {option.value && (
                <span
                  aria-hidden="true"
                  className={`h-2 w-2 rounded-full ${CATEGORY_STYLE[option.value]?.dot ?? 'bg-navy-400'}`}
                />
              )}
              {option.label}
              <span className={active ? 'text-navy-300' : 'text-navy-400'}>{count}</span>
            </button>
          )
        })}
      </div>

      {visible.length === 0 ? (
        <div className="rounded-2xl bg-white shadow-card ring-1 ring-navy-100/70">
          <EmptyState
            icon={documents.length === 0 ? '📚' : '🔍'}
            title={documents.length === 0 ? 'No documents yet' : 'No matches'}
          >
            {documents.length === 0
              ? 'Without documents the assistant escalates every question to HR.'
              : 'Try a different search term or clear the category filter.'}
          </EmptyState>
        </div>
      ) : view === 'grid' ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((doc) => (
            <article
              key={doc.id}
              className={`flex flex-col rounded-2xl bg-white p-5 shadow-card ring-1 ring-navy-100/70 transition duration-200 hover:-translate-y-0.5 hover:shadow-card-hover ${
                doc.is_published ? '' : 'opacity-75'
              }`}
            >
              <div className="flex items-start gap-3">
                <span
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
                    CATEGORY_STYLE[doc.category]?.tile ?? CATEGORY_STYLE.other.tile
                  }`}
                >
                  <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
                    {DOC_ICON}
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate font-semibold text-navy-900" title={doc.title}>
                    {doc.title}
                  </h3>
                  <p className="text-xs font-medium text-navy-500">
                    {CATEGORY_LABEL[doc.category] ?? doc.category}
                    {doc.version ? ` · ${doc.version}` : ''}
                  </p>
                </div>
              </div>

              {doc.source_reference && (
                <p className="mt-3 truncate text-xs text-navy-500" title={doc.source_reference}>
                  {doc.source_reference}
                </p>
              )}
              {doc.error_message && (
                <p className="mt-2 rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700">
                  {doc.error_message}
                </p>
              )}

              <div className="mt-3">
                <Meta doc={doc} />
              </div>

              <div className="mt-4 flex flex-wrap gap-1 border-t border-navy-100 pt-3">
                {actions(doc)}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-navy-100/70">
          <ul className="divide-y divide-navy-100">
            {visible.map((doc) => (
              <li
                key={doc.id}
                className={`flex flex-col gap-3 p-4 transition hover:bg-navy-50/60 sm:flex-row sm:items-center ${
                  doc.is_published ? '' : 'opacity-75'
                }`}
              >
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                    CATEGORY_STYLE[doc.category]?.tile ?? CATEGORY_STYLE.other.tile
                  }`}
                >
                  <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
                    {DOC_ICON}
                  </svg>
                </span>

                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-navy-900">{doc.title}</p>
                  <p className="truncate text-xs text-navy-500">
                    {CATEGORY_LABEL[doc.category] ?? doc.category}
                    {doc.source_reference ? ` · ${doc.source_reference}` : ''}
                  </p>
                  {doc.error_message && (
                    <p className="mt-1 text-xs text-red-700">{doc.error_message}</p>
                  )}
                </div>

                <div className="sm:w-52">
                  <Meta doc={doc} />
                </div>

                <div className="flex flex-wrap gap-1 sm:justify-end">{actions(doc)}</div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete "${deleting.title}"?`}
          confirmLabel="Delete document"
          tone="danger"
          onConfirm={() => {
            onAct(() => api.deleteKnowledgeDocument(deleting.id), 'Document deleted.')
            setDeleting(null)
          }}
          onCancel={() => setDeleting(null)}
        >
          <p>
            Its {deleting.chunk_count} indexed passage
            {deleting.chunk_count === 1 ? '' : 's'} will be removed too, so the assistant
            can no longer answer from it.
          </p>
        </ConfirmDialog>
      )}
    </section>
  )
}

export default function KnowledgeBase() {
  const toast = useToast()
  const [documents, setDocuments] = useState([])
  const [stats, setStats] = useState(null)
  const [analytics, setAnalytics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [docs, statsRow, analyticsRow] = await Promise.all([
        api.listKnowledgeDocuments(),
        api.knowledgeStats(),
        api.chatAnalytics().catch(() => null),
      ])
      setDocuments(docs)
      setStats(statsRow)
      setAnalytics(analyticsRow)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn, message) => {
    setError('')
    try {
      await fn()
      toast.success(message)
      await load()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">Knowledge base</h1>
        <p className="mt-1 text-sm text-navy-500">
          What the AI assistant is allowed to answer from. Adding or editing a document
          re-indexes it immediately.
        </p>
      </div>

      <Alert>{error}</Alert>

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Documents indexed" value={stats?.documents_ready ?? 0} />
        <Stat label="Searchable passages" value={stats?.chunks_total ?? 0} />
        <Stat
          label="Resolved without HR"
          value={
            analytics && analytics.questions_total
              ? `${Math.round(analytics.resolution_rate * 100)}%`
              : '—'
          }
        />
        <Stat label="Escalated to HR" value={analytics?.escalated ?? 0} />
      </dl>

      {stats && (
        <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Embeddings: <strong>{stats.embedding_provider}</strong> · Generation:{' '}
          <strong>{stats.chat_provider}</strong> ({stats.chat_model})
          {stats.embedding_provider === 'local' && (
            <span className="ml-2 text-amber-700">
              — local embedder in use; set VOYAGE_API_KEY for production-quality retrieval.
            </span>
          )}
        </div>
      )}

      <Card title="Test retrieval">
        <SearchPreview />
      </Card>

      <Card title="Add a document">
        <DocumentForm
          onCreated={(doc) => {
            toast.success(
              doc.status === 'ready'
                ? `"${doc.title}" indexed into ${doc.chunk_count} passage(s).`
                : `"${doc.title}" added — indexing ${doc.status}.`,
            )
            load()
          }}
        />
      </Card>

      <StaleIndexBanner documents={documents} activeProvider={stats?.embedding_provider} />

      <DocumentLibrary documents={documents} onAct={act} />

    </div>
  )
}
