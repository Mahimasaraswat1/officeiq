import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Input } from '../components/ui'
import ConfirmDialog from '../components/ConfirmDialog'

const SUGGESTIONS = [
  'How many annual leave days do I get?',
  'When are salaries paid?',
  'What is the remote work policy?',
  'How do I claim expenses?',
]

/** Confidence shown as a small labelled chip, so the number means something. */
function ConfidenceBadge({ value }) {
  const percent = Math.round((value ?? 0) * 100)
  const tone =
    percent >= 70
      ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
      : percent >= 45
        ? 'bg-accent-50 text-accent-700 ring-accent-100'
        : 'bg-amber-50 text-amber-800 ring-amber-200'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${tone}`}>
      {percent}% confident
    </span>
  )
}

/**
 * Citations as distinct source tags.
 *
 * Deliberately styled apart from the answer text: a claim and its provenance
 * should never blur together, and an employee checking "did it really say
 * that?" needs the document name to be the obvious thing to look at.
 */
function Citations({ citations }) {
  if (!citations?.length) return null

  return (
    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-navy-100 pt-3">
      {citations.map((citation) => (
        <span
          key={`${citation.document_id}-${citation.chunk_index}`}
          title={
            citation.source_reference
              ? `${citation.document_title} · ${citation.source_reference}`
              : citation.document_title
          }
          className="inline-flex max-w-full items-center gap-1.5 rounded-lg bg-navy-50 px-2.5 py-1 text-xs ring-1 ring-navy-100"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-accent-600">
            <path d="M5 2h7l3 3v13H5V2zm6 1.5V6h2.5L11 3.5z" />
          </svg>
          <span className="font-semibold text-navy-700">Source:</span>
          <span className="truncate text-navy-600">
            {citation.document_title}
            {citation.heading ? ` — ${citation.heading}` : ''}
          </span>
        </span>
      ))}
    </div>
  )
}

/**
 * How an escalation is presented depends on *why* it escalated.
 *
 * These all used to look identical, so a failed model call told the employee
 * their question wasn't covered by the handbook — sending them to hunt for a
 * documentation gap that did not exist.
 */
const ESCALATION_STYLE = {
  escalated_no_context: {
    bubble: 'bg-amber-50 text-amber-900 ring-amber-200',
    note: "This isn't covered in the handbook, so it's better to check with HR than to rely on a guess.",
  },
  escalated_low_confidence: {
    bubble: 'bg-amber-50 text-amber-900 ring-amber-200',
    note: 'Related passages were found but they do not clearly answer this — confirm with HR before relying on them.',
  },
  error: {
    bubble: 'bg-red-50 text-red-900 ring-red-200',
    note: 'The assistant could not be reached. This is a technical fault, not a gap in the handbook — please try again shortly.',
  },
}

const escalationStyle = (message) =>
  ESCALATION_STYLE[message.outcome] ?? ESCALATION_STYLE.escalated_no_context

function Bubble({ message }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-accent-600 px-4 py-2.5 text-sm text-white shadow-card">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start gap-2.5">
      <AssistantAvatar />
      <div
        className={`max-w-[85%] rounded-2xl rounded-bl-md px-4 py-3 text-sm shadow-card ring-1 ${
          message.escalated
            ? escalationStyle(message).bubble
            : 'bg-white text-navy-800 ring-navy-100'
        }`}
      >
        <p className="whitespace-pre-line">{message.content}</p>

        {message.escalated ? (
          <p className="mt-2 text-xs opacity-80">{escalationStyle(message).note}</p>
        ) : (
          message.confidence != null && (
            <div className="mt-2">
              <ConfidenceBadge value={message.confidence} />
            </div>
          )
        )}

        <Citations citations={message.citations} />
      </div>
    </div>
  )
}

function AssistantAvatar() {
  return (
    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy-900 text-[10px] font-extrabold text-white">
      IQ
    </span>
  )
}

/** Three staggered dots — the conventional "still thinking" signal. */
function TypingIndicator() {
  return (
    <div className="flex justify-start gap-2.5">
      <AssistantAvatar />
      <div className="flex items-center gap-2 rounded-2xl rounded-bl-md bg-white px-4 py-3 shadow-card ring-1 ring-navy-100">
        <span className="flex gap-1" aria-hidden="true">
          {[0, 150, 300].map((delay) => (
            <span
              key={delay}
              className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy-400"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </span>
        {/* The visible text carries the meaning; the dots are decoration, so a
            reader with reduced motion still knows what is happening. */}
        <span className="text-sm text-navy-500">Searching your handbook…</span>
      </div>
    </div>
  )
}

function SuggestionChips({ onPick, disabled }) {
  return (
    <div className="flex flex-wrap gap-2">
      {SUGGESTIONS.map((suggestion) => (
        <button
          key={suggestion}
          type="button"
          disabled={disabled}
          onClick={() => onPick(suggestion)}
          className="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-navy-600 shadow-card ring-1 ring-navy-100 transition duration-200 hover:-translate-y-0.5 hover:text-navy-900 hover:shadow-card-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          {suggestion}
        </button>
      ))}
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
  const [deleting, setDeleting] = useState(null)
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
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, role: 'user', content: trimmed },
    ])
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
          outcome: response.outcome,
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

  const confirmDelete = async () => {
    try {
      await api.deleteConversation(deleting.id)
      if (deleting.id === conversationId) startNew()
      setDeleting(null)
      loadConversations()
    } catch (err) {
      setError(err.message)
      setDeleting(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">Ask HR</h1>
        <p className="mt-1 text-sm text-navy-500">
          Answers come from your company's own policy documents, with sources shown. If
          something isn't covered you'll be pointed to HR rather than given a guess.
        </p>
      </div>

      <Alert>{error}</Alert>

      <div className="grid gap-5 lg:grid-cols-4">
        {/* --- Conversation history --- */}
        <aside className="lg:col-span-1">
          <div className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-navy-100/70">
            <Button className="w-full" onClick={startNew}>
              New question
            </Button>
            <ul className="mt-3 space-y-0.5">
              {conversations.length === 0 && (
                <li className="px-2 py-3 text-xs text-navy-500">No conversations yet.</li>
              )}
              {conversations.map((conversation) => (
                <li key={conversation.id}>
                  <div
                    className={`group flex items-center gap-1 rounded-xl transition ${
                      conversation.id === conversationId
                        ? 'bg-navy-100 text-navy-900'
                        : 'text-navy-600 hover:bg-navy-50'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => openConversation(conversation.id)}
                      className="min-w-0 flex-1 truncate px-2.5 py-2 text-left text-xs"
                    >
                      {conversation.title || 'Conversation'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeleting(conversation)}
                      aria-label={`Delete conversation: ${conversation.title || 'Conversation'}`}
                      className="mr-1 shrink-0 rounded-lg px-1.5 py-1 text-navy-400 opacity-0 transition hover:bg-white hover:text-red-600 focus-visible:opacity-100 group-hover:opacity-100"
                    >
                      ✕
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        {/* --- Transcript --- */}
        <section className="lg:col-span-3">
          <div className="flex h-[34rem] flex-col overflow-hidden rounded-2xl bg-navy-50/60 shadow-card ring-1 ring-navy-100/70">
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.length === 0 && !sending && (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-navy-900 text-sm font-extrabold text-white">
                    IQ
                  </span>
                  <p className="text-base font-bold text-navy-900">Ask me anything</p>
                  <p className="mt-1 max-w-sm text-sm text-navy-500">
                    Leave, payroll, benefits or policy — every answer cites the handbook
                    passage it came from.
                  </p>
                  <div className="mt-5">
                    <SuggestionChips onPick={send} disabled={sending} />
                  </div>
                </div>
              )}

              {messages.map((message) => (
                <Bubble key={message.id} message={message} />
              ))}

              {sending && <TypingIndicator />}
              <div ref={bottomRef} />
            </div>

            {/* Once a conversation is under way the chips move above the
                composer, so a follow-up is still one click away. */}
            {messages.length > 0 && (
              <div className="border-t border-navy-100 bg-white/60 px-3 pt-3">
                <SuggestionChips onPick={send} disabled={sending} />
              </div>
            )}

            <form
              onSubmit={(event) => {
                event.preventDefault()
                send()
              }}
              className="flex gap-2 border-t border-navy-100 bg-white p-3"
            >
              <Input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask a question about company policy…"
                aria-label="Your question"
                disabled={sending}
                autoFocus
                className="rounded-xl"
              />
              <Button type="submit" loading={sending} disabled={!question.trim()}>
                Send
              </Button>
            </form>
          </div>
        </section>
      </div>

      {deleting && (
        <ConfirmDialog
          title="Delete this conversation?"
          confirmLabel="Delete"
          tone="danger"
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        >
          <p>
            “{deleting.title || 'Conversation'}” will be removed permanently. Your
            conversations are private to you, so nobody else has a copy.
          </p>
        </ConfirmDialog>
      )}
    </div>
  )
}
