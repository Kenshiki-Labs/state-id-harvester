# Independent gallery sources

The gallery track acquires original PNG/JPEG assets linked from official agency HTML.
It complements native PDF object extraction: source pages can describe one design while
their images show another, and HTML images can contain the same baked-in callouts as PDFs.
No gallery asset is automatically a clean specimen, a reviewed cohort, or a physical master.

```sh
uv run --locked state-id-harvester harvest-images --all --output output/gallery
uv run --locked state-id-harvester harvest-images --states WA NY --max-assets 80
```

HTML bytes and image bytes are stored unchanged under content hashes. The private ledger
retains source-page hashes, asset aliases, actual raster dimensions, table/caption context,
acquisition method, failures, and unreviewed status. The gallery does not change PDF source
counts or accepted cohorts. Raster signatures and header dimensions are checked before
bounded decoding; SVG, HTML disguised as an image, and unsupported formats are rejected.

Some agency pages require an ordinary browser. A browser-assisted import binds each
unchanged asset to retained parent HTML and checks its byte count and hash:

```sh
uv run --locked state-id-harvester harvest-images \
  --import-manifest tmp/source-research/WA/driver-adapter-import.json \
  --output output/gallery
```

This import records observed browser evidence; it does not replay or independently prove
the original network transaction. A browser record cannot approve a cohort or issue an
access key. Source-specific usage constraints remain attached to imported evidence.

An import ledger must contain `source_page_url`, `collection`, `html_path`,
`parent_html_sha256`, and an `images` array. Paths are relative to that ledger.
Each image records its observed `url`, final `asset_url`, `path`, `sha256`,
`size_bytes`, and `altered: false`. Optional captions and usage constraints remain
observations. A research download manifest with a `files` array is not this contract;
prepare an explicit adapter ledger that references the unchanged retained HTML and bytes.
Run `verify-images --output output/gallery` after import. Check the run's events for
failed imports: a valid empty inventory does not establish successful acquisition.

Verified private examples include Washington's card-front gallery and New York's annotated
front/back gallery. Separately inspected California, Pennsylvania, Florida, and Virginia
assets supply additional references. Their captions, image composition and usage conditions
require individual review. Agency-delegated non-government CDNs currently remain blocked by
the transport's host policy; AVIF and other unsupported raster formats remain explicit gaps.
