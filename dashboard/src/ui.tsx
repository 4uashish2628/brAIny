// Small shared UI components: status badges and layout.
import type { ReactNode } from 'react'
import type { RunStatus, TrialStatus } from './api'
import { href, STATUS_HELP } from './lib'

// -- status ----------------------------------------------------------------------

const STATUS_STYLES: Record<TrialStatus | RunStatus, string> = {
  PASS: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  FAIL: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  TAMPER: 'bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30',
  LIMIT: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  ERROR: 'bg-red-500/20 text-red-300 ring-red-500/40',
  running: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  queued: 'bg-zinc-500/10 text-zinc-400 ring-zinc-500/25',
  cancelled: 'bg-zinc-500/10 text-zinc-500 ring-zinc-500/20',
  done: 'bg-zinc-500/10 text-zinc-300 ring-zinc-500/25',
}

export function StatusBadge({ status }: { status: TrialStatus | RunStatus }) {
  return (
    <span
      title={STATUS_HELP[status as TrialStatus]}
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLES[status]}`}
    >
      {status === 'running' && <span className="size-1.5 animate-pulse rounded-full bg-sky-300" />}
      {status}
    </span>
  )
}

// -- layout ----------------------------------------------------------------------

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
          <a href={href.runs()} className="flex items-center gap-2 font-semibold tracking-tight text-zinc-100">
            <img src="/favicon.svg" alt="" className="size-6" />
            Invigilator
          </a>
          <span className="text-sm text-zinc-500">sandboxed agent evaluation</span>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-zinc-800 bg-zinc-900/50 ${className}`}>{children}</section>
}

export function ErrorNote({ error }: { error: string }) {
  return <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</p>
}

export function Loading() {
  return <p className="text-sm text-zinc-500">Loading…</p>
}
