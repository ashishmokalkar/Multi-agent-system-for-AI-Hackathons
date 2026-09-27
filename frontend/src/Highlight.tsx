import { useEffect, useMemo, useRef, useState } from 'react'
import { HIGHLIGHT_DURATION_SECONDS, beatAt, handoffAgent, localBeatProgress, participatingAgents } from './highlight'
import type { ControlEvent, FixtureInfo } from './types'
import './highlight.css'

const NAMES: Record<string, string> = {
  coordinator: 'Coordinator',
  data_investigator: 'Data Analysis',
  research_modeling_agent: 'Modeling',
  synthetic_data_engineer: 'Synthetic Data',
  independent_evaluator: 'Evaluation',
  training_engineer: 'Training',
  ensemble_analyst: 'Ensemble',
}

const TASKS: Record<string, string> = {
  coordinator: 'Plan + summarize',
  data_investigator: 'Validate isolation',
  research_modeling_agent: 'Define experiment',
  synthetic_data_engineer: 'Build + revise artifact',
  independent_evaluator: 'Independent verification',
  training_engineer: 'Execute training',
  ensemble_analyst: 'Compare predictions',
}

interface Recording {
  source_mode: 'mock' | 'live'
  capture_kind: string
  events: ControlEvent[]
}

function drawWave(canvas: HTMLCanvasElement, samples: Float32Array): void {
  const context = canvas.getContext('2d')
  if (!context) return
  const width = canvas.width
  const height = canvas.height
  context.clearRect(0, 0, width, height)
  const gradient = context.createLinearGradient(0, 0, width, 0)
  gradient.addColorStop(0, 'rgba(60, 207, 226, .28)')
  gradient.addColorStop(.5, 'rgba(94, 234, 212, .82)')
  gradient.addColorStop(1, 'rgba(60, 207, 226, .28)')
  context.strokeStyle = gradient
  context.lineWidth = 2
  context.beginPath()
  const step = Math.max(1, Math.floor(samples.length / width))
  for (let x = 0; x < width; x += 1) {
    let low = 1
    let high = -1
    for (let offset = 0; offset < step; offset += 1) {
      const value = samples[x * step + offset] ?? 0
      low = Math.min(low, value)
      high = Math.max(high, value)
    }
    context.moveTo(x, (1 - high) * height / 2)
    context.lineTo(x, (1 - low) * height / 2)
  }
  context.stroke()
}

function Waveform({ samples, subdued = false }: { samples: Float32Array | null; subdued?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (canvas.current && samples) drawWave(canvas.current, samples)
  }, [samples])
  return <canvas ref={canvas} width="1400" height="280" className={subdued ? 'wave-canvas subdued' : 'wave-canvas'} aria-hidden="true" />
}

