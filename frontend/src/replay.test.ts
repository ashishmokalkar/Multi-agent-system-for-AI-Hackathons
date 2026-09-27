import { describe, expect, it } from 'vitest'
import { advanceCursor, orderedEvents, replayDurationMs, visibleReplayEvents } from './replay'
import type { ControlEvent } from './types'

const event = (sequence: number): ControlEvent => ({
  sequence,
  created_at: `2026-01-01T00:00:0${sequence}Z`,
  event_type: 'agent_started',
  agent: 'coordinator',
  summary: String(sequence),
  payload: {},
})

describe('recorded replay', () => {
  it('preserves event sequence and supports seek', () => {
    const events = orderedEvents([event(3), event(1), event(2)])
    expect(events.map((item) => item.sequence)).toEqual([1, 2, 3])
    expect(visibleReplayEvents(events, 1).map((item) => item.sequence)).toEqual([1, 2])
  })

  it('supports pause externally and deterministic speed', () => {
    expect(advanceCursor(0, 1200, 0.5, 5)).toBe(0.5)
    expect(advanceCursor(0, 1200, 2, 5)).toBe(2)
    expect(replayDurationMs(6, 2)).toBe(3000)
  })

  it('clamps seeking at the final event', () => {
    expect(advanceCursor(3, 9000, 2, 5)).toBe(4)
  })
})
