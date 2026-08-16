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

const CATEGORIES = [
  { value: 'policy', label: 'General policy' },
  { value: 'leave', label: 'Leave' },
  { value: 'payroll', label: 'Payroll' },
  { value: 'benefits', label: 'Benefits' },
  { value: 'onboarding', label: 'Onboarding' },
  { value: 'it', label: 'IT' },
  { value: 'other', label: 'Other' },
]

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
        <h1 className="text-2xl font-semibold text-slate-900">Knowledge base</h1>
        <p className="mt-1 text-sm text-slate-500">
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

      <Card title={`Documents (${documents.length})`}>
        {documents.length === 0 ? (
          <EmptyState>
            No documents yet — the assistant will escalate every question to HR.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">Title</th>
                  <th className="px-4 py-2 font-medium">Category</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Passages</th>
                  <th className="px-4 py-2 font-medium">Published</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {documents.map((doc) => (
                  <tr key={doc.id} className={doc.is_published ? '' : 'opacity-60'}>
                    <td className="px-4 py-2">
                      <span className="font-medium text-slate-900">{doc.title}</span>
                      {doc.source_reference && (
                        <p className="text-xs text-slate-500">{doc.source_reference}</p>
                      )}
                      {doc.error_message && (
                        <p className="text-xs text-red-600">{doc.error_message}</p>
                      )}
                    </td>
                    <td className="px-4 py-2 text-slate-600">{doc.category}</td>
                    <td className="px-4 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          STATUS_TONES[doc.status] ?? 'bg-slate-100 text-slate-700'
                        }`}
                      >
                        {doc.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 tabular-nums text-slate-600">
                      {doc.chunk_count}
                    </td>
                    <td className="px-4 py-2 text-slate-600">
                      {doc.is_published ? 'Yes' : 'No'}
                    </td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <button
                        onClick={() =>
                          act(
                            () =>
                              api.updateKnowledgeDocument(doc.id, {
                                is_published: !doc.is_published,
                              }),
                            doc.is_published ? 'Unpublished.' : 'Published.',
                          )
                        }
                        className="mr-3 text-xs font-medium text-slate-600 hover:text-slate-900"
                      >
                        {doc.is_published ? 'Unpublish' : 'Publish'}
                      </button>
                      <button
                        onClick={() =>
                          act(
                            () => api.reingestKnowledgeDocument(doc.id),
                            'Re-indexed.',
                          )
                        }
                        className="mr-3 text-xs font-medium text-slate-600 hover:text-slate-900"
                      >
                        Re-index
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Delete "${doc.title}" and its passages?`)) {
                            act(
                              () => api.deleteKnowledgeDocument(doc.id),
                              'Document deleted.',
                            )
                          }
                        }}
                        className="text-xs font-medium text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
