import { useEffect, useMemo, useRef, useState } from 'react'
import type { ControlEvent, FixtureInfo } from './types'

interface Props {
  events: ControlEvent[]
  onArtifactOpen: (artifact: string) => void
}

function formatTime(value: number): string {
  return `${value.toFixed(3)} s`
}

function drawWaveform(canvas: HTMLCanvasElement, samples: Float32Array): void {
  const width = canvas.width
  const height = canvas.height
  const context = canvas.getContext('2d')!
  context.clearRect(0, 0, width, height)
  const gradient = context.createLinearGradient(0, 0, width, 0)
  gradient.addColorStop(0, '#70d6ff')
  gradient.addColorStop(0.55, '#8c7dff')
  gradient.addColorStop(1, '#52f2b8')
  context.strokeStyle = gradient
  context.lineWidth = 1.4
  context.beginPath()
  const step = Math.max(1, Math.floor(samples.length / width))
  for (let x = 0; x < width; x += 1) {
    let minimum = 1
    let maximum = -1
    const start = x * step
    for (let offset = 0; offset < step && start + offset < samples.length; offset += 1) {
      const value = samples[start + offset]
      minimum = Math.min(minimum, value)
      maximum = Math.max(maximum, value)
    }
    context.moveTo(x, (1 - maximum) * height * 0.5)
    context.lineTo(x, (1 - minimum) * height * 0.5)
  }
  context.stroke()
}

function drawSpectrogram(canvas: HTMLCanvasElement, samples: Float32Array): void {
  const context = canvas.getContext('2d')!
  const width = canvas.width
  const height = canvas.height
  context.fillStyle = '#07101b'
  context.fillRect(0, 0, width, height)
  const columns = Math.min(300, width)
  const bins = 52
  const fft = 128
  for (let column = 0; column < columns; column += 1) {
    const center = Math.floor((column / Math.max(1, columns - 1)) * Math.max(0, samples.length - fft))
    for (let bin = 1; bin <= bins; bin += 1) {
      let real = 0
      let imaginary = 0
      for (let index = 0; index < fft; index += 1) {
        const window = 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / (fft - 1))
        const angle = (2 * Math.PI * bin * index) / fft
        const sample = samples[center + index] * window
        real += sample * Math.cos(angle)
        imaginary -= sample * Math.sin(angle)
      }
      const db = 20 * Math.log10(Math.sqrt(real * real + imaginary * imaginary) / fft + 1e-5)
      const intensity = Math.max(0, Math.min(1, (db + 76) / 64))
      const hue = 225 - intensity * 95
      context.fillStyle = `hsla(${hue}, 88%, ${8 + intensity * 58}%, ${0.35 + intensity * 0.65})`
      const x = (column / columns) * width
      const y = height - (bin / bins) * height
      context.fillRect(x, y, Math.ceil(width / columns) + 1, Math.ceil(height / bins) + 1)
    }
  }
}

