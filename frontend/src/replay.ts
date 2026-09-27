import type { ControlEvent } from './types'

export const REPLAY_STEP_MS = 1200

export function orderedEvents(events: ControlEvent[]): ControlEvent[] {
  return [...events].sort((a, b) => a.sequence - b.sequence)
}

export function visibleReplayEvents(events: ControlEvent[], cursor: number): ControlEvent[] {
  const ordered = orderedEvents(events)
  if (cursor < 0) return []
  return ordered.slice(0, Math.min(ordered.length, Math.floor(cursor) + 1))
}

export function advanceCursor(cursor: number, elapsedMs: number, speed: number, eventCount: number): number {
  if (eventCount === 0 || elapsedMs <= 0) return cursor
  const next = cursor + (elapsedMs * speed) / REPLAY_STEP_MS
  return Math.min(eventCount - 1, Math.max(-1, next))
}

export function replayDurationMs(eventCount: number, speed = 1): number {
  if (eventCount <= 1) return 0
  return ((eventCount - 1) * REPLAY_STEP_MS) / speed
}