export default function Highlight() {
  const query = useMemo(() => new URLSearchParams(window.location.search), [])
  const layout = window.location.pathname.includes('/vertical') || query.get('layout') === 'vertical' ? 'vertical' : 'landscape'
  const fixed = query.has('t') ? Number(query.get('t')) : null
  const captureMode = fixed !== null || query.get('autoplay') === '1'
  const [recording, setRecording] = useState<Recording | null>(null)
  const [fixture, setFixture] = useState<FixtureInfo | null>(null)
  const [samples, setSamples] = useState<Float32Array | null>(null)
  const [elapsed, setElapsed] = useState(Number.isFinite(fixed) ? Math.max(0, Math.min(HIGHLIGHT_DURATION_SECONDS, fixed!)) : 0)
  const [isPlaying, setIsPlaying] = useState(fixed === null)
  const elapsedRef = useRef(elapsed)

  useEffect(() => {
    elapsedRef.current = elapsed
  }, [elapsed])

  useEffect(() => {
    Promise.all([
      fetch('/api/recordings/default').then((response) => response.json()),
      fetch('/api/demo/fixture').then((response) => response.json()),
    ]).then(([captured, fixtureData]) => {
      setRecording(captured)
      setFixture(fixtureData)
      ;(window as unknown as { __HIGHLIGHT_READY__: boolean }).__HIGHLIGHT_READY__ = true
    })
  }, [])

  useEffect(() => {
    if (!fixture) return
    fetch(fixture.audio_url).then((response) => response.arrayBuffer()).then(async (buffer) => {
      const audioContext = new AudioContext()
      const decoded = await audioContext.decodeAudioData(buffer)
      setSamples(new Float32Array(decoded.getChannelData(0)))
      await audioContext.close()
    })
  }, [fixture])

  useEffect(() => {
    if (!recording || !fixture || fixed !== null || !isPlaying) return
    const base = elapsedRef.current >= HIGHLIGHT_DURATION_SECONDS ? 0 : elapsedRef.current
    const started = performance.now()
    let frame = 0
    const render = (now: number) => {
      const seconds = Math.min(HIGHLIGHT_DURATION_SECONDS, base + (now - started) / 1000)
      setElapsed(seconds)
      if (seconds < HIGHLIGHT_DURATION_SECONDS) {
        frame = requestAnimationFrame(render)
      } else {
        setIsPlaying(false)
        ;(window as unknown as { __HIGHLIGHT_COMPLETE__: boolean }).__HIGHLIGHT_COMPLETE__ = true
      }
    }
    frame = requestAnimationFrame(render)
    return () => cancelAnimationFrame(frame)
  }, [recording, fixture, fixed, isPlaying])

  const replay = () => {
    ;(window as unknown as { __HIGHLIGHT_COMPLETE__: boolean }).__HIGHLIGHT_COMPLETE__ = false
    setElapsed(0)
    setIsPlaying(true)
  }

  const togglePlayback = () => {
    if (elapsed >= HIGHLIGHT_DURATION_SECONDS) replay()
    else setIsPlaying((value) => !value)
  }

  if (!recording || !fixture) {
    return <main className={`highlight ${layout}`}><div className="highlight-loading">Loading recorded run</div></main>
  }

  const events = recording.events
  const beat = beatAt(elapsed)
  const progress = localBeatProgress(elapsed, beat)
  const agents = participatingAgents(events)
  const activeAgent = beat.id === 'orchestration' ? handoffAgent(events, progress) : null
  const rejection = events.find((event) => event.event_type === 'review_rejected')
  const correction = events.find((event) => event.event_type === 'artifact_created' && event.payload.artifact_id === 'corrected_annotation')
  const accepted = events.find((event) => event.event_type === 'review_accepted')
  const complete = events.find((event) => event.event_type === 'run_completed')
  const changes = (rejection?.payload.changes ?? []) as Array<{ field: string; delta_seconds: number }>
  const correctedInterval = (correction?.payload.proposed_correction ?? fixture.known_reference) as [number, number]
  const showCorrection = beat.id === 'verification' && progress >= .56
  const interval = showCorrection ? correctedInterval : fixture.original_annotation
  const verificationStage = progress < .34 ? 0 : progress < .68 ? 1 : 2
  const progressPercent = Math.min(100, (elapsed / HIGHLIGHT_DURATION_SECONDS) * 100)
  const provenance = recording.source_mode === 'mock' ? 'Illustrative demo · mock execution' : 'Recorded agent run'

  return (
    <main className={`highlight ${layout} ${captureMode ? 'capture-mode' : 'review-mode'}`} data-layout={layout} data-beat={beat.id}>
      <header className="highlight-header">
        <div className="highlight-brand">
          <i aria-hidden="true"><span /><span /><span /></i>
          <div><strong>Audio Competition Agents</strong><small>TECHNICAL PRODUCT DEMO</small></div>
        </div>
        <div className="capture-provenance"><span>Recorded run · accelerated</span><b>{provenance}</b></div>
      </header>

      <section className="highlight-stage" key={beat.id}>
        {beat.id === 'title' && (
          <div className="scene scene-title">
            <div className="title-content" style={{ transform: `translate3d(${(progress - .5) * 16}px, ${-38 - progress * 4}px, 0) scale(${1 + progress * .01})` }}>
              <span className="scene-index">MULTI-AGENT ORCHESTRATION</span>
              <h1><span>Multi-Agent AI System</span>{' '}<span>for AI Hackathons</span></h1>
              <p><span>Solving real-world ML problems</span>{' '}<span>with agentic swarms.</span></p>
              <div className="title-techline">
                <span><strong>{events.length}</strong> structured events</span>
                <span><strong>{agents.length}</strong> active roles</span>
                <span><strong>1</strong> verified revision</span>
              </div>
            </div>
            <div className="title-wave" style={{ transform: `translateX(${(progress - .5) * 24}px) scaleY(${1 + Math.sin(progress * Math.PI) * .08})` }}>
              <Waveform samples={samples} subdued />
              <div className="wave-axis" />
              <div className="signal-scan" style={{ left: `${progress * 100}%` }}><span>{(progress * fixture.duration_seconds).toFixed(2)} s</span></div>
            </div>
          </div>
        )}

        {beat.id === 'orchestration' && (
          <div className="scene scene-orchestration">
            <div className="scene-heading"><span>01 · ORCHESTRATION</span><h1>{beat.caption}</h1></div>
            <div className="orchestration-flow">
              {agents.map((agent, index) => (
                <div className="agent-step" key={agent}>
                  <div className={`agent-node ${activeAgent === agent ? 'active' : ''}`}>
                    <i>{String(index + 1).padStart(2, '0')}</i>
                    <strong>{NAMES[agent] ?? agent}</strong>
                    <span>{TASKS[agent] ?? 'Recorded task'}</span>
                    {activeAgent === agent && <em>Processing</em>}
                  </div>
                  {index < agents.length - 1 && <div className={`agent-link ${activeAgent === agents[index + 1] ? 'active' : ''}`}><span /><i /></div>}
                </div>
              ))}
            </div>
            <div className="orchestration-readout">
              <span>RECORDED HANDOFF</span>
              <strong>{activeAgent ? TASKS[activeAgent] : 'Plan objective'}</strong>
              <i>{String(Math.max(1, Math.ceil(progress * events.length))).padStart(2, '0')} / {events.length}</i>
            </div>
          </div>
        )}

        {beat.id === 'verification' && (
          <div className="scene scene-verification">
            <div className="scene-heading"><span>02 · WORK + VERIFICATION</span><h1>{beat.caption}</h1></div>
            <div className="verification-steps">
              {['Detect mismatch', 'Revise boundaries', 'Independent validation'].map((label, index) => <div className={index <= verificationStage ? 'active' : ''} key={label}><i>{index < verificationStage ? '✓' : String(index + 1)}</i><span>{label}</span></div>)}
            </div>
            <div className="verification-grid">
              <div className="artifact-panel">
                <div className="artifact-label"><span>WAVEFORM ANNOTATION</span><b>{showCorrection ? 'REVISION 1' : 'INITIAL ARTIFACT'}</b></div>
                <div className="artifact-wave">
                  <Waveform samples={samples} />
                  <div className="analysis-cursor" style={{ left: `${progress * 100}%` }} />
                  <div className="reference-interval" style={{ left: `${fixture.known_reference[0] / fixture.duration_seconds * 100}%`, width: `${(fixture.known_reference[1] - fixture.known_reference[0]) / fixture.duration_seconds * 100}%` }}><span>Reference</span></div>
                  <div className={`candidate-interval ${showCorrection ? 'corrected' : ''}`} style={{ left: `${interval[0] / fixture.duration_seconds * 100}%`, width: `${(interval[1] - interval[0]) / fixture.duration_seconds * 100}%` }}><span>{showCorrection ? 'Corrected' : 'Submitted'}</span></div>
                </div>
                <div className="artifact-times"><span>0.000 s</span><strong>{interval[0].toFixed(3)}–{interval[1].toFixed(3)} s</strong><span>{fixture.duration_seconds.toFixed(3)} s</span></div>
              </div>
              <aside className={`review-panel ${showCorrection ? 'accepted' : 'rejected'}`}>
                <span className="review-label">INDEPENDENT EVALUATION</span>
                <h2>{showCorrection ? 'Revision verified' : 'Boundary check failed'}</h2>
                {showCorrection ? (
                  <div className="review-result"><strong>Accepted</strong><p>{accepted?.summary ?? 'Evaluator accepted revision 1'}</p></div>
                ) : (
                  <div className="review-deltas">{changes.map((change) => <div key={change.field}><span>{change.field} delta</span><strong>{change.delta_seconds > 0 ? '+' : ''}{change.delta_seconds.toFixed(3)} s</strong></div>)}</div>
                )}
              </aside>
            </div>
          </div>
        )}

        {beat.id === 'outcome' && (
          <div className="scene scene-outcome">
            <span className="scene-index">03 · OUTCOME</span>
            <div className="completion-mark" aria-hidden="true"><span>✓</span><i /></div>
            <h1>Workflow complete</h1>
            <p>{complete?.summary ?? 'Completed after independent review.'}</p>
            <div className="outcome-trace">
              <div><i>✓</i><span>Boundary check</span><strong>Finding recorded</strong></div>
              <div><i>✓</i><span>Artifact revision</span><strong>Coordinates corrected</strong></div>
              <div><i>✓</i><span>Independent review</span><strong>Revision accepted</strong></div>
            </div>
            <small>Generated fixture · recorded mock execution</small>
          </div>
        )}

        {beat.id === 'end' && (
          <div className="scene scene-end">
            <div className="end-mark" aria-hidden="true"><span /><span /><span /></div>
            <h1><span>Multi-Agent AI System</span>{' '}<span>for AI Hackathons</span></h1>
            <p>Explore the workflow on GitHub</p>
            <div className="end-signal"><i /><i /><i /><i /><i /></div>
          </div>
        )}
      </section>

      <footer className="highlight-footer">
        <span>{beat.caption}</span>
        <div className="highlight-progress"><i style={{ width: `${progressPercent}%` }} /></div>
        <strong>{elapsed.toFixed(1)} / {HIGHLIGHT_DURATION_SECONDS.toFixed(1)} s</strong>
      </footer>

      {!captureMode && (
        <nav className="replay-controls" aria-label="Highlight replay controls">
          <button type="button" onClick={togglePlayback}>{isPlaying ? 'Pause' : 'Play'}</button>
          <button type="button" onClick={replay}>Replay</button>
          <input aria-label="Highlight timeline" type="range" min="0" max={HIGHLIGHT_DURATION_SECONDS} step=".01" value={elapsed} onChange={(event) => { setIsPlaying(false); setElapsed(Number(event.target.value)) }} />
        </nav>
      )}
    </main>
  )
}
