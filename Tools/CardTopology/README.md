# Native edge topology audit

This is an exact planar graph of the retained EdgeDrawing linework. It is a host
experiment; a closed face is a geometric enclosure, not an inferred material or
credential region. Gaps stay open. There is no threshold for gap closure.

## Run

Use the existing `geotiff-env` (NumPy 2.0.2, SciPy 1.13.1, Shapely 2.0.7).
No dependency was added and no source image is decoded or modified by this audit.

```
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardTopology/audit.py Artifacts/gis-baseline-20260911/edge-candidates-v1 Artifacts/gis-baseline-20260911/topology-v2
Artifacts/gis-baseline-20260911/geotiff-env/bin/python -m unittest discover -s Tools/CardTopology -p 'test_*.py' -v
```

Outputs are immutable; use a new output directory for every execution.

## Graph definition

Only consecutive points in retained chains supply line segments. Spatially
neighboring pixels from different chains are not connected. Endpoints separated
by one pixel remain separated, including endpoints of the same chain.

Shapely/GEOS `node` adds exact geometric intersections and removes duplicate
segments in the derived graph. It does not snap coordinates or fill gaps. A
crossing of unit diagonals is therefore a junction at a half-integer source index;
this is an explicit planar interpretation of intersecting linework, not evidence
of a physical junction. `sharedVertexComponentCount` separately measures the
original graph connected only at exact observed coordinates.

Every source segment retains a provenance relationship after geometric noding
or duplicate dissolution. `path_source_segments.npy` rows are `[pathId,
originalPointStartIndex]`; that index identifies the consecutive source pair
`points[index:index+2]`. The original offsets identify its original chain. A
segment split at a crossing has relationships to both output paths. Exact
quarter/three-quarter segment probes enumerate these relationships; they are
not a reduced analysis raster or a sampled selection of source segments. For
native unit segments these cover both possible diagonal halves. All input
segments are checked for a retained relationship.

Singleton chains do not define loops. They remain isolated graph nodes unless
they intersect linework exactly. Shapely `split` makes an exact contact an explicit
path endpoint. Zero-length repeated steps do not become artificial graph edges.

The endpoint graph retains paths with every vertex supplied by GEOS; no line
simplification, smoothing, resizing, snapping, gap bridging or minimum-length
filter is used. SciPy sparse connected-components supplies connectivity; degree
counts include both ends of a closed path. `cycleRank = E - V + C` counts independent
graph cycles. Shapely `polygonize_full` separately reports faces, cuts, dangles and
invalid rings. These are different measurements and are not interchanged.

## Package/API

`dataset.load_dataset(path, source_hashes=None, edge_manifest_hash=None)` returns
`manifest, arrays, regions, immutable_file_snapshots` after integrity checks.
NumPy arrays are read-only. Publication uses the existing atomic no-overwrite
CardBoundary helper and validates the package before publishing.

- `path_points.npy`: float64 source pixel indices, including exact intersections.
- `path_offsets.npy`: int64 offsets; every path has at least two points.
- `path_nodes.npy`: int64 pair of graph node IDs per path.
- `path_components.npy`: int32 component ID per path.
- `nodes.npy`: float64 graph-node coordinates.
- `degrees.npy`, `node_components.npy`: int32 node attributes.
- `path_source_segments.npy`: int64 path/source-segment provenance pairs.
- `regions.geojson`: closed polygonal faces, with integer region/component IDs.
- `cuts.wkb`, `dangles.wkb`, `invalid.wkb`: complete polygonization leftovers.
- `topology.json`: counts; `manifest.json`: hashes, parameters and execution versions.

Coordinates share the retained source-index system. Add (0.5, 0.5) for the viewer's
pixel-edge-origin coordinates. JSON and arrays never quantize crossing positions.
This local-coordinate GeoJSON is consumed by ID Cadastral; it is not WGS84 data.

## Sources, licenses, maintenance, removal seam

No upstream source code was copied or modified. The local adapter delegates exact
noding/polygonization to GEOS through Shapely and connectivity to SciPy. Inspected
installed Python wrappers and public reference documentation:

- Shapely 2.0.7 constructive wrapper:
  https://github.com/shapely/shapely/blob/2.0.7/shapely/constructive.py
- Shapely exact split wrapper:
  https://github.com/shapely/shapely/blob/2.0.7/shapely/ops.py
- https://shapely.readthedocs.io/en/2.0.7/reference/shapely.node.html
- https://shapely.readthedocs.io/en/2.0.7/reference/shapely.polygonize_full.html
- https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.sparse.csgraph.connected_components.html
- SciPy pinned implementation:
  https://github.com/scipy/scipy/blob/v1.13.1/scipy/sparse/csgraph/_traversal.pyx

Shapely uses BSD-3-Clause; its bundled GEOS has LGPL-2.1 licensing. SciPy uses
BSD-3-Clause with additional bundled-library notices. Exact installed distribution
notices are retained in `licenses/`. These are established maintained upstream
projects, frozen here to the already installed experiment versions. Existing
NumPy is their numerical dependency; Shapely wraps the already bundled GEOS.
Incremental binary cost is zero because this lane reuses those packages. No new
model or remote service is introduced. Removing Tools/CardTopology and the optional
viewer input removes the adapter without changing capture/Swift behavior.

## First baseline outcome

Both native runs retain 2,222,518 points / 207,654 chains. There are 2,090 singleton
chains, zero genuinely closed original chains, 206,751 connected components,
410,225 degree-one endpoints, 903 junctions and zero graph cycles. Polygonization
produces zero faces: all 206,467 noded paths are dangles. The detector has useful
visible transitions but this retained output does not enclose regions without
adding a separate closure/segmentation interpretation.

`topology-v1-executed-source/` preserves the first run's adapter source. The second
run adds singleton-contact/empty-input handling and stronger admission validation;
its native geometry and classifications must be compared with the first run.
