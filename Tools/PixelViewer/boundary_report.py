"""Render boundary diagnostics as a local report; source geometry is never edited."""
import json,html,hashlib
from pathlib import Path
import numpy as np
BASE=Path(__file__).resolve().parents[2]/'Artifacts/gis-baseline-20260911'
OUT=BASE/'boundary-review'
m=json.loads((OUT/'measurements.json').read_text())
rows=[];sensitivity=[];texture=[]
for name,e in m['edges'].items():
 c=e['scales']['0.08']['stations'][40]['candidates'][0]
 rows.append(f"| {name} | {c['offsetNominalMillimeters']:.2f} | {c['sourceDisplacementPixels']:.1f} | {c['offsetRectifiedPixels']:.1f} |")
 values=np.array([[s['candidates'][0]['offsetNominalMillimeters'] if s['candidates'] else np.nan for s in e['scales'][str(sigma)]['stations']] for sigma in [.04,.08,.16]])
 sensitivity.append(f"- {name}: {int(np.sum(np.ptp(values,axis=0)<=.2))}/81 stations keep the strongest candidate within 0.20 nominal mm across the three smoothing scales.")
 vals={side:[v['adjacentDifferenceRMS'] for v in m['pairedSurfaceSamples'] if v['edge']==name and v['side']==side and v['widthNominalMillimeters']==.5] for side in ['inside','outside']}
 texture.append(f"| {name} | {np.mean(vals['inside']):.2f} | {np.mean(vals['outside']):.2f} |")
report='''# ID Cadastral — boundary assessment

## Disposition

**The saved quadrilateral is rejected as a precise physical/cadastral boundary
for this capture.** It remains the historical geometry used by the current
rectification. The object-layer implementation passed its checks; its proposed
geometry did not pass visual boundary assessment. No replacement boundary was
created and no image, mask, corner or GeoTIFF was changed by this assessment.

## What the evidence establishes

The original has visible card-face strips outside the saved top, left and right
lines. On the bottom, the saved line traverses a dark band below the printed
face. The band's appearance alone does not resolve exposed edge versus shadow.
All four corners are rounded; their physical outline differs from the sharp
quadrilateral. Corner background inclusion and straight-side cropping are
separate effects.

The visual review covers four corners and 25/50/75% samples on every edge.
Automated transects cover 81 positions over each edge's central 80%; this is
sampling, not an assertion that every perimeter pixel has been classified.

## Automated midpoint transition candidates

Negative offsets are outside the saved boundary; positive offsets are inside.
Source displacement is signed length along the projectively mapped transect,
not perpendicular source-edge residual. Distances in mm are nominal card-plane
coordinates; extrapolation onto the paper is not physical paper metrology.

| Edge | Strongest candidate offset (nominal mm) | Source displacement (px) | Rectified offset (px) |
|---|---:|---:|---:|
'''+ '\n'.join(rows)+'''

Top/right candidates are consistent with the visibly excluded face strips.
The left midpoint's strongest peak is printed content inside the card, not the
physical boundary. At bottom, competing midpoint candidates occur near -0.40 mm
(-20.2 source px, -20 output px) at the dark-band/paper transition and +0.70 mm
(+35.3 source px, +35 output px) near the face termination. A strongest-gradient
rule would choose the wrong kind of boundary at some positions.

All filtered local maxima, their scores, source XY and rectified XY are retained
in measurements.json; raw sampled RGB and gradient arrays are in profiles.npz.
No candidate was promoted into corrected geometry.

## Sensitivity to measurement scale

'''+ '\n'.join(sensitivity)+'''

These are parameter-sensitivity observations, not accuracy or repeatability
across cameras. Changes can reflect switching between print, edge and shadow.

## Adjacent-surface comparison

The table uses only 0.5 mm diagnostic patches sampled at equal 0.02 nominal mm
spacing, at 20/50/80% of each edge, centered 2 nominal mm inside/outside. Entries
are mean RMS adjacent-sample RGB differences in decoded channel-value units.
Printing, focus, illumination and material all contribute. No patch is treated
as a pure-material reference; no material classifier has been trained.

| Edge | Inside RMS | Outside RMS |
|---|---:|---:|
'''+ '\n'.join(texture)+'''

The source crops visibly distinguish structured card printing from irregular
paper texture. This simple scalar varies by location and has overlapping
inside/outside values; it cannot by itself label paper versus card. Paired
samples at 0.25 and 1.0 mm, actual grid spacing, RGB means and standard deviations
are retained too. The experiment does not infer ink chemistry or authenticity.

## Rectification consequences

The same saved quadrilateral defines the normalized PNG and GeoTIFF. Visible
face pixels outside its top/side edges are excluded from that output. At the
bottom, some of the dark band is admitted. Rectification cannot recover excluded
pixels; the original still preserves them. GeoTIFF pixel equality proves faithful
packaging of the existing rectification, not accuracy of its input boundary.

## Completeness and remaining uncertainty

Completed: object partition/mask checks, visual coverage of edges and corners,
multiscale automated transects, paired surface measurements, coordinate tracing,
alternative-peak retention, independent review and input-integrity checks.

Unresolved: exact physical perimeter, rounded-corner contour, separation of the
bottom shadow/edge, calibrated uncertainty and repeatability on other captures.
This is enough to reject the present boundary for precise downstream use. Those
questions cannot be closed by declaring the current quadrilateral accurate.
Boundary refinement must be evaluated automatically as a separate implementation
step. No manual correction is proposed or applied here.
'''
for rel,expected in m['sourceHashes'].items():
 if hashlib.sha256((BASE/rel).read_bytes()).hexdigest()!=expected:raise ValueError('Source hash changed: '+rel)
report+='\nIntegrity check: all '+str(len(m['sourceHashes']))+' recorded source/artifact hashes remain unchanged.\n'
(OUT/'REPORT.md').write_text(report)
images=[]
for edge in ['top','right','bottom','left']:
 images.append(f'<h2>{edge.title()} edge</h2><img src="{edge}-profiles.png"><img src="visual-agent/{edge}-samples.png">')
for corner in ['tl','tr','br','bl']:images.append(f'<h2>{corner.upper()} corner</h2><img src="visual-agent/{corner}.png">')
page='<!doctype html><meta charset="utf-8"><title>ID Cadastral — boundary assessment</title><style>body{background:#10191c;color:#e7eeee;font:16px system-ui;margin:32px auto;max-width:1200px;padding:20px}pre{white-space:pre-wrap;line-height:1.6}img{max-width:100%;margin:12px 0}a{color:#76dfca}</style><h1>ID Cadastral — boundary assessment</h1><p><a href="measurements.json">Measurements JSON</a> · <a href="profiles.npz">Raw profiles</a> · <a href="visual-agent/observations.md">Visual review</a></p><pre>'+html.escape(report)+'</pre>'+''.join(images)
(OUT/'report.html').write_text(page)
print(OUT/'report.html')
