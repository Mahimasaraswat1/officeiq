import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, EmptyState, Spinner } from './ui'
import { useToast } from './Toast'

const CHECK_LABEL = { aadhaar: 'Aadhaar', pan: 'PAN' }

const REASON_LABEL = {
  verified: 'Verified',
  missing_number: 'No number could be read',
  invalid_format: 'Invalid format',
  checksum_failed: 'Checksum failed — likely a misread digit',
  not_found_in_registry: 'Not found in the registry',
  name_mismatch: 'Name does not match the profile',
  dob_mismatch: 'Date of birth does not match',
}

const FACE_LABEL = {
  matched: 'Face matched',
  not_matched: 'Face did not match',
  no_face_in_photo: 'No face found in the photo',
  no_face_in_id: 'No face found on the ID',
  multiple_faces_in_photo: 'Multiple faces in the photo',
  error: 'Face match could not run',
}

function StatusPill({ ok, warn, children }) {
  const tone = ok
    ? 'bg-emerald-100 text-emerald-800'
    : warn
      ? 'bg-amber-100 text-amber-800'
      : 'bg-red-100 text-red-800'
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{children}</span>
}

function SimilarityBar({ value, threshold }) {
  const percent = Math.round((value ?? 0) * 100)
  const mark = Math.round((threshold ?? 0) * 100)
  const passed = (value ?? 0) >= (threshold ?? 0)

  return (
    <div className="mt-2">
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full rounded-full ${passed ? 'bg-emerald-500' : 'bg-red-500'}`}
          style={{ width: `${percent}%` }}
        />
        {/* Threshold marker, so the score is readable against the bar it is judged by. */}
        <div
          className="absolute top-0 h-full w-0.5 bg-slate-700"
          style={{ left: `${mark}%` }}
          title={`Pass threshold ${threshold}`}
        />
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Similarity {(value ?? 0).toFixed(3)} · threshold {(threshold ?? 0).toFixed(3)}
      </p>
    </div>
  )
}

export default function VerificationPanel({ employeeId, onChanged }) {
  const toast = useToast()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setSummary(await api.verificationSummary(employeeId))
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [employeeId])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn, successMessage) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      toast.success(successMessage)
      await load()
      onChanged?.()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Spinner label="Loading verification status…" />

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>

      <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
        Aadhaar and PAN checks run against a <strong>simulated registry</strong>. No
        government API is contacted in this version.
      </div>

      {/* --- ID checks --- */}
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">ID verification</h3>
        {summary.id_checks.length === 0 ? (
          <EmptyState icon="🪪" title="No ID checks yet">
            A check runs automatically once an Aadhaar or PAN document finishes
            extraction.
          </EmptyState>
        ) : (
          <ul className="space-y-2">
            {summary.id_checks.map((check) => (
              <li
                key={check.id}
                className="rounded-lg px-4 py-3 ring-1 ring-slate-200"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-900">
                      {CHECK_LABEL[check.check_type] ?? check.check_type}
                    </span>
                    <StatusPill ok={check.status === 'passed'}>{check.status}</StatusPill>
                  </div>
                  <span className="font-mono text-xs text-slate-500">
                    {check.masked_number}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-600">
                  {REASON_LABEL[check.reason_code] ?? check.reason_code}
                  {check.message ? ` — ${check.message}` : ''}
                </p>
                {check.reference_id && (
                  <p className="mt-0.5 font-mono text-xs text-slate-500">
                    ref {check.reference_id}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* --- Face match --- */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">Face match</h3>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => act(() => api.runFaceMatch(employeeId), 'Face match complete.')}
          >
            {summary.face_match ? 'Re-run' : 'Run face match'}
          </Button>
        </div>

        {!summary.face_match ? (
          <EmptyState>
            Not run yet. Needs both a passport photo and an Aadhaar or PAN document.
          </EmptyState>
        ) : (
          <div className="rounded-lg px-4 py-3 ring-1 ring-slate-200">
            <div className="flex items-center gap-2">
              <StatusPill
                ok={summary.face_match.status === 'matched'}
                warn={summary.face_match.status.startsWith('no_face') ||
                      summary.face_match.status === 'multiple_faces_in_photo'}
              >
                {FACE_LABEL[summary.face_match.status] ?? summary.face_match.status}
              </StatusPill>
              {summary.face_match.engine && (
                <span className="text-xs text-slate-500">
                  via {summary.face_match.engine}
                </span>
              )}
            </div>
            {summary.face_match.similarity != null && (
              <SimilarityBar
                value={summary.face_match.similarity}
                threshold={summary.face_match.threshold}
              />
            )}
            {summary.face_match.message && (
              <p className="mt-1 text-xs text-slate-600">{summary.face_match.message}</p>
            )}
          </div>
        )}
      </section>

      {/* --- Readiness --- */}
      <section className="rounded-lg bg-slate-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-slate-900">
              {summary.documents_approved} of {summary.documents_total} document
              {summary.documents_total === 1 ? '' : 's'} approved
              {summary.documents_rejected > 0 && ` · ${summary.documents_rejected} rejected`}
            </p>
            <p className="text-xs text-slate-500">
              Current stage: {summary.onboarding_status.replaceAll('_', ' ')}
            </p>
          </div>
          <Button
            disabled={busy || !summary.ready_for_completion}
            onClick={() =>
              act(() => api.completeOnboarding(employeeId), 'Onboarding marked complete.')
            }
          >
            Mark onboarding complete
          </Button>
        </div>

        {summary.blocking_issues.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Outstanding before completion
            </p>
            <ul className="mt-1 list-inside list-disc text-xs text-slate-600">
              {summary.blocking_issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  )
}
