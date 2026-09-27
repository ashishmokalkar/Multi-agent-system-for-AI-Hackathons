import { useEffect, useMemo, useRef, useState } from 'react'
import AudioPanel from './AudioPanel'
import { advanceCursor, orderedEvents, visibleReplayEvents } from './replay'
import type { AgentStatus, ControlEvent, MetricPayload } from './types'

const AGENTS = [
  { id: 'coordinator', name: 'Coordinator', short: 'CO', role: 'Routes the objective and owns the final summary' },
  { id: 'data_investigator', name: 'Data investigator', short: 'DI', role: 'Checks manifests, labels and split isolation' },
  { id: 'research_modeling_agent', name: 'Research / modeling', short: 'RM', role: 'Defines one bounded matched experiment' },
  { id: 'synthetic_data_engineer', name: 'Synthetic engineer', short: 'SE', role: 'Creates and revises the candidate artifact' },
  { id: 'independent_evaluator', name: 'Independent evaluator', short: 'EV', role: 'Challenges evidence and measures outcomes' },
  { id: 'training_engineer', name: 'Training engineer', short: 'TR', role: 'Runs only allowlisted authorized jobs' },
  { id: 'ensemble_analyst', name: 'Ensemble analyst', short: 'EA', role: 'Compares compatible saved predictions' },
] as const

const ACTIVE_DEMO_AGENTS = new Set([
  'coordinator', 'data_investigator', 'research_modeling_agent', 'synthetic_data_engineer', 'independent_evaluator',
])

function statusFor(agent: string, events: ControlEvent[]): AgentStatus {
  let status: AgentStatus = 'idle'
  for (const event of events) {
    if (event.event_type === 'task_assigned' && ACTIVE_DEMO_AGENTS.has(agent)) status = 'queued'
    if (event.agent === agent && event.event_type === 'agent_started') status = 'running'
    if (event.agent === agent && event.event_type === 'agent_completed') status = 'completed'
    if (event.event_type === 'revision_requested' && event.payload.target === agent) status = 'queued'
    if (event.event_type === 'review_rejected' && agent === 'synthetic_data_engineer') status = 'awaiting review'
    if (event.agent === agent && (event.event_type === 'run_failed' || event.event_type === 'agent_failed')) status = 'failed'
  }
  return status
}

function eventIcon(type: string): string {
  if (type.includes('review_rejected')) return '!'
  if (type.includes('review_accepted')) return '✓'
  if (type.includes('artifact')) return '◇'
  if (type.includes('metric')) return '∑'
  if (type.includes('tool')) return '⌁'
  if (type.includes('completed')) return '✓'
  if (type.includes('failed') || type.includes('cancelled')) return '×'
  return '•'
}

function number(value: number | undefined): string {
  return typeof value === 'number' ? value.toFixed(4) : '—'
}

