/**
 * Header jump-to box. Debounced substring search across whatever the signed-in
 * role is allowed to see; the backend does the scoping, so this component never
 * has to know the rules.
 */

import { useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { StatusBadge } from './ui'

const DEBOUNCE_MS = 250
const MIN_CHARS = 2

export default function GlobalSearch() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(0)
  const inputId = useId()
  const containerRef = useRef(null)
  const inputRef = useRef(null)
  const navigate = useNavigate()

  // Flatten the grouped response once so arrow keys can walk it linearly.
  const flat = (results?.groups ?? []).flatMap((group) => group.items)

  useEffect(() => {
    if (query.trim().length < MIN_CHARS) {
      setResults(null)
      return undefined
    }

    let cancelled = false
    setLoading(true)
    // Debounced so a fast typist fires one request, not eight.
    const timer = setTimeout(async () => {
      try {
        const body = await api.search(query.trim())
        if (!cancelled) {
          setResults(body)
          setCursor(0)
          setOpen(true)
        }
      } catch {
        if (!cancelled) setResults(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  useEffect(() => {
    const onClick = (event) => {
      if (!containerRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  // "/" focuses the box, unless the reader is already typing somewhere.
  useEffect(() => {
    const onKey = (event) => {
      const tag = document.activeElement?.tagName
      if (event.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
        // offsetParent is null when an ancestor is display:none, which is how
        // the hidden copy is told apart from the visible one.
        if (inputRef.current?.offsetParent === null) return
        event.preventDefault()
        inputRef.current.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const go = (hit) => {
    setOpen(false)
    setQuery('')
    navigate(hit.link)
  }

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      setOpen(false)
      inputRef.current?.blur()
      return
    }
    if (!flat.length) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((index) => (index + 1) % flat.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((index) => (index - 1 + flat.length) % flat.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      go(flat[cursor])
    }
  }

  const showPanel = open && query.trim().length >= MIN_CHARS
  let runningIndex = -1

  return (
    <div className="relative w-full sm:max-w-xs" ref={containerRef}>
      <label className="sr-only" htmlFor={inputId}>
        Search employees, documents, tasks and policies
      </label>
      <div className="relative">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
          className="pointer-events-none absolute top-2.5 left-2.5 h-4 w-4 text-slate-500"
        >
          <path
            fillRule="evenodd"
            d="M9 3.5a5.5 5.5 0 1 0 3.4 9.8l3.4 3.4a1 1 0 0 0 1.4-1.4l-3.4-3.4A5.5 5.5 0 0 0 9 3.5Zm-3.5 5.5a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0Z"
            clipRule="evenodd"
          />
        </svg>
        <input
          id={inputId}
          ref={inputRef}
          type="search"
          value={query}
          placeholder="Search…  /"
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => results && setOpen(true)}
          onKeyDown={onKeyDown}
          className="w-full rounded-md border-0 bg-slate-50 py-1.5 pr-3 pl-8 text-sm text-slate-900 ring-1 ring-slate-200 ring-inset placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-slate-900 focus:ring-inset"
        />
      </div>

      {showPanel && (
        <div className="absolute right-0 left-0 z-30 mt-2 max-h-96 overflow-y-auto rounded-lg bg-white shadow-lg ring-1 ring-slate-200">
          {loading && !results && (
            <p className="px-4 py-6 text-center text-sm text-slate-500">Searching…</p>
          )}

          {results && results.total === 0 && (
            <p className="px-4 py-6 text-center text-sm text-slate-500">
              No matches for “{query.trim()}”.
            </p>
          )}

          {results?.groups
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <div key={group.kind}>
                <p className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-500">
                  <span>{group.label}</span>
                  {/* The list is capped, so say how many there really are. */}
                  {group.total > group.items.length && (
                    <span className="text-slate-500">
                      {group.items.length} of {group.total}
                    </span>
                  )}
                </p>
                {group.items.map((hit) => {
                  runningIndex += 1
                  const active = runningIndex === cursor
                  return (
                    <button
                      key={`${hit.kind}-${hit.id}`}
                      type="button"
                      onClick={() => go(hit)}
                      onMouseEnter={() => setCursor(flat.indexOf(hit))}
                      className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition ${
                        active ? 'bg-slate-100' : 'hover:bg-slate-50'
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-slate-900">
                          {hit.title}
                        </span>
                        {hit.subtitle && (
                          <span className="block truncate text-xs text-slate-500">
                            {hit.subtitle}
                          </span>
                        )}
                      </span>
                      {hit.badge && <StatusBadge status={hit.badge} />}
                    </button>
                  )
                })}
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
