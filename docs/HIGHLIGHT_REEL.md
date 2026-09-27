# Social highlight reel

Target and export duration: exactly 14.0 seconds.

## On-screen identity

**Multi-Agent AI System for AI Hackathons**

**Solving real-world ML problems with agentic swarms.**

The replay is labeled **Recorded run · accelerated** and
**Illustrative demo · mock execution**. It does not display historical
competition metrics or imply a competition win.

## Deterministic storyboard

| Time | Scene | Recorded evidence and motion |
|---:|---|---|
| 0–2 s | Exact title and subtitle | Moving decoded waveform, signal scan, and actual structured-event/role/revision counts |
| 2–5.2 s | “Coordinated agents. Structured experimentation.” | Recorded handoffs animate across five participating roles; each card identifies its task |
| 5.2–10 s | “Explore. Experiment. Evaluate.” | Analysis cursor, recorded boundary rejection, −0.050 s/+0.300 s deltas, revision, and acceptance |
| 10–12 s | Workflow complete | Recorded completed status plus boundary-check, revision, and review trace |
| 12–14 s | Project title | “Explore the workflow on GitHub”; no repository URL is burned into the video |

## Routes and controls

- Landscape capture: `/highlight/landscape?autoplay=1`
- Vertical capture: `/highlight/vertical?autoplay=1`
- Deterministic frame: replace the query with `?t=SECONDS`
- Interactive review: open either route without capture parameters

Interactive review exposes pause, play, replay, and timeline controls. Capture
and fixed-frame routes hide them.

## Export

```bash
cd frontend
npm run build
npm run capture:highlight
```

The task writes separately composed 1920×1080 and 1080×1920 H.264/YUV420p MP4s
plus title, orchestration, verification, revision, outcome, and end-card PNGs
for both layouts. Versions 1 and 2 remain preserved; this version is in
`artifacts/social_highlight_v3`.
