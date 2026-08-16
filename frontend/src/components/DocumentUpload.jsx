import { useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Select } from './ui'
import { useToast } from './Toast'

const DOCUMENT_TYPES = [
  { value: 'aadhaar', label: 'Aadhaar card' },
  { value: 'pan', label: 'PAN card' },
  { value: 'resume', label: 'Resume / CV' },
  { value: 'certificate', label: 'Educational certificate' },
  { value: 'photo', label: 'Passport photo' },
  { value: 'other', label: 'Other' },
]

const MAX_MB = 10
const ACCEPT = '.pdf,.jpg,.jpeg,.png'

export default function DocumentUpload({ employeeId, onUploaded }) {
  const toast = useToast()
  const inputRef = useRef(null)
  const [documentType, setDocumentType] = useState('aadhaar')
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')

  const send = async (file) => {
    setError('')

    // Fail fast on the obvious cases; the server re-validates everything.
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`"${file.name}" is larger than ${MAX_MB} MB.`)
      return
    }
    if (documentType === 'photo' && file.type === 'application/pdf') {
      setError('A passport photo must be a JPEG or PNG image.')
      return
    }

    setProgress(0)
    try {
      await api.uploadDocument(employeeId, file, documentType, setProgress)
      toast.success(`"${file.name}" uploaded. Extraction is running…`)
      onUploaded?.()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setProgress(null)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) send(file)
  }

  const busy = progress !== null

  return (
    <div className="space-y-3">
      <Alert>{error}</Alert>

      <label className="block">
        <span className="mb-1 block text-sm font-medium text-slate-700">Document type</span>
        <Select
          value={documentType}
          onChange={(e) => setDocumentType(e.target.value)}
          disabled={busy}
        >
          {DOCUMENT_TYPES.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </Select>
      </label>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !busy && inputRef.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed px-6 py-8 text-center transition ${
          dragging
            ? 'border-slate-900 bg-slate-50'
            : 'border-slate-300 hover:border-slate-400 hover:bg-slate-50'
        } ${busy ? 'pointer-events-none opacity-60' : ''}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => e.target.files?.[0] && send(e.target.files[0])}
        />

        {busy ? (
          <div className="space-y-2">
            <p className="text-sm font-medium text-slate-700">Uploading… {progress}%</p>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-slate-900 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm font-medium text-slate-700">
              Drop a file here, or click to browse
            </p>
            <p className="mt-1 text-xs text-slate-500">
              PDF, JPEG, or PNG · up to {MAX_MB} MB
            </p>
          </>
        )}
      </div>
    </div>
  )
}

export { DOCUMENT_TYPES }
