# Nominal card GeoTIFF

Host-only export of the existing front rectified PNG. This adds spatial metadata
and lossless tile organization, not new measurements or image processing.

```sh
python3 -m venv Artifacts/gis-baseline-20260911/geotiff-env
Artifacts/gis-baseline-20260911/geotiff-env/bin/pip install --only-binary=:all: -r Tools/CardRaster/requirements-macos-py39.txt
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardRaster/export_geotiff.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/geotiff
```

Output directory must not already exist. Inputs are fixed `front-original.heic`,
`front-rectified.png`, and `front-geometry.json` within the given baseline.
Source hashes, RGBA encoding and ID-1 geometry are checked before export. No
resizing, color conversion or resampling occurs. The TIFF preserves the PNG's
four 8-bit channels and adds a standard sRGB ICC profile. Alpha is retained,
not converted into a claim of card-boundary validity. No pixel is assigned nodata.

## Coordinates

- Local engineering coordinates, not Earth coordinates; no EPSG authority.
- Top-left card edge is `(0,0)`; scale is 0.02 mm per pixel.
- GIS coordinates: x right, y up. Bottom-right edge is `(85.60,-53.98)` mm.
- Existing card/viewer coordinates: x right, y down.
- Explicit conversion: `card_x = gis_x`, `card_y = -gis_y`.
- First pixel center: GIS `(0.01,-0.01)`, card `(0.01,0.01)` mm.
- Pixel `[1000,500]`: GIS `(20.01,-10.01)`, card `(20.01,10.01)` mm.

GDAL's GeoTIFF writer normalizes custom local CRS axis directions on readback.
An initial positive-y/down experiment lost its SOUTH axis declaration, so this
export deliberately uses conventional north-up GIS axes with a negative row
scale. The file's internal tags and JSON explain the conversion to the viewer.
GDAL also reads the local unit label as `unknown`; the retained unit factor
`0.001` meters defines millimeters. Readback checks that factor explicitly.
The original geometry matrices use card coordinates, so negate GIS y before
applying cardMillimetersToSource.

Dimensions are assumed nominal ID-1 dimensions, not physical size validation.
Source lens distortion remains uncalibrated. This is an inspection artifact,
not an authenticity result. Browser viewer continues using its existing PNG.

## Output and verification

`front-card.tif`: 512×512 tiles, DEFLATE lossless compression, horizontal
predictor, RGBA uint8, no overview/resampling. This is a tiled GeoTIFF, not a
claimed Cloud Optimized GeoTIFF.

`manifest.json`: input/output hashes and byte counts, complete retained geometry,
GIS/card coordinate interpretation, converter hash, tool versions, limitations
and verification results. Staged output is only published after verification.

All 46,206,880 channel samples (11,551,720 pixels) are compared against the PNG
using Rasterio/GDAL and independently Pillow. The verifier rejects a one-channel
mutation. Internal georeferencing is checked with GDAL auxiliary metadata
disabled. Both readers verify the standard ICC profile. Input hashes are checked
again after the export. Existing output is refused rather than overwritten.
Publication reuses CardBoundary's macOS atomic no-replace publisher, including
its persistent process lock and durability checks. A destination created during
export, or a destination symlink, is rejected without replacing it.

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python -m unittest discover -s Tools/CardRaster -p 'test_*.py'
```

## Dependency provenance and removal

Sources inspected 2026-09-11:
- https://gdal.org/en/stable/drivers/raster/gtiff.html
- https://rasterio.readthedocs.io/en/stable/topics/writing.html
- https://rasterio.readthedocs.io/en/stable/topics/georeferencing.html
- https://github.com/rasterio/rasterio/tree/1.4.3
- https://pillow.readthedocs.io/en/stable/reference/ImageCms.html
- Repository Decision 0039 and host image provenance decisions 0011/0039.

No implementation source copied. Reuses Rasterio 1.4.3 (BSD-3-Clause) with its
bundled GDAL 3.9.3 and native libraries; Pillow 11.3.0 (MIT-CMU) provides PNG and
independent TIFF reading plus LittleCMS sRGB profile generation. NumPy 2.0.2
(BSD-3-Clause) compares arrays. All packages are pinned in
`requirements-macos-py39.txt`, including transitive affine, attrs, certifi, click,
click-plugins, cligj, importlib-metadata, pyparsing and zipp. Installed package
license files retain the wheel/native notices; nothing is copied into the app.
Rasterio wheel is about 18.8 MB, Pillow 4.7 MB; isolated installed environment
about 100 MB. This compatibility pin is for the host's Python 3.9, not a claim
of latest releases. Current GDAL/Rasterio documentation was consulted; only
basic GTiff APIs available in the installed versions are used and verified.

Removal seam: delete this host tool and its isolated artifact environment. No
Swift dependency, app binary cost, phone installation or network runtime added.
Sensitive inputs, TIFF, manifest and environment remain under ignored Artifacts.

## Manifest schema version 2

Type and status fields use stable identifiers. Coordinate origin, pixel-center
offset, zero-based indices and the GIS-to-card affine are structured values.
Affine order is `[a,b,c,d,e,f]`: `x_out=a*x+b*y+c`, `y_out=d*x+e*y+f`.
Scale basis and lens calibration are recorded as `nominal_id1` and
`uncalibrated`. Explanations live in this document rather than a limitations
array. The retained geometry projection uses structured coordinate/encoding
fields; the original source geometry file remains unchanged and hash-linked.
Existing manifest migration records its source hash and transformer hash,
preserving the TIFF's original export provenance.
