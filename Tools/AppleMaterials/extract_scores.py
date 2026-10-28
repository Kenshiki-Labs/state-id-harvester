"""Retain Apple's decoder logits before argmax, at unchanged source dimensions."""
import argparse
import json
import io
from evidence import publish_staged
from pathlib import Path
import tempfile
import time
import numpy as np
from PIL import Image
import torch
from evidence import digest, require, read_manifest, read_rgb, snapshot, strict_json
from run import admitted_bytes, validate_classes, validate_labels


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--upstream', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.is_symlink():
        raise FileExistsError(a.output)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    m = read_manifest(a.baseline)
    require(m.get('schema') == 'apple_dms_materials_v1', 'Invalid material manifest')
    validate_classes(m['classes'])
    source = Path(m['source'])
    modelpath = a.upstream/'DMS46_v1.pt'
    rgb = read_rgb(source, m['source_sha256'])
    provenance = strict_json(Path(__file__).with_name('source-provenance.json').read_bytes())
    require(m['model_sha256'] == provenance['artifacts']['DMS46_v1.pt'], 'Unexpected model version')
    taxonomy = strict_json(admitted_bytes(a.upstream/'taxonomy.json', provenance['artifacts']['taxonomy.json']))
    require(all(0 <= c['taxonomy_id'] < len(taxonomy['names']) and c['name'] == taxonomy['names'][c['taxonomy_id']] for c in m['classes']), 'Class names do not match upstream')
    model_raw = admitted_bytes(modelpath, m['model_sha256'])
    with snapshot(a.baseline, m, ['labels.png']) as admitted:
        expected = np.asarray(Image.open(admitted/'labels.png')).copy()
        baseline_hash = digest(admitted/'manifest.json')
    h,w = rgb.shape[:2]
    require((w, h) == (m['width'], m['height']), "Evidence validation failed: (w, h) == (m['width'], m['height'])")
    validate_labels(expected, (h,w))
    model = torch.jit.load(io.BytesIO(model_raw), map_location='cpu').eval()
    x = torch.from_numpy(rgb.transpose(2,0,1).copy()).float()
    mean = torch.tensor([.485,.456,.406])[:,None,None]*255
    std = torch.tensor([.229,.224,.225])[:,None,None]*255
    x = ((x-mean)/std).unsqueeze(0)
    start = time.monotonic()
    print(f'Extracting 46 x {h} x {w} native logits', flush=True)
    with torch.inference_mode():
        scores = model.decoder(model.encoder(x), h, w)[0].numpy()
    require(scores.shape == (46, h, w) and scores.dtype == np.float32, 'Evidence validation failed: scores.shape == (46, h, w) and scores.dtype == np.float32')
    # Every source row verified without allocating another full 46-band tensor.
    mismatches = 0
    margin = np.empty((h,w),dtype=np.float32)
    for y in range(h):
        row = scores[:,y,:]
        require(np.isfinite(row).all(), 'Evidence validation failed: np.isfinite(row).all()')
        mismatches += int(np.count_nonzero(row.argmax(axis=0) != expected[y]))
        top = np.partition(row, -2, axis=0)[-2:]
        margin[y] = top[1]-top[0]
    require(np.isfinite(margin).all(), 'Nonfinite top-two margin')
    require(mismatches == 0, f'Argmax differs at {mismatches} pixels')
    require(digest(source) == m['source_sha256'], "Evidence validation failed: digest(source) == m['source_sha256']")
    print(f'All {h*w:,} argmax labels match retained run; writing layers', flush=True)
    with tempfile.TemporaryDirectory(dir=a.output.parent) as tmp:
        out = Path(tmp)/'result'
        out.mkdir()
        np.save(out/'scores.npy', scores, allow_pickle=False)
        np.save(out/'margin.npy', margin, allow_pickle=False)
        lo,hi = float(scores.min()),float(scores.max())
        bands = []
        for i,c in enumerate(m['classes']):
            band = scores[i]
            # Shared display scale for all materials; only previews are reduced.
            display = np.rint((band-lo)/max(hi-lo,1e-30)*255).astype(np.uint8)
            im=Image.fromarray(display)
            im.thumbnail((1200,1200))
            im.save(out/f'band-{i}.png')
            bands.append(dict(index=i,name=c['name'],taxonomy_id=c['taxonomy_id'],
                              min=float(band.min()),max=float(band.max()),mean=float(band.mean(dtype=np.float64))))
        display = Image.fromarray(np.rint(margin/max(float(margin.max()),1e-9)*255).astype(np.uint8))
        display.thumbnail((1200,1200)); display.save(out/'margin.png')
        im=Image.fromarray(rgb); im.thumbnail((1200,1200)); im.save(out/'original.jpg')
        manifest=dict(schema='apple_dms_scores_v1',width=w,height=h,bands=bands,
                      array_axes=['material','y','x'],dtype='float32',coordinates='source_pixel',
                      input_resampling='none',source_sha256=m['source_sha256'],
                      model_sha256=m['model_sha256'],upstream_commit=m['upstream_commit'],
                      torch=torch.__version__,device='cpu',argmax_mismatches=mismatches,
                      baseline_manifest_sha256=baseline_hash,
                      display_scale=[lo,hi],margin_display_scale=[0,float(margin.max())],
                      elapsed_seconds=time.monotonic()-start,
                      artifacts={p.name:digest(p) for p in out.iterdir()})
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        # Verify serialized shape and bytes' numeric identity before publication.
        saved=np.load(out/'scores.npy',mmap_mode='r',allow_pickle=False)
        for i in range(46):
            require(np.array_equal(saved[i], scores[i]), 'Evidence validation failed: np.array_equal(saved[i], scores[i])')
        publish_staged(out,a.output)
    print(f'Published {a.output}',flush=True)


if __name__=='__main__':
    main()
