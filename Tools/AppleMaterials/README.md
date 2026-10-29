# Apple material observations

## License surface separation

`assess_separation.py --scores <scores> --materials <earlier-labels>
--working <working-boundary> --output <new-directory>` measures the owner-directed
question: does a dominant interior appearance pattern differ from surroundings?
It selects each region's most frequent winning channel from the existing outputs,
retains the native score difference, measures all pixels and all four-connected
adjacencies across the unchanged working mask, and publishes a separate report.
It verifies common source lineage and input hashes. It does not train, relabel
materials or change the boundary. Channel names are identifiers, not required
physical-material conclusions. Selection and measurement on one sample are
descriptive, not held-out presentation-detection accuracy.

Retained `surface-separation-v1` result: the interior channel beats the exterior
channel on 93.79% of working-inside pixels versus 7.86% outside. The same interior
channel wins against all 46 on 78.95% inside versus 7.79% outside. Strong regional
separation coexists with spillover: target-winner mask IoU is 65.64%, and the
contrast increases inward on 61.01% of immediate boundary adjacency pairs.
All 35,500,800 pixels included. Results checked by readback and metric recomputation.
No reproduction comparison was executed in this assessment.

The earlier six-class scene proposal remains in `task-classes.json` and
`task_contract.py` for historical compatibility. It is not the active surface
separation task and is no longer displayed as the workspace's purpose. No
working score layers or reports were removed.

Local evaluation of Apple's pretrained DMS46 model on the complete, upright
uncropped RGB scene. This is an independent material prediction layer; it does
not replace observed boundaries, edges, measurements, or the existing viewer.

## Source and reuse

- Source: https://github.com/apple/ml-dms-dataset
- Commit: `a379a63e9435e32134a465eb31ecb0aefebed985`
- Model: https://docs-assets.developer.apple.com/ml-research/datasets/dms/dms46_v1.zip
- Model and code license: accompanying Apple `LICENSE.txt`; transitive notices
  retained in `ACKNOWLEDGMENTS.txt`. Dataset labels have separate noncommercial
  terms; this evaluation does not download or train on that dataset.
- Adapted: RGB normalization and class-index mapping from `inference.py`.
- Changes: remove sample's 512-pixel resizing; run one native whole-scene tensor;
  CPU device support; save source-aligned labels, visualization, counts and hashes;
  reject orientation/shape mismatch and changed input; publish only after success.
- Upstream model weights and network are unchanged. TorchScript model returns
  argmax labels only, not class probabilities. Internal feature downsampling is
  part of the network; native input/output size does not establish native detail
  accuracy. Native scale differs from the sample's inference scale.

Model download is about 166 MiB; expanded model about 179 MiB. Runtime is isolated
Python/PyTorch (BSD-style), NumPy (BSD) and Pillow (HPND). Full installed dependency
versions are retained with the local run. The upstream sample targets 2022 CUDA
PyTorch; this host execution uses a newer ARM64 CPU runtime. Its continued
availability is not a claim of active maintenance or validated document accuracy.
Removal seam: delete this host tool and its ignored artifacts; no Swift SDK or
existing cadastral pipeline depends on it.

## Run

Install `requirements-macos-py311.txt` in a dedicated macOS Python 3.11
environment. It pins PyTorch, NumPy, Pillow and their required runtime
dependencies; unrelated download and GIS packages are excluded.

```
python Tools/AppleMaterials/run.py --image /path/to/upright-original.png \
  --upstream /path/to/downloaded-apple-files --output /path/to/new-result --device cpu
```

`labels.png` stores Apple's zero-based 46-class model indices at original image
coordinates. `manifest.json` maps these to upstream taxonomy IDs, material names
and display colors. `materials.png` and `overlay.png` are presentation artifacts.
No labels are reassigned using the card mask. Region comparisons may subsequently
use that mask to summarize model predictions, not to train or direct them.

These tools package local research observations with checked lineage. Material labels
describe model predictions; they do not prove physical card presence or issuer
authenticity. Evaluation results belong alongside the retained output.

## Native score layers

`extract_scores.py --baseline <material-result> --upstream <apple-files>
--output <new-directory>` calls the unchanged encoder and decoder before the
outer model's argmax. It saves `scores.npy` as float32 `[material,y,x]` and
`margin.npy` as float32 `[y,x]`. The manifest maps all 46 bands to taxonomy names.
These are source-pixel raster arrays, not calibrated probabilities or physical
material measurements. No class removal or renormalization is performed.

The retained baseline run extracted 46 × 6880 × 5160 values, verified all values
finite, matched argmax at every source pixel against the earlier result, and
read back all serialized bands with exact numeric equality. Source/model/output
hashes are retained. The scores file is 6,532,147,328 bytes.

`serve_scores.py --dataset <score-directory> --port 8780` opens a separate
loopback viewer with a material selector, top-two margin and exact native pixel
readouts. It verifies artifact hashes before serving. Material previews share
one global min/max display scale; margin has its own scale. Only visual previews
are reduced, and exact native coordinates can be entered for readout. This
local viewer does not modify the existing cadastral workspace.

## Evidence admission and separate reports

`source-provenance.json` pins the retained upstream inference script, taxonomy
and model by SHA256. The model loads from the same verified bytes that were
hashed. Source RGB is decoded from verified bytes; labels and manifests are
copied into private verified snapshots before downstream processing. All native
labels, dimensions, class indices and score finiteness are checked. Outputs use
the shared macOS no-replace publisher and never overwrite retained datasets.

Region reports now require a separate output directory:

```sh
python Tools/AppleMaterials/report.py --result /path/to/material-result \
  --regions /path/to/working-area/source-labels.png --output /path/to/new-report
```

The region image must belong to a hash-linked working-area package for the same
source. The report retains native prediction downloads and reduced display
previews, and leaves the original material-result directory unchanged.