export default function App() {
  const [events, setEvents] = useState<ControlEvent[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [requestedMode, setRequestedMode] = useState<'mock' | 'live'>('mock')
  const [executionMode, setExecutionMode] = useState<'mock' | 'live' | 'replay'>('mock')
  const [sourceMode, setSourceMode] = useState<'mock' | 'live'>('mock')
  const [liveAvailable, setLiveAvailable] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [presentation, setPresentation] = useState(false)
  const [inspector, setInspector] = useState(false)
  const [recorded, setRecorded] = useState<ControlEvent[]>([])
  const [replayCursor, setReplayCursor] = useState(-1)
  const [replayPlaying, setReplayPlaying] = useState(false)
  const [replaySpeed, setReplaySpeed] = useState(1)
  const [clock, setClock] = useState(Date.now())
  const stream = useRef<EventSource | null>(null)

  useEffect(() => {
    fetch('/api/health').then((response) => response.json()).then((data) => setLiveAvailable(Boolean(data.live_available))).catch(() => setError('Backend is unavailable.'))
    return () => stream.current?.close()
  }, [])

  useEffect(() => {
    if (executionMode !== 'replay' || !replayPlaying || recorded.length === 0) return
    let previous = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now()
      const elapsed = now - previous
      previous = now
      setReplayCursor((current) => {
        const next = advanceCursor(current, elapsed, replaySpeed, recorded.length)
        if (next >= recorded.length - 1) setReplayPlaying(false)
        return next
      })
    }, 80)
    return () => window.clearInterval(timer)
  }, [executionMode, replayPlaying, replaySpeed, recorded.length])

  const visibleEvents = executionMode === 'replay' ? visibleReplayEvents(recorded, replayCursor) : events
  const latest = visibleEvents.at(-1)
  const metricEvent = [...visibleEvents].reverse().find((event) => event.event_type === 'metrics_recorded')
  const metrics = metricEvent?.payload as unknown as MetricPayload | undefined
  const terminal = Boolean(latest && ['run_completed', 'run_failed', 'run_cancelled'].includes(latest.event_type))
  const phaseStart = [...visibleEvents].reverse().find((event) => ['agent_started', 'tool_started', 'job_progress'].includes(event.event_type))
  const elapsedSeconds = phaseStart && executionMode !== 'replay' ? Math.max(0, Math.floor((clock - new Date(phaseStart.created_at).getTime()) / 1000)) : null

  useEffect(() => {
    if (executionMode === 'replay' || terminal || !latest) return
    const timer = window.setInterval(() => setClock(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [executionMode, terminal, latest])

  const modeLabel = executionMode === 'replay'
    ? `RECORDED REPLAY · SOURCE ${sourceMode.toUpperCase()}`
    : executionMode === 'live'
      ? 'LIVE · OPENAI AGENTS + LOCAL TOOLS'
      : 'MOCK · OFFLINE AGENTS + REAL LOCAL TOOLS'

  const start = async () => {
    setError(null)
    setEvents([])
    setRecorded([])
    setReplayCursor(-1)
    stream.current?.close()
    const response = await fetch('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: requestedMode }),
    })
    const body = await response.json()
    if (!response.ok) {
      setError(body.error ?? 'Run could not start.')
      return
    }
    setRunId(body.run_id)
    setExecutionMode(requestedMode)
    setSourceMode(requestedMode)
    const eventSource = new EventSource(`/api/runs/${body.run_id}/stream`)
    stream.current = eventSource
    eventSource.addEventListener('control_room', (message) => {
      const event = JSON.parse((message as MessageEvent).data) as ControlEvent
      setEvents((current) => current.some((item) => item.sequence === event.sequence) ? current : [...current, event])
      if (['run_completed', 'run_failed', 'run_cancelled'].includes(event.event_type)) eventSource.close()
    })
    eventSource.onerror = () => {
      if (!terminal) setError('The event stream closed; persisted run data remains available.')
      eventSource.close()
    }
  }

  const cancel = async () => {
    if (!runId) return
    const response = await fetch(`/api/runs/${runId}/cancel`, { method: 'POST' })
    if (!response.ok) setError('The run had already reached a terminal state.')
  }

  const replay = async () => {
    setError(null)
    stream.current?.close()
    const response = await fetch('/api/recordings/default')
    const body = await response.json()
    if (!response.ok) {
      setError(body.error ?? 'No recorded run is available.')
      return
    }
    const ordered = orderedEvents(body.events as ControlEvent[])
    setRecorded(ordered)
    setReplayCursor(-1)
    setReplayPlaying(true)
    setExecutionMode('replay')
    setSourceMode(body.source_mode === 'live' ? 'live' : 'mock')
    setRunId(body.run_id ?? 'bundled-recording')
  }

  const reset = async () => {
    stream.current?.close()
    await fetch('/api/reset', { method: 'POST' })
    setEvents([])
    setRecorded([])
    setReplayCursor(-1)
    setReplayPlaying(false)
    setRunId(null)
    setError(null)
    setExecutionMode('mock')
  }

  const openArtifact = (artifact: string) => {
    document.getElementById(artifact)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const currentTask = latest?.summary ?? 'Ready for a generated-fixture experiment'
  const visibleFeed = visibleEvents.slice(-8).reverse()

  return (
    <main className={presentation ? 'app presentation' : 'app'}>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><span /><span /><span /></div>
          <div><strong>Audio Competition</strong><small>AGENT CONTROL ROOM</small></div>
        </div>
        <div className={`mode-badge ${executionMode}`}><i />{modeLabel}</div>
        <div className="header-actions">
          <button className="text-button" onClick={() => setPresentation((value) => !value)}>{presentation ? 'Exit presentation' : 'Presentation mode'}</button>
          {!presentation && <button className="icon-button" aria-label="Toggle technical inspector" onClick={() => setInspector((value) => !value)}>⌘</button>}
        </div>
      </header>

      <section className="task-banner">
        <div><span className="eyebrow">CURRENT TASK</span><h1>{currentTask}</h1></div>
        <div className="task-state"><span className={terminal ? 'state-dot complete' : latest ? 'state-dot active' : 'state-dot'} />{terminal ? 'Finished' : latest ? executionMode === 'replay' ? 'Recorded event playback' : `In progress · ${elapsedSeconds ?? 0}s · indeterminate` : 'Standing by'}{latest && !terminal && <span className="indeterminate-track"><i /></span>}</div>
      </section>

      <section className="controls" aria-label="run controls">
        <div className="mode-picker">
          <button className={requestedMode === 'mock' ? 'selected' : ''} onClick={() => setRequestedMode('mock')}>Mock</button>
          <button className={requestedMode === 'live' ? 'selected' : ''} onClick={() => setRequestedMode('live')} title={liveAvailable ? 'Credentials detected' : 'OPENAI_API_KEY not available'}>Live {!liveAvailable && <span>locked</span>}</button>
        </div>
        <button className="primary-button" onClick={start} disabled={requestedMode === 'live' && !liveAvailable}>▶ Start run</button>
        <button className="control-button danger" onClick={cancel} disabled={!runId || terminal || executionMode === 'replay'}>■ Cancel</button>
        <button className="control-button" onClick={replay}>↻ Recorded replay</button>
        <button className="control-button" onClick={reset}>Reset view</button>
        {executionMode === 'replay' && (
          <div className="replay-controls">
            <button onClick={() => setReplayPlaying((value) => !value)}>{replayPlaying ? 'Ⅱ Pause' : '▶ Play'}</button>
            <input aria-label="Replay seek" type="range" min="-1" max={Math.max(0, recorded.length - 1)} step="0.01" value={replayCursor} onChange={(event) => { setReplayCursor(Number(event.target.value)); setReplayPlaying(false) }} />
            <select aria-label="Replay speed" value={replaySpeed} onChange={(event) => setReplaySpeed(Number(event.target.value))}>
              <option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option>
            </select>
          </div>
        )}
      </section>

      {error && <div className="error-banner" role="alert">{error}</div>}

      <section className="agent-flow" aria-label="agent workflow">
        {AGENTS.map((agent, index) => {
          const status = statusFor(agent.id, visibleEvents)
          const pulsing = latest?.agent === agent.id && ['task_assigned', 'agent_started', 'tool_started', 'revision_requested'].includes(latest.event_type)
          return (
            <article key={agent.id} className={`agent-card ${status.replace(' ', '-')} ${pulsing ? 'handoff-pulse' : ''}`}>
              <div className="agent-index">0{index + 1}</div>
              <div className="agent-avatar">{agent.short}</div>
              <div className="agent-copy"><h3>{agent.name}</h3><p>{agent.role}</p></div>
              <span className="agent-status"><i />{status}</span>
            </article>
          )
        })}
      </section>

      <section className="content-grid">
        <AudioPanel events={visibleEvents} onArtifactOpen={openArtifact} />

        <aside className="right-rail">
          <section className="panel metrics-panel">
            <header className="panel-heading"><div><span className="eyebrow">OBSERVED RESULT</span><h2>Baseline vs candidate</h2></div></header>
            <p className="metric-scope">{metrics?.label ?? 'Awaiting actual CPU scoring — no values inferred'}</p>
            <div className="metric-table">
              <div className="metric-row header"><span>Metric</span><span>Baseline</span><span>Candidate</span></div>
              <div className="metric-row"><span>Event F1</span><strong>{number(metrics?.baseline.event_f1)}</strong><strong>{number(metrics?.candidate.event_f1)}</strong></div>
              <div className="metric-row"><span>Segment Dice</span><strong>{number(metrics?.baseline.segment_dice)}</strong><strong>{number(metrics?.candidate.segment_dice)}</strong></div>
              <div className="metric-row combined"><span>Combined</span><strong>{number(metrics?.baseline.combined)}</strong><strong>{number(metrics?.candidate.combined)}</strong></div>
            </div>
            <p className="metric-footnote">Generated fixture only. These are never presented as leaderboard or validation results.</p>
          </section>

          <section className="panel feed-panel">
            <header className="panel-heading"><div><span className="eyebrow">CHRONOLOGICAL</span><h2>Activity feed</h2></div><span className="event-count">{visibleEvents.length} events</span></header>
            <ol className="activity-feed">
              {visibleFeed.length === 0 && <li className="empty-feed">No activity yet.</li>}
              {visibleFeed.map((event) => (
                <li key={event.sequence} className={event.event_type} onClick={() => event.payload.artifact_id && openArtifact(String(event.payload.artifact_id))}>
                  <span className="feed-icon">{eventIcon(event.event_type)}</span>
                  <div><strong>{event.summary}</strong><small>{event.agent?.replaceAll('_', ' ') ?? 'system'} · {new Date(event.created_at).toLocaleTimeString()}</small></div>
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </section>

      {inspector && !presentation && (
        <details className="inspector" open>
          <summary>Technical inspector</summary>
          <div className="inspector-grid">
            <div><span>Run ID</span><code>{runId ?? 'none'}</code></div>
            <div><span>Mode provenance</span><code>{modeLabel}</code></div>
            <div><span>Latest sequence</span><code>{latest?.sequence ?? 0}</code></div>
            <div><span>Wall-clock timestamp</span><code>{latest?.created_at ?? 'none'}</code></div>
          </div>
          <pre>{latest ? JSON.stringify(latest, null, 2) : 'No event selected.'}</pre>
        </details>
      )}

      <footer><span>Deterministic fixture · bounded revision · no GPU training</span><span>github-ready / audio-competition-agents</span></footer>
    </main>
  )
}
