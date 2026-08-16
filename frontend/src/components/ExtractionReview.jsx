import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Input } from './ui'

const FIELD_LABELS = {
  aadhaar_number: 'Aadhaar number',
  pan_number: 'PAN number',
  full_name: 'Full name',
  father_name: "Father's name",
  date_of_birth: 'Date of birth',
  gender: 'Gender',
  postal_code: 'PIN code',
  phone: 'Phone',
  email: 'Email',
  address_line1: 'Address',
  city: 'City',
  state: 'State',
}

const label = (name) => FIELD_LABELS[name] ?? name.replaceAll('_', ' ')

/** Confidence rendered as a bar + percentage, so HR can triage at a glance. */
function ConfidenceMeter({ value, low }) {
  const percent = Math.round((value ?? 0) * 100)
  const tone = low ? 'bg-amber-500' : percent >= 90 ? 'bg-emerald-500' : 'bg-sky-500'

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${percent}%` }} />
      </div>
      <span className={`text-xs tabular-nums ${low ? 'text-amber-700' : 'text-slate-500'}`}>
        {percent}%
      </span>
    </div>
  )
}

function FieldRow({ documentId, field, onChanged }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(field.effective_value ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await api.correctField(documentId, field.id, draft || null)
      setEditing(false)
      onChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <tr className={field.is_low_confidence ? 'bg-amber-50/60' : undefined}>
      <td className="px-4 py-2.5 text-sm font-medium text-slate-700">
        {label(field.field_name)}
        {field.is_low_confidence && (
          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
            check
          </span>
        )}
      </td>
      <td className="px-4 py-2.5">
        {editing ? (
          <div className="flex items-center gap-2">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="max-w-xs"
              autoFocus
            />
            <Button onClick={save} loading={saving}>
              Save
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setEditing(false)
                setDraft(field.effective_value ?? '')
              }}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-slate-900">
              {field.effective_value || <span className="text-slate-500">—</span>}
            </span>
            {field.corrected_value !== null && field.corrected_value !== undefined && (
              <span
                className="rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800"
                title={`OCR originally read: ${field.value ?? '—'}`}
              >
                corrected
              </span>
            )}
          </div>
        )}
        {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      </td>
      <td className="px-4 py-2.5">
        <ConfidenceMeter value={field.confidence} low={field.is_low_confidence} />
      </td>
      <td className="px-4 py-2.5 text-right">
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="text-xs font-medium text-slate-600 hover:text-slate-900"
          >
            Edit
          </button>
        )}
      </td>
    </tr>
  )
}

function ResumeSummary({ profile }) {
  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <p className="text-xs text-slate-500">Candidate</p>
          <p className="font-medium text-slate-900">{profile.candidate_name ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Email</p>
          <p className="font-medium text-slate-900">{profile.email ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Total experience</p>
          <p className="font-medium text-slate-900">
            {profile.total_experience_years != null
              ? `${profile.total_experience_years} yrs`
              : '—'}
          </p>
        </div>
      </div>

      {profile.experience?.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Experience
          </p>
          <ul className="space-y-1">
            {profile.experience.map((job, index) => (
              <li key={index} className="text-slate-700">
                {job.title || job.detail}{' '}
                <span className="text-slate-500">
                  ({job.start_year}–{job.is_current ? 'present' : job.end_year})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {profile.education?.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Education
          </p>
          <ul className="space-y-1">
            {profile.education.map((edu, index) => (
              <li key={index} className="text-slate-700">
                <span className="font-medium">{edu.degree}</span>
                {edu.institution ? ` · ${edu.institution}` : ''}
                {edu.year ? ` · ${edu.year}` : ''}
                {edu.cgpa ? ` · CGPA ${edu.cgpa}` : ''}
                {edu.percentage ? ` · ${edu.percentage}%` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {profile.skills?.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Skills
          </p>
          <div className="flex flex-wrap gap-1.5">
            {profile.skills.map((skill) => (
              <span
                key={skill}
                className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function ExtractionReview({ document, onChanged, canApply = true }) {
  const [applying, setApplying] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const apply = async () => {
    setApplying(true)
    setError('')
    setResult(null)
    try {
      const response = await api.applyExtraction(document.id, {})
      setResult(response)
      onChanged?.()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setApplying(false)
    }
  }

  if (document.status === 'processing' || document.status === 'uploaded') {
    return (
      <Alert tone="info">
        Extraction is running. Refresh in a moment to see the results.
      </Alert>
    )
  }

  if (document.status === 'failed') {
    return <Alert>Extraction failed: {document.error_message ?? 'unknown error'}</Alert>
  }

  // Employees see why a document was turned down and what to do next.
  const rejectionNotice = document.status === 'rejected' && document.rejection_reason && (
    <Alert>
      {`This document was rejected by HR:\n${document.rejection_reason}\n\nPlease upload a replacement.`}
    </Alert>
  )

  const hasFields = document.fields?.length > 0
  const lowCount = document.fields?.filter((f) => f.is_low_confidence).length ?? 0

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>
      {rejectionNotice}

      {result && (
        <Alert tone="success">
          {result.message}
          {Object.keys(result.skipped).length > 0 &&
            `\nSkipped: ${Object.entries(result.skipped)
              .map(([k, v]) => `${label(k)} (${v})`)
              .join(', ')}`}
        </Alert>
      )}

      {lowCount > 0 && (
        <Alert tone="info">
          {lowCount} field{lowCount === 1 ? '' : 's'} came back with low confidence — please
          check {lowCount === 1 ? 'it' : 'them'} before applying.
        </Alert>
      )}

      {document.resume_profile && (
        <div className="rounded-lg bg-slate-50 p-4">
          <ResumeSummary profile={document.resume_profile} />
        </div>
      )}

      {hasFields ? (
        <>
          <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
            <table className="w-full text-left">
              <thead className="bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">Field</th>
                  <th className="px-4 py-2 font-medium">Value</th>
                  <th className="px-4 py-2 font-medium">Confidence</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {document.fields.map((field) => (
                  <FieldRow
                    key={field.id}
                    documentId={document.id}
                    field={field}
                    onChanged={onChanged}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {canApply && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-500">
                Applies name, date of birth, contact, and address fields to the profile.
                ID numbers are kept for verification only.
              </p>
              <Button onClick={apply} loading={applying}>
                Apply to profile
              </Button>
            </div>
          )}
        </>
      ) : (
        <p className="py-6 text-center text-sm text-slate-500">
          No fields could be read from this document. Try re-uploading a clearer scan.
        </p>
      )}
    </div>
  )
}
