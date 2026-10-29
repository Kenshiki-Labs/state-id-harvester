# Temporal physical-handling evidence

This local ID Cadastral tool turns a retained phone export into a reproducible,
inspectable package of native frames, camera observations, exact-time geometry,
phone motion, coverage gaps and separately attributed visual-review findings.
It does not automatically classify physical handling, material, or authenticity.
Unreviewed inputs stay `unreviewed`; phone motion and pixel differences cannot
promote them to `observed`.

## Run

Use the existing Cadastral geometry environment (NumPy 2.0.2, Pillow 11.3.0)
or install `requirements-macos-py39.txt` in a local Python environment. No network
is used by analysis or viewing. macOS is required for atomic package publication.

```sh
python3 Tools/TemporalEvidence/analyze.py --export /path/to/retained --output /path/to/new-package
python3 Tools/Cadastral/launch.py --component temporal --report /path/to/new-package
```

The viewer provides every retained frame, segment selection, frame stepping,
time-based playback, phone gyro readouts, raw observations, recording gaps and
review findings. The PNGs preserve delivered dimensions. The viewer may scale
images for display; analysis does not resize, crop, skip frames or omit pixels.
Playback stops at segment boundaries rather than inventing continuity.

A reviewer can download a draft annotation and import it into a **new** package:

```sh
python3 Tools/TemporalEvidence/analyze.py --export /path/to/retained --output /path/to/reviewed-package --review /path/to/review.json
python3 -m unittest discover -s Tools/TemporalEvidence -p 'test_*.py'
```

The analysis command verifies the export again. It never modifies source records
or overwrites an existing package. Downloaded annotations are not saved to the
phone or silently admitted as findings. `reviewerType` distinguishes a person
from an assistant's visual inspection. All review statuses require evidence
ranges and notes. A positive motion observation requires multiple source frames
within one uninterrupted retained interval. One still or a hand-contact note
alone cannot establish handling.

## Data and evidence contracts

- `index.json` in the input pins each manifest and original payload. The reader
  verifies all records, journal ordinals and previous hashes, run/workflow
  identity, raw-plane layout, seal counts, motion/frame chronology and retained
  still bindings. Broken custody fails; a valid partial/unsealed prefix remains
  usable with explicit partial/interrupted status. Export hashes are integrity
  checks against the supplied index, not signatures authenticating a device.
- Legacy exports identify `selected_still_segments`. The updated phone export
  discovers all retained segments in the selected workflow, including segments
  without successful stills. Segment completeness never proves journey-wide
  continuity; this tool leaves journey continuity unestablished.
- Every native 420f luma sample contributes to per-frame descriptive statistics.
  Adjacent unregistered luma change can reflect exposure, focus, shadows,
  camera movement or object movement. It is not optical flow or object attribution.
  Differences are absent across known frame/clock gaps. The 50 ms reporting
  bound is an explicit engineering diagnostic, not an evaluated liveness limit.
- Motion joins use the measured host/system-uptime bracket. A nearest sample
  must be within 25 ms including clock uncertainty and within available sensor
  coverage. No extrapolation, interpolation across gaps, zero-offset assumption,
  or cross-session attitude comparison. Ambiguous/reset clocks remain unavailable.
- Geometry joins require equal rational capture timestamps, epoch and coordinate
  space. Repeated/reset session timestamps suppress ambiguous joins. Unmatched
  raw geometry events remain in the report; no nearest-frame grafting.
- BT.601 full-range NV12 conversion produces native-size display PNGs only when
  the recorded matrix supports it. Other matrix/missing metadata displays native
  luma explicitly. Original planes remain authoritative. The display is not a
  calibrated color/material measurement.
- `report.json` binds source inventory, method/source-code hashes, implementation
  versions, frame hashes and derivative artifact hashes. `manifest.json` pins
  report bytes. `review.json`, when supplied, is preserved and hashed separately.
  Review endpoints include exact source IDs/hashes and the export index hash.
  The reviewed interval is not hardcoded in analysis and is never auto-discovered
  by replaying this scan's labels.
