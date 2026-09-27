export type EventPayload = Record<string, unknown>

export interface ControlEvent {
  sequence: number
  created_at: string
  event_type: string
  agent: string | null
  summary: string
  payload: EventPayload
}

export type AgentStatus = 'idle' | 'queued' | 'running' | 'awaiting review' | 'completed' | 'failed'

export interface FixtureInfo {
  duration_seconds: number
  sample_rate: number
  caption: string
  known_reference: [number, number]
  original_annotation: [number, number]
  audio_url: string
}

export interface ScoreSet {
  event_f1?: number
  segment_dice?: number
  combined?: number
  scorer?: string
}

export interface MetricPayload {
  baseline: ScoreSet
  candidate: ScoreSet
  label: string
}
