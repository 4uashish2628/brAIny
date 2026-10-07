// One trial: what the agent did, step by step. Live while running; replayable after.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, subscribeToRun, type Step, type TrialDetail } from './api'
import { href, seconds, STATUS_HELP } from './lib'
import { Card, ErrorNote, Loading, StatusBadge } from './ui'

const FINISHED = ['PASS', 'FAIL', 'TAMPER', 'LIMIT', 'ERROR', 'cancelled']
const SPEEDS = [1, 2, 4]

function StepCard({ step, latest }: { step: Step; latest: boolean }) {
  const ok = step.exit_code === 0
  return (
    <div className={`rounded-xl border bg-zinc-900/50 transition ${latest ? 'border-zinc-600' : 'border-zinc-800'}`}>
      {step.thought && (
        <details className="border-b border-zinc-800 px-4 py-2 text-sm text-zinc-400">
          <summary className="cursor-pointer select-none text-xs text-zinc-500">model reasoning</summary>
          <p className="mt-2 whitespace-pre-wrap">{step.thought}</p>
        </details>
      )}
      <div className="flex items-start gap-3 px-4 py-3">
        <span className="mt-0.5 w-6 shrink-0 text-right font-mono text-xs text-zinc-600">{step.index}</span>
        <code className="flex-1 whitespace-pre-wrap break-all font-mono text-sm text-zinc-100">
          <span className="select-none text-emerald-400">$ </span>{step.command}
        </code>
        <span className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-xs ${ok ? 'bg-emerald-500/10 text-emerald-300' : 'bg-rose-500/10 text-rose-300'}`}>
          exit {step.exit_code ?? '?'}
        </span>
        <span className="w-12 shrink-0 text-right font-mono text-xs text-zinc-500">{seconds(step.duration)}</span>
      </div>
      {step.output && (
        <pre className="max-h-64 overflow-auto border-t border-zinc-800 bg-zinc-950/70 px-4 py-3 font-mono text-xs leading-relaxed text-zinc-400">
          {step.output}
        </pre>
      )}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm text-zinc-200">{value}</dd>
    </div>
  )
}

export function TrialPage({ id }: { id: string }) {
  const [trial, setTrial] = useState<TrialDetail | null>(null)
  const [steps, setSteps] = useState<Step[]>([])
  const [error, setError] = useState<string | null>(null)
  const [shown, setShown] = useState<number | null>(null) // null = show all (live / not replaying)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const bottom = useRef<HTMLDivElement>(null)

  const load = useCallback(
    () =>
      api.trial(id)
        .then((t) => {
          setTrial(t)
          setSteps(t.result?.trajectory?.steps ?? t.live_steps ?? [])
        })
        .catch((e: Error) => setError(e.message)),
    [id],
  )

  useEffect(() => {
    void load()
  }, [load])

  // Live updates while the trial is queued or running.
  const runId = trial?.run_id
  const live = trial != null && !FINISHED.includes(trial.status)
  useEffect(() => {
    if (!runId || !live) return
    return subscribeToRun(runId, (event) => {
      if (event.type === 'step' && event.trial_id === id) {
        setSteps((prev) => (prev.some((s) => s.index === event.step.index) ? prev : [...prev, event.step]))
      } else if (event.type === 'trial' && event.id === id) {
        if (FINISHED.includes(event.status)) load()
        else setTrial((prev) => prev && { ...prev, status: event.status })
      }
    })
  }, [runId, live, id, load])

  // Replay ticker. Playback ends by itself when the last step is shown.
  const isPlaying = playing && shown != null && shown < steps.length
  useEffect(() => {
    if (!isPlaying) return
    const timer = setTimeout(() => setShown((s) => (s ?? 0) + 1), 1200 / speed)
    return () => clearTimeout(timer)
  }, [isPlaying, shown, speed])

  // Keep the newest step in view while live or replaying.
  const visible = shown == null ? steps : steps.slice(0, shown)
  useEffect(() => {
    if (live || isPlaying) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [visible.length, live, isPlaying])

  // Arrow keys step through the replay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (live || steps.length === 0) return
      if (e.key === 'ArrowRight') setShown((s) => Math.min((s ?? steps.length) + 1, steps.length))
      if (e.key === 'ArrowLeft') setShown((s) => Math.max((s ?? steps.length) - 1, 0))
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') setPlaying(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [live, steps.length])

  if (error) return <ErrorNote error={error} />
  if (!trial) return <Loading />

  const result = trial.result
  const traj = result?.trajectory
  const position = shown ?? steps.length
  const button = 'rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 transition hover:border-zinc-500 disabled:opacity-30'

  return (
    <div className="space-y-6">
      <div>
        <a href={href.run(trial.run_id)} className="text-xs text-zinc-500 hover:text-zinc-300">← Run {trial.run_id}</a>
        <h1 className="mt-1 flex flex-wrap items-center gap-3 text-xl font-semibold text-zinc-100">
          <span className="font-mono">{trial.task}</span>
          <span className="text-zinc-500">#{trial.trial_no}</span>
          <StatusBadge status={trial.status} />
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          <span className="font-mono text-zinc-300">{trial.model}</span>
          {STATUS_HELP[trial.status] && <> · {STATUS_HELP[trial.status]}</>}
        </p>
      </div>

      {result?.tampering?.length ? (
        <div className="rounded-xl border border-fuchsia-500/30 bg-fuchsia-500/10 px-4 py-3 text-sm text-fuchsia-200">
          <p className="font-semibold">Tampering detected: the agent changed files the tests depend on.</p>
          <ul className="mt-2 font-mono text-xs">{result.tampering.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      ) : null}
      {result?.violation && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <span className="font-semibold">Resource limit:</span> {result.violation}
        </div>
      )}
      {result?.error && <ErrorNote error={result.error} />}

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-auto text-sm font-semibold text-zinc-100">
              Trajectory {live ? <span className="text-sky-300">· live</span> : null}
            </h2>
            {!live && steps.length > 0 && (
              <>
                <button className={button} onClick={() => { setShown(0); setPlaying(true) }}>⟲ Replay</button>
                <button className={button} disabled={position === 0} onClick={() => { setPlaying(false); setShown(Math.max(position - 1, 0)) }}>◀</button>
                <button className={button} disabled={shown == null || shown >= steps.length}
                        onClick={() => setPlaying(!isPlaying)}>
                  {isPlaying ? '❚❚ Pause' : '▶ Play'}
                </button>
                <button className={button} disabled={position >= steps.length} onClick={() => { setPlaying(false); setShown(position + 1) }}>▶</button>
                <button className={button} onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])}>{speed}×</button>
                <span className="w-16 text-right font-mono text-xs text-zinc-500">{position}/{steps.length}</span>
              </>
            )}
          </div>
          {!live && steps.length > 0 && (
            <input type="range" min={0} max={steps.length} value={position} aria-label="Replay position"
                   onChange={(e) => { setPlaying(false); setShown(Number(e.target.value)) }}
                   className="w-full accent-emerald-400" />
          )}

          {trial.instruction && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3">
              <div className="mb-1 text-xs uppercase tracking-wide text-zinc-500">Task given to the agent</div>
              <p className="whitespace-pre-wrap text-sm text-zinc-300">{trial.instruction}</p>
            </div>
          )}

          {visible.map((step, i) => <StepCard key={step.index} step={step} latest={i === visible.length - 1} />)}
          {steps.length === 0 && (
            <p className="text-sm text-zinc-500">{trial.status === 'queued' ? 'Waiting for a worker…' : live ? 'Waiting for the first command…' : 'The agent ran no commands.'}</p>
          )}
          {live && <p className="animate-pulse text-xs text-sky-300">agent is working…</p>}
          {!live && traj && position === steps.length && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3 text-sm">
              <span className="text-zinc-500">Agent stopped: </span>
              <span className="font-mono text-zinc-200">{traj.stop_reason}</span>
              {traj.summary && <p className="mt-1 text-zinc-400">“{traj.summary}”</p>}
            </div>
          )}
          <div ref={bottom} />
        </div>

        <aside className="space-y-4">
          <Card className="p-4">
            <dl className="grid grid-cols-2 gap-4">
              <Fact label="Duration" value={seconds(trial.duration)} />
              <Fact label="Commands" value={String(steps.length)} />
              <Fact label="Model calls" value={String(traj?.llm_calls ?? '—')} />
              <Fact label="Tokens" value={traj ? (traj.prompt_tokens + traj.completion_tokens).toLocaleString() : '—'} />
              <Fact label="Peak disk" value={result ? `${result.peak_disk_mb} MB` : '—'} />
              <Fact label="Tests" value={result ? (result.tests_passed ? 'passed' : 'failed') : '—'} />
            </dl>
          </Card>
          {result && (
            <Card className="p-4">
              <h3 className="mb-2 text-xs uppercase tracking-wide text-zinc-500">Verifier output</h3>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs text-zinc-300">
                {result.test_output || '(none)'}
              </pre>
            </Card>
          )}
          {result && result.changed_files.length > 0 && (
            <Card className="p-4">
              <details>
                <summary className="cursor-pointer text-xs uppercase tracking-wide text-zinc-500">
                  Files changed ({result.changed_files.length})
                </summary>
                <ul className="mt-2 max-h-64 overflow-auto font-mono text-xs text-zinc-400">
                  {result.changed_files.map((f) => <li key={f}>{f}</li>)}
                </ul>
              </details>
            </Card>
          )}
        </aside>
      </div>
    </div>
  )
}
