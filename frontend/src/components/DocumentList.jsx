import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, EmptyState, Spinner } from './ui'
import ExtractionReview from './ExtractionReview'
import DocumentReviewActions from './DocumentReviewActions'
import { DOCUMENT_TYPES } from './DocumentUpload'

const TYPE_LABEL = Object.fromEntries(DOCUMENT_TYPES.map((t) => [t.value, t.label]))

const STATUS_TONES = {
  uploaded: 'bg-slate-100 text-slate-700',
  processing: 'bg-sky-100 text-sky-800',
  extracted: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-100 text-red-800',
  approved: 'bg-emerald-100 text-emerald-800',
  rejected: 'bg-red-100 text-red-800',
}

const formatSize = (bytes) =>
  bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`

function DocumentRow({ summary, canManage, canApply, canReview, onChanged }) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const loadDetail = useCallback(async () => {
    setLoading(true)
    try {
      setDetail(await api.getDocument(summary.id))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [summary.id])

  const toggle = () => {
    const next = !expanded
    setExpanded(next)
    if (next && !detail) loadDetail()
  }

  const view = async () => {
    setError('')
    try {
      const { url } = await api.getDownloadUrl(summary.id)
      window.open(url, '_blank', 'noopener')
    } catch (err) {
      setError(err.message)
    }
  }

  const reprocess = async () => {
    setBusy(true)
    setError('')
    try {
      setDetail(await api.reprocessDocument(summary.id))
      onChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!confirm(`Delete "${summary.original_filename}"? This cannot be undone.`)) return
    setBusy(true)
    setError('')
    try {
      await api.deleteDocument(summary.id)
      onChanged?.()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-slate-900">
              {TYPE_LABEL[summary.document_type] ?? summary.document_type}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                STATUS_TONES[summary.status] ?? 'bg-slate-100 text-slate-700'
              }`}
            >
              {summary.status}
            </span>
            {summary.ocr_confidence != null && (
              <span className="text-xs text-slate-500">
                OCR {Math.round(summary.ocr_confidence * 100)}%
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {summary.original_filename} · {formatSize(summary.size_bytes)} ·{' '}
            {new Date(summary.created_at).toLocaleString()}
          </p>
        </div>

        <div className="flex shrink-0 gap-2">
          <Button variant="secondary" onClick={view}>
            View
          </Button>
          <Button variant="secondary" onClick={toggle}>
            {expanded ? 'Hide' : 'Review'}
          </Button>
          {canManage && (
            <>
              <Button variant="secondary" onClick={reprocess} disabled={busy}>
                Re-run
              </Button>
              <Button variant="danger" onClick={remove} disabled={busy}>
                Delete
              </Button>
            </>
          )}
        </div>
      </div>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {expanded && (
        <div className="mt-4 border-t border-slate-100 pt-4">
          {loading && <Spinner label="Loading extraction…" />}
          {!loading && detail && (
            <div className="space-y-5">
              <ExtractionReview
                document={detail}
                canApply={canApply}
                onChanged={() => {
                  loadDetail()
                  onChanged?.()
                }}
              />
              {canReview && (
                <div className="border-t border-slate-100 pt-4">
                  <h4 className="mb-2 text-sm font-semibold text-slate-900">HR decision</h4>
                  <DocumentReviewActions
                    document={detail}
                    onReviewed={() => {
                      loadDetail()
                      onChanged?.()
                    }}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  )
}

export default function DocumentList({
  employeeId,
  canManage = false,
  canApply = true,
  canReview = false,
  refreshKey,
  onChanged: onListChanged,
}) {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments(employeeId))
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [employeeId])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  // Extraction runs in the background, so poll briefly while anything is pending.
  useEffect(() => {
    const pending = documents.some((d) => d.status === 'uploaded' || d.status === 'processing')
    if (!pending) return
    const timer = setTimeout(load, 2000)
    return () => clearTimeout(timer)
  }, [documents, load])

  if (loading) return <Spinner />

  return (
    <div className="space-y-3">
      <Alert>{error}</Alert>
      {documents.length === 0 ? (
        <EmptyState icon="📄" title="No documents yet">
          Upload an Aadhaar card, PAN card and photograph to start verification.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg bg-white ring-1 ring-slate-200">
          {documents.map((doc) => (
            <DocumentRow
              key={doc.id}
              summary={doc}
              canManage={canManage}
              canApply={canApply}
              canReview={canReview}
              onChanged={() => {
                load()
                onListChanged?.()
              }}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
