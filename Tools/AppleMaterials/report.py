"""Summarize retained model labels by existing scene regions; no relabeling."""
import argparse
import hashlib
import io
import tempfile
import html
import json
from pathlib import Path

from evidence import require, read_manifest, snapshot, read_rgb, publish_staged
from run import validate_classes, validate_labels
import numpy as np
from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--result', type=Path, required=True)
    p.add_argument('--regions', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.is_symlink(): raise FileExistsError(a.output)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    m = read_manifest(a.result)
    require(m.get('schema') == 'apple_dms_materials_v1', 'Invalid material manifest')
    validate_classes(m['classes'])
    with snapshot(a.result, m, list(m['artifacts'])) as admitted:
        files = {name: (admitted/name).read_bytes() for name in ['manifest.json']+list(m['artifacts'])}
    labels = np.asarray(Image.open(io.BytesIO(files['labels.png']))).copy()
    validate_labels(labels, (m['height'], m['width']))
    wm = read_manifest(a.regions.parent)
    require(wm.get('type') == 'id_cadastral_interior_working_area' and wm.get('schemaVersion') == 1,
            'Expected working-area region package')
    require(wm['sourceHashes']['browser-viewer/original.png'] == m['source_sha256'], 'Region source mismatch')
    with snapshot(a.regions.parent, wm, [a.regions.name]) as admitted:
        region_raw = (admitted/a.regions.name).read_bytes()
    regions = np.asarray(Image.open(io.BytesIO(region_raw))).copy()
    require(regions.dtype == np.uint8 and labels.shape == regions.shape and
            set(np.unique(regions)) <= {0,1,2,3}, 'Invalid native regions')
    rgb = read_rgb(Path(m['source']), m['source_sha256'])
    require(rgb.shape[:2] == labels.shape, 'Source dimensions mismatch')
    counts = np.bincount(labels.ravel(), minlength=46)
    require(m['pixels'] == labels.size and all(c['pixels'] == int(counts[i]) and
            np.isclose(c['fraction'], counts[i]/labels.size, rtol=0, atol=1e-12)
            for i,c in enumerate(m['classes'])), 'Class counts mismatch')
    names = ['surroundings', 'interior_eligible', 'edge_unresolved', 'shadow_working_region']
    summaries = []
    for region, name in enumerate(names):
        counts = np.bincount(labels[regions == region], minlength=len(m['classes']))
        n = int(counts.sum())
        rows = [dict(name=c['name'], model_index=c['model_index'], pixels=int(counts[i]),
                     fraction=float(counts[i]/n) if n else None)
                for i, c in enumerate(m['classes'])]
        summaries.append(dict(region=name, pixels=n,
                              classes=sorted(rows, key=lambda r: -r['pixels'])))
    require(sum((r['pixels'] for r in summaries)) == labels.size, "Evidence validation failed: sum((r['pixels'] for r in summaries)) == labels.size")
    region_hash = hashlib.sha256(region_raw).hexdigest()
    report = dict(schema='apple_dms_region_summary_v1', regions=str(a.regions.resolve()),
                  regions_sha256=region_hash, summaries=summaries,
                  material_manifest_sha256=hashlib.sha256(files['manifest.json']).hexdigest())
    # Only display previews are reduced. Analysis arrays remain native.
    previews = {}
    for raw, target in [(None, 'source-preview.jpg'),
                        (files['materials.png'], 'materials-preview.png'),
                        (files['overlay.png'], 'overlay-preview.jpg')]:
        image = Image.fromarray(rgb) if raw is None else Image.open(io.BytesIO(raw))
        require(image.size == (m['width'],m['height']), 'Presentation raster dimensions mismatch')
        image.thumbnail((1200,1200))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG' if target.endswith('.png') else 'JPEG')
        previews[target] = buffer.getvalue()
    sections = ''
    for region in summaries:
        rows = ''.join(f'<tr><td>{html.escape(c["name"])}</td><td>{c["fraction"]:.1%}</td>'
                       f'<td>{c["pixels"]:,}</td></tr>' for c in region['classes'][:6] if c['pixels'])
        sections += f'<section><h2>{html.escape(region["region"])}</h2><table>{rows}</table></section>'
    legend = ''.join(f'<li><span style="background:rgb{tuple(c["rgb"])}">&nbsp;&nbsp;&nbsp;</span> '
                     f'{html.escape(c["name"])}: {c["fraction"]:.1%}</li>'
                     for c in sorted(m['classes'], key=lambda c: -c['pixels']) if c['pixels'])
    page = f'''<!doctype html><meta charset="utf-8"><title>ID Cadastral · Apple materials</title>
<style>body{{background:#111b22;color:#e4edf2;font:16px system-ui;margin:24px}}a{{color:#7ed7df}}
.images{{display:flex;gap:12px}}figure{{margin:0;flex:1;min-width:0}}img{{width:100%}}
.regions{{display:flex;gap:30px;flex-wrap:wrap}}td{{padding:5px 12px}}li{{margin:8px}}</style>
<h1>ID Cadastral · Apple material predictions</h1>
<p>Native whole-scene input: {m['width']:,} × {m['height']:,} · {m['pixels']:,} pixels · {m['elapsed_seconds']:.1f} seconds</p>
<p>Unmodified DMS46 model. Model predictions; existing region names are comparison areas. No confidence output.</p>
<div class="images"><figure><figcaption>Original scene</figcaption><img src="source-preview.jpg"></figure>
<figure><figcaption>Material labels</figcaption><a href="materials.png"><img src="materials-preview.png"></a></figure>
<figure><figcaption>Overlay</figcaption><a href="overlay.png"><img src="overlay-preview.jpg"></a></figure></div>
<p>Previews are reduced for display; click predictions for native resolution.</p>
<div class="regions">{sections}</div><h2>Full-scene legend</h2><ul>{legend}</ul>
<a href="manifest.json">Model and raster manifest</a> · <a href="region-summary.json">Region counts JSON</a> ·
<a href="labels.png">Native class-index raster</a>'''
    with tempfile.TemporaryDirectory(dir=a.output.parent) as temp:
        out = Path(temp)/'report'; out.mkdir()
        for name, raw in {**files, **previews}.items(): (out/name).write_bytes(raw)
        (out/'region-summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        (out/'index.html').write_text(page)
        publish_staged(out,a.output)
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
