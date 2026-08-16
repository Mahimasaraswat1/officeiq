import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, EmptyState, Field, Input, Select, Spinner } from '../components/ui'
import { CATEGORY_LABEL } from '../components/TaskList'
import { useToast } from '../components/Toast'

const CATEGORIES = [
  { value: 'task', label: 'Task' },
  { value: 'training', label: 'Training' },
  { value: 'document_checklist', label: 'Document checklist' },
  { value: 'policy_acknowledgement', label: 'Policy acknowledgement' },
]

const DOCUMENT_TYPES = ['aadhaar', 'pan', 'resume', 'certificate', 'photo', 'other']

const BLANK_TEMPLATE = {
  code: '',
  title: '',
  description: '',
  category: 'task',
  default_due_days: '',
  is_mandatory: true,
  resource_url: '',
  required_document_type: '',
}

const BLANK_RULE = { name: '', description: '', department: '', designation: '', priority: 100 }

/** Strips empty strings so optional fields are sent as null, not "". */
const clean = (obj) =>
  Object.fromEntries(
    Object.entries(obj)
      .filter(([, v]) => v !== '' && v !== undefined)
      .map(([k, v]) => [k, v]),
  )

function TemplateForm({ onCreated }) {
  const [form, setForm] = useState(BLANK_TEMPLATE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const update = (field) => (e) =>
    setForm({ ...form, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const payload = clean(form)
      if (payload.default_due_days !== undefined) {
        payload.default_due_days = Number(payload.default_due_days)
      }
      await api.createTaskTemplate(payload)
      setForm(BLANK_TEMPLATE)
      onCreated?.()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setBusy(false)
    }
  }

  const isChecklist = form.category === 'document_checklist'

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Code" hint="Stable identifier, e.g. IT_LAPTOP">
          <Input value={form.code} onChange={update('code')} required />
        </Field>
        <Field label="Title">
          <Input value={form.title} onChange={update('title')} required />
        </Field>
      </div>

      <Field label="Description">
        <Input value={form.description} onChange={update('description')} />
      </Field>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Category">
          <Select value={form.category} onChange={update('category')}>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Due (days)" hint="After the joining date">
          <Input
            type="number"
            min="0"
            value={form.default_due_days}
            onChange={update('default_due_days')}
          />
        </Field>
        <Field label="Resource URL">
          <Input value={form.resource_url} onChange={update('resource_url')} />
        </Field>
      </div>

      {isChecklist && (
        <Field
          label="Required document"
          hint="The item completes itself once this document is approved."
        >
          <Select
            value={form.required_document_type}
            onChange={update('required_document_type')}
            required
          >
            <option value="">Select a document type…</option>
            {DOCUMENT_TYPES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </Field>
      )}

      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={form.is_mandatory}
          onChange={update('is_mandatory')}
          className="h-4 w-4 rounded border-slate-300"
        />
        Mandatory — onboarding cannot be completed while this is outstanding
      </label>

      <div className="flex justify-end">
        <Button type="submit" loading={busy}>
          Add template
        </Button>
      </div>
    </form>
  )
}

function RuleEditor({ rule, templates, onSaved, onCancel }) {
  const [form, setForm] = useState({
    name: rule?.name ?? '',
    description: rule?.description ?? '',
    department: rule?.department ?? '',
    designation: rule?.designation ?? '',
    priority: rule?.priority ?? 100,
  })
  const [selected, setSelected] = useState(
    new Set((rule?.items ?? []).map((i) => i.template_id)),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value })

  const toggle = (id) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const payload = {
        ...form,
        priority: Number(form.priority),
        items: [...selected].map((template_id) => ({ template_id })),
      }
      if (rule) await api.updateAssignmentRule(rule.id, payload)
      else await api.createAssignmentRule(payload)
      onSaved?.()
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
        <Field label="Rule name">
          <Input value={form.name} onChange={update('name')} required />
        </Field>
        <Field label="Priority" hint="Display order only — rules never override each other">
          <Input type="number" value={form.priority} onChange={update('priority')} />
        </Field>
      </div>

      <Field label="Description">
        <Input value={form.description} onChange={update('description')} />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Department" hint="Leave empty to match any department">
          <Input value={form.department} onChange={update('department')} />
        </Field>
        <Field label="Designation" hint="Leave empty to match any designation">
          <Input value={form.designation} onChange={update('designation')} />
        </Field>
      </div>

      <div>
        <p className="mb-1 text-sm font-medium text-slate-700">
          Items to assign ({selected.size} selected)
        </p>
        <div className="max-h-72 space-y-1 overflow-y-auto rounded-md p-2 ring-1 ring-slate-200">
          {templates.length === 0 && (
            <p className="p-2 text-sm text-slate-500">Create a template first.</p>
          )}
          {templates.map((template) => (
            <label
              key={template.id}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50"
            >
              <input
                type="checkbox"
                checked={selected.has(template.id)}
                onChange={() => toggle(template.id)}
                className="h-4 w-4 rounded border-slate-300"
              />
              <span className="font-medium text-slate-900">{template.title}</span>
              <span className="text-xs text-slate-500">
                {CATEGORY_LABEL[template.category]} · {template.code}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" loading={busy}>
          {rule ? 'Save rule' : 'Create rule'}
        </Button>
      </div>
    </form>
  )
}

function RulePreview() {
  const [department, setDepartment] = useState('')
  const [designation, setDesignation] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    try {
      setResult(await api.previewAssignment({ department, designation }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        Check what a new joiner would receive before you rely on these rules.
      </p>
      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Department"
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          className="sm:max-w-48"
        />
        <Input
          placeholder="Designation"
          value={designation}
          onChange={(e) => setDesignation(e.target.value)}
          className="sm:max-w-48"
        />
        <Button onClick={run} loading={busy}>
          Preview
        </Button>
      </div>

      {result && (
        <div className="rounded-md bg-slate-50 p-4 text-sm">
          <p className="font-medium text-slate-900">
            {result.total} item{result.total === 1 ? '' : 's'} would be assigned
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            Matched rules: {result.matched_rules.join(', ') || 'none'}
          </p>
          <ul className="mt-2 list-inside list-disc text-slate-700">
            {result.templates.map((t) => (
              <li key={t.id}>
                {t.title}{' '}
                <span className="text-xs text-slate-500">({CATEGORY_LABEL[t.category]})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function OnboardingRules() {
  const toast = useToast()
  const [templates, setTemplates] = useState([])
  const [rules, setRules] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingRule, setEditingRule] = useState(null)
  const [creatingRule, setCreatingRule] = useState(false)

  const load = useCallback(async () => {
    try {
      const [templateRows, ruleRows] = await Promise.all([
        api.listTaskTemplates({ include_inactive: true }),
        api.listAssignmentRules(),
      ])
      setTemplates(templateRows)
      setRules(ruleRows)
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

  const removeRule = async (rule) => {
    if (!confirm(`Delete the rule "${rule.name}"? Tasks already assigned are unaffected.`)) return
    try {
      await api.deleteAssignmentRule(rule.id)
      toast.success('Rule deleted.')
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const toggleTemplate = async (template) => {
    try {
      await api.updateTaskTemplate(template.id, { is_active: !template.is_active })
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Onboarding rules</h1>
        <p className="mt-1 text-sm text-slate-500">
          Define what new joiners receive. Changes take effect immediately — no deploy needed.
        </p>
      </div>

      <Alert>{error}</Alert>

      <Card title="Preview">
        <RulePreview />
      </Card>

      <Card
        title={`Assignment rules (${rules.length})`}
        action={
          !creatingRule &&
          !editingRule && (
            <Button onClick={() => setCreatingRule(true)}>Add rule</Button>
          )
        }
      >
        {creatingRule && (
          <div className="mb-5 rounded-lg bg-slate-50 p-4">
            <RuleEditor
              templates={templates.filter((t) => t.is_active)}
              onSaved={() => {
                setCreatingRule(false)
                toast.success('Rule created.')
                load()
              }}
              onCancel={() => setCreatingRule(false)}
            />
          </div>
        )}

        {rules.length === 0 && !creatingRule ? (
          <EmptyState icon="⚙️" title="No rules yet">
            Without a rule nothing is auto-assigned. Add one to give every new joiner a
            starting checklist.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rules.map((rule) => (
              <li key={rule.id} className="py-3">
                {editingRule === rule.id ? (
                  <div className="rounded-lg bg-slate-50 p-4">
                    <RuleEditor
                      rule={rule}
                      templates={templates.filter((t) => t.is_active)}
                      onSaved={() => {
                        setEditingRule(null)
                        toast.success('Rule saved.')
                        load()
                      }}
                      onCancel={() => setEditingRule(null)}
                    />
                  </div>
                ) : (
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-900">{rule.name}</span>
                        {!rule.is_active && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                            inactive
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {rule.department || rule.designation
                          ? [
                              rule.department && `department = ${rule.department}`,
                              rule.designation && `designation = ${rule.designation}`,
                            ]
                              .filter(Boolean)
                              .join(' · ')
                          : 'Applies to everyone'}{' '}
                        · {rule.items.length} item{rule.items.length === 1 ? '' : 's'}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button variant="secondary" onClick={() => setEditingRule(rule.id)}>
                        Edit
                      </Button>
                      <Button variant="danger" onClick={() => removeRule(rule)}>
                        Delete
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={`Task & training catalogue (${templates.length})`}>
        <div className="space-y-5">
          <TemplateForm
            onCreated={() => {
              toast.success('Template created.')
              load()
            }}
          />

          {templates.length > 0 && (
            <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Title</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 font-medium">Due</th>
                    <th className="px-4 py-2 font-medium">Required</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {templates.map((template) => (
                    <tr key={template.id} className={template.is_active ? '' : 'opacity-50'}>
                      <td className="px-4 py-2 font-mono text-xs text-slate-600">
                        {template.code}
                      </td>
                      <td className="px-4 py-2 text-slate-900">{template.title}</td>
                      <td className="px-4 py-2 text-slate-600">
                        {CATEGORY_LABEL[template.category]}
                      </td>
                      <td className="px-4 py-2 text-slate-600">
                        {template.default_due_days != null
                          ? `+${template.default_due_days}d`
                          : '—'}
                      </td>
                      <td className="px-4 py-2 text-slate-600">
                        {template.is_mandatory ? 'Yes' : 'No'}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => toggleTemplate(template)}
                          className="text-xs font-medium text-slate-600 hover:text-slate-900"
                        >
                          {template.is_active ? 'Deactivate' : 'Reactivate'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}
