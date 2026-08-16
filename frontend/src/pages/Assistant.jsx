import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, EmptyState, Input, Spinner } from '../components/ui'

const SUGGESTIONS = [
  'How many annual leave days do I get per year?',
  'When are salaries paid each month?',
  'How many days can I carry forward?',
  'What is the remote work policy?',
]

/** Confidence shown as a small labelled bar, so the number means something. */
function ConfidenceBadge({ value }) {
  const percent = Math.round((value ?? 0) * 100)
  const tone =
    percent >= 70
      ? 'bg-emerald-100 text-emerald-800'
      : percent >= 45
        ? 'bg-sky-100 text-sky-800'
        : 'bg-amber-100 text-amber-800'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {percent}% confident
    </span>
  )
}

function Citations({ citations }) {
  if (!citations?.length) return null
  return (
    <div className="mt-3 border-t border-slate-100 pt-2">
      <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Sources
      </p>
      <ol className="mt-1 space-y-1">
        {citations.map((c, index) => (
          <li key={`${c.document_id}-${c.chunk_index}`} className="text-xs text-slate-600">
            <span className="font-medium text-slate-700">[{index + 1}]</span>{' '}
            {c.document_title}
            {c.heading ? ` — ${c.heading}` : ''}
            {c.source_reference ? (
              <span className="text-slate-500"> · {c.source_reference}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  )
}

function Bubble({ message }) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2.5 text-sm text-white">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[85%] rounded-2xl rounded-bl-sm px-4 py-3 text-sm ring-1 ${
          message.escalated
            ? 'bg-amber-50 text-amber-900 ring-amber-200'
            : 'bg-white text-slate-800 ring-slate-200'
        }`}
      >
        <p className="whitespace-pre-line">{message.content}</p>

        {message.escalated ? (
          <p className="mt-2 text-xs text-amber-700">
            Answering from the company knowledge base only — this wasn't covered, so
            please check with HR rather than relying on a guess.
          </p>
        ) : (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {message.confidence != null && <ConfidenceBadge value={message.confidence} />}
          </div>
        )}

        <Citations citations={message.citations} />
      </div>
    </div>
  )
}

export default function Assistant() {
  const [conversations, setConversations] = useState([])
  const [conversationId, setConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations())
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  const openConversation = async (id) => {
    setError('')
    try {
      const detail = await api.getConversation(id)
      setConversationId(id)
      setMessages(detail.messages)
    } catch (err) {
      setError(err.message)
    }
  }

  const startNew = () => {
    setConversationId(null)
    setMessages([])
    setError('')
  }

  const send = async (text) => {
    const trimmed = (text ?? question).trim()
    if (!trimmed || sending) return

    setError('')
    setQuestion('')
    // Show the question immediately; the answer replaces the pending state.
    setMessages((prev) => [...prev, { id: `local-${Date.now()}`, role: 'user', content: trimmed }])
    setSending(true)

    try {
      const response = await api.ask({
        question: trimmed,
        conversation_id: conversationId ?? undefined,
      })
      setConversationId(response.conversation_id)
      setMessages((prev) => [
        ...prev,
        {
          id: response.message_id,
          role: 'assistant',
          content: response.answer,
          confidence: response.confidence,
          citations: response.citations,
          escalated: response.escalated,
        },
      ])
      loadConversations()
    } catch (err) {
      setError(err.fieldMessages ?? err.message)
    } finally {
      setSending(false)
    }
  }

  const removeConversation = async (id, event) => {
    event.stopPropagation()
    if (!confirm('Delete this conversation?')) return
    try {
      await api.deleteConversation(id)
      if (id === conversationId) startNew()
      loadConversations()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Ask HR</h1>
        <p className="mt-1 text-sm text-slate-500">
          Answers come from your company's own policy documents, with sources shown. If
          something isn't covered, you'll be pointed to HR rather than given a guess.
        </p>
      </div>

      <Alert>{error}</Alert>

      <div className="grid gap-6 lg:grid-cols-4">
        {/* --- Conversation list --- */}
        <aside className="lg:col-span-1">
          <div className="rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200">
            <Button className="w-full" onClick={startNew}>
              New question
            </Button>
            <ul className="mt-3 space-y-1">
              {conversations.length === 0 && (
                <li className="px-2 py-3 text-xs text-slate-500">No conversations yet.</li>
              )}
              {conversations.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => openConversation(c.id)}
                    className={`group flex w-full items-center justify-between rounded px-2 py-2 text-left text-xs transition ${
                      c.id === conversationId
                        ? 'bg-slate-100 text-slate-900'
                        : 'text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    <span className="truncate">{c.title || 'Conversation'}</span>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => removeConversation(c.id, e)}
                      onKeyDown={(e) => e.key === 'Enter' && removeConversation(c.id, e)}
                      className="ml-2 hidden shrink-0 text-slate-500 hover:text-red-600 group-hover:block"
                    >
                      ✕
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        {/* --- Transcript --- */}
        <section className="lg:col-span-3">
          <div className="flex h-[32rem] flex-col rounded-lg bg-slate-50 shadow-sm ring-1 ring-slate-200">
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.length === 0 && !sending && (
                <div className="pt-10">
                  <EmptyState icon="💬" title="Ask me anything">
                    Leave, payroll, benefits or policy — answers come from your company
                    handbook, with citations.
                  </EmptyState>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="rounded-full bg-white px-3 py-1.5 text-xs text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((message) => (
                <Bubble key={message.id} message={message} />
              ))}

              {sending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-sm bg-white px-4 py-3 text-sm text-slate-500 ring-1 ring-slate-200">
                    Searching the knowledge base…
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                send()
              }}
              className="flex gap-2 border-t border-slate-200 bg-white p-3"
            >
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a question about company policy…"
                disabled={sending}
                autoFocus
              />
              <Button type="submit" disabled={sending || !question.trim()}>
                Send
              </Button>
            </form>
          </div>
        </section>
      </div>
    </div>
  )
}
