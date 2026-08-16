import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, Field, Input, Spinner, StatusBadge } from '../components/ui'
import DocumentUpload from '../components/DocumentUpload'
import DocumentList from '../components/DocumentList'
import { useToast } from '../components/Toast'

const EDITABLE = [
  ['personal_email', 'Personal email'],
  ['phone', 'Phone'],
  ['date_of_birth', 'Date of birth'],
  ['address_line1', 'Address line 1'],
  ['address_line2', 'Address line 2'],
  ['city', 'City'],
  ['state', 'State'],
  ['postal_code', 'Postal code'],
  ['country', 'Country'],
]

export default function MyOnboarding() {
  const toast = useToast()
  const [record, setRecord] = useState(null)
  const [form, setForm] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [documentsKey, setDocumentsKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    api
      .myEmployeeRecord()
      .then((data) => {
        if (cancelled) return
        setRecord(data)
        setForm(Object.fromEntries(EDITABLE.map(([key]) => [key, data[key] ?? ''])))
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSaving(true)
    try {
      const changes = Object.fromEntries(
        Object.entries(form).filter(([key, value]) => (value || null) !== (record[key] || null)),
      )
      if (Object.keys(changes).length === 0) {
        toast.success('Nothing to save.')
        return
      }
      const updated = await api.updateMyEmployeeRecord(changes)
      setRecord(updated)
      toast.success('Your details have been saved.')
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner />
  if (!record) return <Alert>{error || 'No employee record is linked to your account.'}</Alert>

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">My onboarding</h1>
        <StatusBadge status={record.onboarding_status} />
      </div>

      <Alert>{error}</Alert>

      <Card title="Personal details">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {EDITABLE.map(([key, label]) => (
              <Field key={key} label={label}>
                <Input
                  type={key === 'date_of_birth' ? 'date' : 'text'}
                  value={form[key] ?? ''}
                  onChange={update(key)}
                />
              </Field>
            ))}
          </div>
          <div className="flex justify-end">
            <Button type="submit" loading={saving}>
              Save details
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Your documents">
        <div className="space-y-5">
          <p className="text-sm text-slate-500">
            Upload your Aadhaar, PAN, resume, certificates, and a passport photo. We read the
            details automatically so you don't have to type them in — you can correct anything
            we get wrong.
          </p>
          <DocumentUpload
            employeeId={record.id}
            onUploaded={() => setDocumentsKey((k) => k + 1)}
          />
          <DocumentList employeeId={record.id} canManage canApply={false} refreshKey={documentsKey} />
        </div>
      </Card>

      <Card title="Coming up">
        <p className="text-sm text-slate-500">
          Your task and training checklist arrives in the next phase of OfficeIQ. Your HR team
          will let you know when it is ready.
        </p>
      </Card>
    </div>
  )
}
