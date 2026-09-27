import { describe, expect, it } from 'vitest'
import { HIGHLIGHT_BEATS, HIGHLIGHT_DURATION_SECONDS, beatAt, handoffAgent, participatingAgents, words } from './highlight'
import type { ControlEvent } from './types'

const event = (sequence: number, agent: string): ControlEvent => ({
  sequence,
  created_at: `2026-01-01T00:00:0${sequence}Z`,
  event_type: 'agent_started',
  agent,
  summary: agent,
  payload: {},
})

describe('14-second technical highlight timeline', () => {
  it('has five contiguous beats, a two-second title, and short captions', () => {
    expect(HIGHLIGHT_DURATION_SECONDS).toBe(14)
    expect(HIGHLIGHT_BEATS).toHaveLength(5)
    expect(HIGHLIGHT_BEATS[0]).toMatchObject({ start: 0, end: 2 })
    expect(HIGHLIGHT_BEATS.at(-1)?.end).toBe(HIGHLIGHT_DURATION_SECONDS)
    HIGHLIGHT_BEATS.forEach((beat, index) => {
      expect(words(beat.caption)).toBeLessThan(8)
      if (index) expect(beat.start).toBe(HIGHLIGHT_BEATS[index - 1].end)
    })
  })

  it('selects deterministic scenes and only recorded participants', () => {
    expect(beatAt(0).id).toBe('title')
    expect(beatAt(2).id).toBe('orchestration')
    expect(beatAt(5.2).id).toBe('verification')
    expect(beatAt(10).id).toBe('outcome')
    expect(beatAt(12).id).toBe('end')
    expect(beatAt(13.99).id).toBe('end')
    const events = [event(1, 'coordinator'), event(2, 'data_investigator'), event(3, 'coordinator')]
    expect(participatingAgents(events)).toEqual(['coordinator', 'data_investigator'])
    expect(handoffAgent(events, 0)).toBe('coordinator')
    expect(handoffAgent(events, .5)).toBe('data_investigator')
  })
})
