// Types and fetch helpers for the Invigilator API.

export type TrialStatus =
  | 'queued' | 'running' | 'cancelled'
  | 'PASS' | 'FAIL' | 'TAMPER' | 'LIMIT' | 'ERROR'

export type RunStatus = 'queued' | 'running' | 'done' | 'cancelled'

export interface RunSummary {
  id: string
  model: string
  status: RunStatus
  created_at: string
  finished_at: string | null
  total: number
  passed: number
  failed: number
  tampered: number
  running: number
  tasks: string[]
}

export interface TrialRow {
  id: string
  task: string
  trial_no: number
  status: TrialStatus
  steps: number | null
  duration: number | null
  detail: string | null
  started_at: string | null
  finished_at: string | null
}

export interface RunDetail extends RunSummary {
  base_url: string
  max_steps: number
  limits: Record<string, number | boolean>
  trials: TrialRow[]
}

export interface Step {
  index: number
  thought: string
  command: string
  exit_code: number | null
  output: string
  duration: number
}

export interface Trajectory {
  steps: Step[]
  finished: boolean
  stop_reason: string
  summary: string
  llm_calls: number
  prompt_tokens: number
  completion_tokens: number
  error: string | null
}

export interface TrialResult {
  passed: boolean
  tests_passed: boolean
  test_output: string
  duration: number
  error: string | null
  violation: string | null
  tampering: string[]
  changed_files: string[]
  peak_disk_mb: number
  trajectory: Trajectory | null
}

export interface TrialDetail extends TrialRow {
  run_id: string
  model: string
  instruction: string | null
  result: TrialResult | null
  live_steps?: Step[]
}

export interface TaskInfo {
  name: string
  instruction: string
}

export interface NewRun {
  tasks: string[]
  trials: number
  model: string
  max_steps: number
}

export type RunEvent =
  | { type: 'trial'; id: string; status: TrialStatus; steps?: number; duration?: number; detail?: string }
  | { type: 'step'; trial_id: string; step: Step }
  | { type: 'run'; id: string; status: RunStatus }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `${resp.status} ${resp.statusText}`)
  }
  return resp.json() as Promise<T>
}

export const api = {
  tasks: () => request<TaskInfo[]>('/api/tasks'),
  runs: () => request<RunSummary[]>('/api/runs'),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  trial: (id: string) => request<TrialDetail>(`/api/trials/${id}`),
  createRun: (body: NewRun) =>
    request<{ id: string; trials: number }>('/api/runs', { method: 'POST', body: JSON.stringify(body) }),
  cancelRun: (id: string) => request<{ cancelled: number }>(`/api/runs/${id}/cancel`, { method: 'POST' }),
}

/** Subscribe to a run's live events (Server-Sent Events). Returns an unsubscribe function. */
export function subscribeToRun(runId: string, onEvent: (event: RunEvent) => void): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`)
  source.onmessage = (message) => onEvent(JSON.parse(message.data) as RunEvent)
  return () => source.close()
}
