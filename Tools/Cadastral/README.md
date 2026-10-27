# ID Cadastral retained host baseline

For fresh SDK captures and the integrated analysis inventory, use
[the assembled workspace](../../docs/capture-port/assembled-workspace.md).
`prepare.py` runs existing analysis tools; `launch.py --run` opens all available
packages from that run. The layout commands below remain for historical baselines.

This entrypoint keeps the spatial workspace, Apple score inspection and the
two-panel surface-separation result together. It opens retained outputs; it does
not regenerate images, train a model, change a boundary, overwrite a package or
silently discard a missing capability.

Run from the repository root. All commands take an explicit baseline directory.
The tracked `baseline-layout.json` lists package versions and isolated Python
environments. For another layout, copy that JSON to a local file and pass
`--config PATH`. Paths are relative to `--baseline`; no capture coordinates,
chain IDs, source hashes or automatically selected "latest" directories enter
the launcher. Dataset lineage and artifact admission remain owned by each tool.

## Open the retained work

Use separate terminals for the two servers. Existing listeners are not killed
or replaced automatically. Select a different `--port` for a parallel audit.

```sh
python3 Tools/Cadastral/launch.py --baseline Artifacts/gis-baseline-20260911 --component workspace
```

Open `http://127.0.0.1:8767`. The launcher passes **all** retained layer packages.

```sh
python3 Tools/Cadastral/launch.py --baseline Artifacts/gis-baseline-20260911 --component scores
```

Open `http://127.0.0.1:8780`. The score server validates its retained artifacts
before announcing readiness; the native scores are several gigabytes.

```sh
python3 Tools/Cadastral/launch.py --baseline Artifacts/gis-baseline-20260911 --component separation
```

This opens the retained `index.html` as a local file after strict JSON admission,
checking source and manifest lineage against the configured score/working packages,
and verifying the hashes of both preview panels and native score-difference/mask
outputs. New reports also hash HTML. Earlier retained reports without an HTML hash
remain readable; their four evidence rasters must still verify. This is an
admission check, not an immutable browser snapshot: do not mutate files while
viewing a report. The launcher does not
serve an arbitrary directory. Add `--print-only` to any command to inspect its
exact invocation or report URL without launching anything.

## Retained feature inventory and ownership

| Capability | Retained meaning |
| --- | --- |
| Original and rectified images | Full-scene original linked to saved and boundary-derived registration; source files unchanged. |
| Pixel inspector | Native coordinates, linked card/GIS coordinates, RGB and hex, pin, zoom and pan. |
| Orange observed contour | Native GrabCut perimeter, including local irregularities; distinct from working correction. |
| Working perimeter and interior | Separate local bottom-shadow interpretation, edge exclusion and interior eligibility mask. |
| Pink/blue transitions | Every retained EdgeDrawing chain; inside/outside colors use the baseline mask, not Apple material classification. |
| Topology | Endpoints, junctions, connected features, retained open paths and faces; no invented connections. |
| Measurements | Every source/rectified scanline retained. UI X/Y queries use the retained rectified measurement dataset. |
| Diagonals and 3–4–5 | Both diagonals, extended sides, virtual corners and registration consistency diagnostics. |
| Corner radii | Separate models conditional on the retained perimeter/registration; not the working correction. |
| Candidate/assembly reports | Competing transitions, path assembly, color evidence and unresolved cases remain inspectable. |
| GeoTIFF and JSON | Native raster packaging, transforms, masks, provenance and download links. |
| Apple material viewer | All 46 native score layers retained; all-channel material menu and separate top-two margin. Names identify model channels. |
| Surface separation, left panel | Dominant interior channel wins against all 46; green/purple overlay retains spillover. |
| Surface separation, right panel | Continuous interior-minus-exterior channel score difference, not a binary replacement for the left panel. |
| Surface separation statistics | All native pixels and immediate four-connected boundary adjacencies; existing working mask defines reporting regions. |

The current question is dominant appearance inside the license versus surrounding
scene. Predicted material names are not necessary physical-material conclusions.
Regional separation in this one capture is descriptive evidence; no reproduction
comparison is implied. The retired six presentation classes are not a trained
classifier and are not dependencies of this baseline.

## Reproduce the software checks

```sh
python3 Tools/Cadastral/check.py --baseline Artifacts/gis-baseline-20260911 --print-only
python3 Tools/Cadastral/check.py --baseline Artifacts/gis-baseline-20260911
```

The command allowlist runs separate processes per suite: geometry/raster/viewer
tests use `geotiff-env`, EdgeDrawing tests use `edge-env`, and Apple tests use
`apple-dms-env`. It never imports all tools into one incompatible environment.
Use `--group geometry`, `--group edges` or `--group apple` to run a bounded lane.
Failure stops that invocation with a nonzero exit status. No real baseline is
recomputed by this check runner.

For real-browser regression checks, open the complete workspace with Playwright
CLI, then run:

```sh
playwright-cli open http://127.0.0.1:8767
playwright-cli run-code --filename Tools/PixelViewer/check-workspace.js
```

That exercises all five tabs, control retention, actual pink/blue, diagonal,
side-line and radius rendering, and X/Y measurement queries. Inspect the rendered
workspace and **both** surface-separation panels as separate visual evidence.
Passing software checks does not turn the baseline into a general physical-edge
or document-authentication certification.

Source reuse: these standard-library entrypoints orchestrate existing repository
tools; they add no imaging algorithm, ML implementation or dependency. The JSON
layout and launcher are the removal seam. Local sensitive artifacts and licensed
model/runtime files remain outside source control.

## Temporal physical-handling evidence

Open an explicitly generated temporal package independently of the spatial baseline:

```sh
python3 Tools/Cadastral/launch.py --component temporal --report /absolute/path/to/temporal-report
python3 Tools/Cadastral/check.py --group temporal
```

The loopback viewer opens at `http://127.0.0.1:8781`. It shows every retained
native-dimension frame, segment-local timestamps, coverage gaps, image measurements
and aligned phone motion. Playback stops at recording boundaries and never invents
intermediate images or bridges missing timestamps. Browser image decode may make
playback slower than acquisition; every retained frame remains inspectable.

Automated measurements and human handling observations appear separately. A
review draft downloads locally; importing it through the temporal analyzer creates
a new report. No server upload or cloud service is involved, and no authenticity
verdict is generated. The package pins its report hash and all frame-artifact
hashes. Serving opens no-follow paths and verifies the exact bytes sent for each
image; mutation, traversal and symlink substitutions fail closed.

The temporal viewer uses Python's standard-library HTTP server with a fixed route
allowlist, following the existing local material viewer's ownership boundary. It
adds no imaging algorithm or dependency. `Tools/TemporalEvidence/serve.py` and its
three presentation assets are the removal seam.

Temporal checks reuse the configured geometry environment when `--baseline` is supplied.
The standalone `--group temporal` lane uses the invoking Python environment.
