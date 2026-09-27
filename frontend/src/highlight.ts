import type { ControlEvent } from './types'

export const HIGHLIGHT_DURATION_SECONDS = 14

export const HIGHLIGHT_BEATS = [
  { id: 'title', start: 0, end: 2, caption: 'Agentic systems for ML challenges' },
  { id: 'orchestration', start: 2, end: 5.2, caption: 'Coordinated agents. Structured experimentation.' },
  { id: 'verification', start: 5.2, end: 10, caption: 'Explore. Experiment. Evaluate.' },
  { id: 'outcome', start: 10, end: 12, caption: 'Verified correction. Completed workflow.' },
  { id: 'end', start: 12, end: 14, caption: 'Explore the workflow on GitHub' },
] as const

export type HighlightBeat = typeof HIGHLIGHT_BEATS[number]

export function beatAt(seconds: number): HighlightBeat {
  const clamped = Math.max(0, Math.min(HIGHLIGHT_DURATION_SECONDS - 0.0001, seconds))
  return HIGHLIGHT_BEATS.find((beat) => clamped >= beat.start && clamped < beat.end) ?? HIGHLIGHT_BEATS.at(-1)!
}

export function localBeatProgress(seconds: number, beat: HighlightBeat): number {
  return Math.max(0, Math.min(1, (seconds - beat.start) / (beat.end - beat.start)))
}

export function participatingAgents(events: ControlEvent[]): string[] {
  const seen = new Set<string>()
  for (const event of events) {
    if (event.event_type === 'agent_started' && event.agent) seen.add(event.agent)
  }
  return [...seen]
}

export function handoffAgent(events: ControlEvent[], progress: number): string | null {
  const handoffs = events.filter((event) => event.event_type === 'agent_started' && event.agent)
  if (!handoffs.length) return null
  const index = Math.min(handoffs.length - 1, Math.floor(Math.max(0, Math.min(.999, progress)) * handoffs.length))
  return handoffs[index].agent
}

export function words(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length
}