- Publication streams native derivatives to private staging, syncs them, and
  reuses the repository's exclusive atomic rename adapter. Interrupted staging
  is not a completed report; competing publishers cannot replace one another.

Keep exports and reports in ignored local `Artifacts/`, never in source control.
The package duplicates display derivatives for reproducibility; it adds no new
phone retention policy and does not delete existing recordings.

## Implementation sources and removal seam

Uses Python standard-library JSON/hashlib/fractions/plistlib, existing NumPy and
Pillow dependencies, and `Tools/CardBoundary/publication.py`. NumPy/Pillow pins
match the existing spatial tool environment; no new dependency or model. License
and dependency inventory remains in the spatial environment's pinned requirements.
Only a custom adapter for the repository-specific encrypted-export graph, timing
and review schemas is new.

Reviewed on 2026-09-14: Apple
[CoreMotion timestamp](https://developer.apple.com/documentation/coremotion/cmlogitem/timestamp),
[session clock](https://developer.apple.com/documentation/avfoundation/avcapturesession/synchronizationclock),
[Vision optical flow](https://developer.apple.com/documentation/vision/vngenerateopticalflowrequest),
and [OpenCV optical flow documentation/sample](https://docs.opencv.org/4.0.0/dc/d6b/group__video__track.html).
The current integration deliberately introduces no optical-flow algorithm: these
APIs do not supply a validated document/background/phone handling decision or the
app-specific custody graph. No external source was copied. Standard full-range
BT.601 equations are used only for display. Removing `Tools/TemporalEvidence`,
the optional Cadastral launcher entry, and the workflow-export additions removes
this integration without changing native capture or usability/authenticity policy.

## Retained hand landmark overlays

Exports containing `handLandmarkFrame` and `handLandmarkSummary` records are read
alongside the original journal. Each derivative must match its source record ID,
SHA-256, complete native metadata, workflow/recording, configuration and provider
millisecond timestamp. Version 1 admits only `identity_full_scene` input with
orientation 1: no crop, resizing, guessed orientation or nearest-frame grafting.
The raw 21 normalized and world landmarks and handedness categories remain in
`report.handLandmarks`. Array positions identify hands within a frame only.

The viewer's **Hand landmark overlay** control selects a separate native-size,
hashed PNG derivative. The original presentation PNG remains unchanged. The
report records the affine transform from upright normalized coordinates to native
pixel-edge coordinates. Out-of-image provider coordinates remain in the report;
drawing is clipped by the presentation canvas. Stroke size affects display only.
The coordinate helper is checked against Pillow's EXIF transpose for all eight
orientations; unsupported input transforms are rejected by this schema version.

`noHands` denotes a successful empty provider result. Unanalyzed frames remain
`unavailable`, and inference failures remain `error`. Historical retries remain in
the report; overlay selection uses one published summary per workflow/configuration,
preferring a current source inventory and then the newest publication. It never
splices frames from different retries. Multiple selected configurations, or
unsummarized duplicate derivatives, remain `ambiguous` with no chosen overlay.
Summary counts and current source inventories are checked. A valid summary from
an older journal inventory is explicitly `stale`; it does not certify current
coverage. Missing source frames/results, false current coverage and inconsistent
links fail package construction. Recording gaps and derivative gaps stay separate.
Neither landmarks, handedness nor any success status promotes the separately
attributed physical-handling review to `observed`.

This integration adds no Python inference dependency. It renders observations
retained by the optional native hand adapter. Coordinate/result semantics were
checked against [Google's Hand Landmarker documentation](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python)
and [Pillow ImageOps](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose).
The skeletal connections encode the documented 21-joint hand topology; no upstream
implementation was copied. Package method hashes pin `hands.py` and
`hand_coordinates.py` with the existing temporal implementation. Removing those
modules and their explicit analyzer/viewer hooks removes this optional derivative
layer without changing native journal pixels or manual review records.