export default function AudioPanel({ events, onArtifactOpen }: Props) {
  const [fixture, setFixture] = useState<FixtureInfo | null>(null)
  const [after, setAfter] = useState(false)
  const [loop, setLoop] = useState(false)
  const [slow, setSlow] = useState(false)
  const [cursor, setCursor] = useState(0)
  const waveform = useRef<HTMLCanvasElement>(null)
  const spectrogram = useRef<HTMLCanvasElement>(null)
  const audio = useRef<HTMLAudioElement>(null)

  const corrected = events.some((event) => event.event_type === 'artifact_created' && event.payload.artifact_id === 'corrected_annotation')
  const rejected = events.some((event) => event.event_type === 'review_rejected')
  const activeAfter = after && corrected
  const proposed = useMemo<[number, number]>(() => {
    if (!fixture) return [0, 0]
    return activeAfter ? fixture.known_reference : fixture.original_annotation
  }, [fixture, activeAfter])

  useEffect(() => {
    fetch('/api/demo/fixture').then((response) => response.json()).then(setFixture)
  }, [])

  useEffect(() => {
    if (!fixture) return
    fetch(fixture.audio_url)
      .then((response) => response.arrayBuffer())
      .then(async (buffer) => {
        const context = new AudioContext()
        const decoded = await context.decodeAudioData(buffer)
        if (waveform.current) drawWaveform(waveform.current, decoded.getChannelData(0))
        if (spectrogram.current) drawSpectrogram(spectrogram.current, decoded.getChannelData(0))
        await context.close()
      })
  }, [fixture])

  useEffect(() => {
    if (corrected) setAfter(true)
  }, [corrected])

  useEffect(() => {
    if (audio.current) audio.current.playbackRate = slow ? 0.65 : 1
  }, [slow])

  useEffect(() => {
    let frame = 0
    const update = () => {
      if (audio.current) setCursor(audio.current.currentTime)
      frame = requestAnimationFrame(update)
    }
    frame = requestAnimationFrame(update)
    return () => cancelAnimationFrame(frame)
  }, [])

  if (!fixture) {
    return <section className="panel audio-panel loading">Preparing generated fixture…</section>
  }

  const duration = fixture.duration_seconds
  const originalStyle = { left: `${(fixture.original_annotation[0] / duration) * 100}%`, width: `${((fixture.original_annotation[1] - fixture.original_annotation[0]) / duration) * 100}%` }
  const proposedStyle = { left: `${(proposed[0] / duration) * 100}%`, width: `${((proposed[1] - proposed[0]) / duration) * 100}%` }
  const referenceStyle = { left: `${(fixture.known_reference[0] / duration) * 100}%`, width: `${((fixture.known_reference[1] - fixture.known_reference[0]) / duration) * 100}%` }
  const cursorStyle = { left: `${Math.min(100, (cursor / duration) * 100)}%` }

  const onTimeUpdate = () => {
    const player = audio.current
    if (!player || !loop) return
    if (player.currentTime < proposed[0] || player.currentTime >= proposed[1]) player.currentTime = proposed[0]
  }

  const playEvent = async () => {
    if (!audio.current) return
    audio.current.currentTime = proposed[0]
    await audio.current.play()
  }

  return (
    <section className="panel audio-panel" id="fixture_audio">
      <header className="panel-heading">
        <div>
          <span className="eyebrow">CENTRAL ARTIFACT · GENERATED FIXTURE</span>
          <h2>Boundary inspection</h2>
        </div>
        <button className="text-button" onClick={() => onArtifactOpen('fixture_audio')}>Open details ↗</button>
      </header>

      <div className="audio-toolbar">
        <div className="segmented" aria-label="annotation version">
          <button className={!activeAfter ? 'selected' : ''} onClick={() => setAfter(false)}>Before</button>
          <button className={activeAfter ? 'selected' : ''} disabled={!corrected} onClick={() => setAfter(true)}>After revision</button>
        </div>
        <button className="tool-button" onClick={playEvent}>▶ Play annotated event</button>
        <label className="toggle"><input type="checkbox" checked={loop} onChange={(event) => setLoop(event.target.checked)} /> Loop event</label>
        <label className="toggle"><input type="checkbox" checked={slow} onChange={(event) => setSlow(event.target.checked)} /> 0.65×</label>
      </div>

      <div className={`visual-stack ${rejected && !activeAfter ? 'defect-visible' : ''}`}>
        <canvas ref={waveform} width="1040" height="112" aria-label="Audio waveform" />
        <canvas ref={spectrogram} width="1040" height="128" aria-label="Audio spectrogram" />
        <div className="annotation-layer" aria-label="annotation overlays">
          <div className="annotation original" style={originalStyle}><span>Original annotation</span></div>
          <div className="annotation proposed" style={proposedStyle}><span>{activeAfter ? 'Proposed correction' : 'Initial proposal'}</span></div>
          <div className="annotation reference" style={referenceStyle}><span>Known fixture reference</span></div>
          <div className="playback-cursor" style={cursorStyle} />
        </div>
        <div className="timeline"><span>0.000 s</span><span>1.000 s</span><span>2.000 s</span><span>3.000 s</span><span>4.000 s</span></div>
      </div>

      <div className="annotation-readout">
        <span className="key original-key">Original <strong>{formatTime(fixture.original_annotation[0])} → {formatTime(fixture.original_annotation[1])}</strong></span>
        <span className="key proposed-key">{activeAfter ? 'Correction' : 'Proposal'} <strong>{formatTime(proposed[0])} → {formatTime(proposed[1])}</strong></span>
        <span className="key reference-key">Known reference <strong>{formatTime(fixture.known_reference[0])} → {formatTime(fixture.known_reference[1])}</strong></span>
      </div>

      <audio ref={audio} src={fixture.audio_url} controls preload="metadata" onTimeUpdate={onTimeUpdate} aria-label="Generated fixture audio" />
      <p className="caption"><strong>Muted-view caption:</strong> {fixture.caption} The original interval intentionally extends beyond it; this is an explicit boundary fixture, not an energy-based semantic claim.</p>
    </section>
  )
}
