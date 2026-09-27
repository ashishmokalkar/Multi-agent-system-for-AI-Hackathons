# Attribution and data notice

This repository contains new orchestration, validation, persistence, and test
code. It does not contain the Vaani audio datasets, model weights, private
experiment outputs, or copied model implementations.

The adapters were designed against the following existing project interfaces:

- `e1_beats.data.assert_split_integrity` for source-group, duplicate-hash,
  and evaluation-leakage checks.
- `e1_beats.official_scorer.official_metrics` for the project-recorded
  competition metric implementation.
- `artifacts/vaani_synthetic_generator_v1/src/generator.py` and
  `audio_ops.py` for provenance gates and sample-accurate audio/event
  transformations.
- The validated BEATs A1 training and evaluation entry points under
  `artifacts/beats_a1_approved_synthetic_40h_v1`.
- Saved-prediction compatibility and comparison logic represented by
  `artifacts/beats_a1_short_long_ensemble_v1/run_ensemble.py`.

Those files remain in the separately configured source repository and retain
their original ownership and licensing status. Their absence does not prevent
the bundled mock demonstration from running.

The OpenAI Agents SDK is an optional dependency and retains its own license.
Competition datasets, external sound libraries, and pretrained weights each
retain their own terms. Nothing in this repository grants redistribution
rights for them.

The control-room frontend uses React, React DOM, Vite, TypeScript, Vitest, and
Playwright as declared npm dependencies. They retain their respective licenses.
The demo WAV is generated deterministically from mathematical waveforms and
contains no copied speech, dataset audio, or pretrained-model output.
