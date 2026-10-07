// Home page: start a new run, and the list of past runs.
import { useEffect, useState, type FormEvent } from 'react'
import { api, type RunSummary, type TaskInfo } from './api'
import { href, percent, timeAgo } from './lib'
import { Card, ErrorNote, Loading, StatusBadge } from './ui'

function NewRunForm() {
  const [tasks, setTasks] = useState<TaskInfo[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [trials, setTrials] = useState(2)
  const [model, setModel] = useState('qwen2.5-coder:7b')
  const [maxSteps, setMaxSteps] = useState(30)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api.tasks()
      .then((list) => {
        setTasks(list)
        setSelected(new Set(list.map((t) => t.name)))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const toggle = (name: string) => {
    const next = new Set(selected)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setSelected(next)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const run = await api.createRun({ tasks: [...selected], trials, model, max_steps: maxSteps })
      window.location.hash = href.run(run.id)
    } catch (e) {
      setError((e as Error).message)
      setSubmitting(false)
    }
  }

  const total = selected.size * trials
  const input = 'w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500'

  return (
    <Card className="p-5">
      <h2 className="mb-4 text-sm font-semibold text-zinc-100">New run</h2>
      {error && <div className="mb-4"><ErrorNote error={error} /></div>}
      {!tasks && !error && <Loading />}
      {tasks && (
        <form onSubmit={submit} className="space-y-5">
          <fieldset>
            <legend className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Tasks</legend>
            <div className="flex flex-wrap gap-2">
              {tasks.map((t) => (
                <label
                  key={t.name}
                  title={t.instruction}
                  className={`cursor-pointer rounded-lg border px-3 py-1.5 font-mono text-xs transition ${
                    selected.has(t.name)
                      ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
                      : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                  }`}
                >
                  <input type="checkbox" className="sr-only" checked={selected.has(t.name)} onChange={() => toggle(t.name)} />
                  {t.name}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid gap-4 sm:grid-cols-[2fr_1fr_1fr]">
            <label className="space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Model</span>
              <input className={input} value={model} onChange={(e) => setModel(e.target.value)} required />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Trials per task</span>
              <input className={input} type="number" min={1} max={20} value={trials}
                     onChange={(e) => setTrials(Number(e.target.value))} />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Max commands</span>
              <input className={input} type="number" min={1} max={200} value={maxSteps}
                     onChange={(e) => setMaxSteps(Number(e.target.value))} />
            </label>
          </div>
          <div className="flex items-center gap-4">
            <button
              type="submit"
              disabled={submitting || selected.size === 0}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:opacity-40"
            >
              {submitting ? 'Starting…' : `Start ${total} trial${total === 1 ? '' : 's'}`}
            </button>
            <span className="text-xs text-zinc-500">Each trial runs in its own sandbox: 512 MB RAM, 1 CPU, no network.</span>
          </div>
        </form>
      )}
    </Card>
  )
}

function RunList() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = () => api.runs().then(setRuns).catch((e: Error) => setError(e.message))
    load()
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [])

  if (error) return <ErrorNote error={error} />
  if (!runs) return <Loading />
  if (runs.length === 0) return <p className="text-sm text-zinc-500">No runs yet. Start one above.</p>

  return (
    <Card className="overflow-hidden">
      <table className="w-full text-sm">
        <thead className="border-b border-zinc-800 text-left text-xs uppercase tracking-wide text-zinc-500">
          <tr>
            <th className="px-4 py-3 font-medium">Run</th>
            <th className="px-4 py-3 font-medium">Model</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Progress</th>
            <th className="px-4 py-3 text-right font-medium">Pass rate</th>
            <th className="px-4 py-3 text-right font-medium">Started</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/70">
          {runs.map((run) => {
            const finished = run.passed + run.failed
            return (
              <tr key={run.id} className="cursor-pointer transition hover:bg-zinc-800/30"
                  onClick={() => (window.location.hash = href.run(run.id))}>
                <td className="px-4 py-3">
                  <a href={href.run(run.id)} className="font-mono text-zinc-100">{run.id}</a>
                  <div className="mt-0.5 truncate text-xs text-zinc-500">{run.tasks.join(', ')}</div>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-zinc-300">{run.model}</td>
                <td className="px-4 py-3"><StatusBadge status={run.status} /></td>
                <td className="px-4 py-3">
                  <div className="flex h-1.5 w-32 overflow-hidden rounded-full bg-zinc-800">
                    <div className="bg-emerald-400" style={{ width: `${(100 * run.passed) / run.total}%` }} />
                    <div className="bg-rose-400" style={{ width: `${(100 * run.failed) / run.total}%` }} />
                  </div>
                  <div className="mt-1 text-xs text-zinc-500">{finished}/{run.total} done</div>
                </td>
                <td className="px-4 py-3 text-right font-mono">{percent(run.passed, finished)}</td>
                <td className="px-4 py-3 text-right text-xs text-zinc-500">{timeAgo(run.created_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}

export function RunsPage() {
  return (
    <div className="space-y-8">
      <NewRunForm />
      <div>
        <h2 className="mb-3 text-sm font-semibold text-zinc-100">Runs</h2>
        <RunList />
      </div>
    </div>
  )
}
