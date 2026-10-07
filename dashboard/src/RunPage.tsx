// One run: every trial grouped by task, updating live as workers report.
import { useCallback, useEffect, useState } from 'react'
import { api, subscribeToRun, type RunDetail, type TrialRow } from './api'
import { href, percent, seconds, timeAgo } from './lib'
import { Card, ErrorNote, Loading, StatusBadge } from './ui'

const FINISHED = ['PASS', 'FAIL', 'TAMPER', 'LIMIT', 'ERROR']

function TrialChip({ trial }: { trial: TrialRow }) {
  return (
    <a
      href={href.trial(trial.id)}
      title={trial.detail ?? undefined}
      className="group flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 transition hover:border-zinc-600"
    >
      <span className="text-xs text-zinc-500">#{trial.trial_no}</span>
      <StatusBadge status={trial.status} />
      <span className="ml-auto font-mono text-xs text-zinc-500">
        {trial.steps != null ? `${trial.steps} cmd` : ''} {trial.duration != null ? seconds(trial.duration) : ''}
      </span>
    </a>
  )
}

export function RunPage({ id }: { id: string }) {
  const [run, setRun] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState<Record<string, number>>({}) // trial id -> commands so far

  const load = useCallback(() => api.run(id).then(setRun).catch((e: Error) => setError(e.message)), [id])

  useEffect(() => {
    load()
    return subscribeToRun(id, (event) => {
      if (event.type === 'step') {
        setLive((prev) => ({ ...prev, [event.trial_id]: event.step.index }))
      } else if (event.type === 'trial') {
        setRun((prev) => prev && {
          ...prev,
          trials: prev.trials.map((t) => (t.id === event.id ? { ...t, ...event, id: t.id } : t)),
        })
        if (FINISHED.includes(event.status)) load() // refresh the summary counts
      } else if (event.type === 'run') {
        load()
      }
    })
  }, [id, load])

  if (error) return <ErrorNote error={error} />
  if (!run) return <Loading />

  const byTask = new Map<string, TrialRow[]>()
  for (const t of run.trials) byTask.set(t.task, [...(byTask.get(t.task) ?? []), t])
  const finished = run.passed + run.failed
  const active = run.status === 'queued' || run.status === 'running'

  const cancel = async () => {
    await api.cancelRun(id)
    load()
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <a href={href.runs()} className="text-xs text-zinc-500 hover:text-zinc-300">← All runs</a>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-semibold text-zinc-100">
            Run <span className="font-mono">{run.id}</span> <StatusBadge status={run.status} />
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            <span className="font-mono text-zinc-300">{run.model}</span> · started {timeAgo(run.created_at)} · up to {run.max_steps} commands per trial
          </p>
        </div>
        {active && (
          <button onClick={cancel}
                  className="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:border-rose-500/60 hover:text-rose-300">
            Cancel queued trials
          </button>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        {[
          ['Pass rate', percent(run.passed, finished)],
          ['Passed', `${run.passed} / ${run.total}`],
          ['Tampered', String(run.tampered)],
          ['In progress', String(run.running)],
        ].map(([label, value]) => (
          <Card key={label} className="px-4 py-3">
            <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
            <div className="mt-1 font-mono text-2xl text-zinc-100">{value}</div>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
        {Object.entries(run.limits)
          .filter(([key]) => ['memory_mb', 'cpus', 'pids', 'disk_mb', 'trial_timeout', 'network'].includes(key))
          .map(([key, value]) => (
            <span key={key} className="rounded-md bg-zinc-900 px-2 py-1 font-mono ring-1 ring-zinc-800">
              {key}={String(value)}
            </span>
          ))}
      </div>

      <div className="space-y-4">
        {[...byTask.entries()].map(([task, trials]) => {
          const passed = trials.filter((t) => t.status === 'PASS').length
          const done = trials.filter((t) => FINISHED.includes(t.status)).length
          return (
            <Card key={task} className="p-4">
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="font-mono text-sm text-zinc-100">{task}</h2>
                <span className="text-xs text-zinc-500">
                  {passed}/{trials.length} passed{done ? ` · ${percent(passed, done)}` : ''}
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {trials.map((t) => (
                  <TrialChip key={t.id} trial={t.status === 'running' && live[t.id] ? { ...t, steps: live[t.id] } : t} />
                ))}
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
