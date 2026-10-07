// Non-component helpers: routing, formatting, status descriptions.
import { useEffect, useState } from 'react'
import type { TrialStatus } from './api'

// -- routing (hash based: #/, #/runs/<id>, #/trials/<id>) -----------------------

export type Route =
  | { page: 'runs' }
  | { page: 'run'; id: string }
  | { page: 'trial'; id: string }

function parseHash(hash: string): Route {
  const [, kind, id] = hash.replace(/^#/, '').split('/')
  if (kind === 'runs' && id) return { page: 'run', id }
  if (kind === 'trials' && id) return { page: 'trial', id }
  return { page: 'runs' }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

export const href = {
  runs: () => '#/',
  run: (id: string) => `#/runs/${id}`,
  trial: (id: string) => `#/trials/${id}`,
}

export const STATUS_HELP: Partial<Record<TrialStatus, string>> = {
  PASS: 'Tests passed, no tampering, no limits hit',
  FAIL: 'Tests failed',
  TAMPER: 'The agent modified protected system files the tests rely on',
  LIMIT: 'The trial hit a resource limit and was stopped',
  ERROR: 'The harness or Docker failed',
}

// -- formatting ------------------------------------------------------------------

export function timeAgo(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

export function seconds(value: number | null | undefined): string {
  if (value == null) return '—'
  return value < 60 ? `${value.toFixed(1)}s` : `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`
}

export function percent(part: number, total: number): string {
  return total ? `${Math.round((100 * part) / total)}%` : '—'
}
