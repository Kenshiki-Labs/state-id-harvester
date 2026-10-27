"""Local full-scene inference using Apple's unmodified DMS46 TorchScript model.

Preprocessing and class mapping adapted from apple/ml-dms-dataset inference.py.
Copyright (C) 2022 Apple Inc. See LICENSE.txt and ACKNOWLEDGMENTS.txt.
"""
import argparse
import ast
import hashlib
import json
import io
from evidence import publish_staged
from pathlib import Path
import tempfile
import time

import numpy as np
from PIL import Image
import torch
from evidence import digest, require, read_rgb, strict_json


def admitted_bytes(path, expected):
    path = Path(path)
    require(not path.is_symlink(), 'Input symlink is not permitted')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'Input hash mismatch')
    return raw


def validate_classes(classes):
    require(isinstance(classes, list) and len(classes) == 46, 'Expected 46 material classes')
    require(all(isinstance(c, dict) and type(c.get('model_index')) is int and
                c['model_index'] == i and type(c.get('taxonomy_id')) is int and
                isinstance(c.get('name'), str) and c['name'] for i,c in enumerate(classes)),
            'Invalid class identity')
    require(len({c['taxonomy_id'] for c in classes}) == 46, 'Duplicate taxonomy identities')


def validate_labels(labels, shape):
    require(labels.shape == shape and labels.ndim == 2 and
            np.issubdtype(labels.dtype, np.integer) and labels.size > 0 and
            labels.min() >= 0 and labels.max() < 46, 'Invalid native labels')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'mps'], required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source_hash = digest(args.image)
    upstream = args.upstream
    # Read Apple's class mapping directly; do not recreate or renumber taxonomy.
    provenance = strict_json(Path(__file__).with_name('source-provenance.json').read_bytes())
    tree = ast.parse(admitted_bytes(upstream / 'inference.py', provenance['artifacts']['inference.py']).decode())
    classes = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'dms46' for t in node.targets))
    taxonomy = strict_json(admitted_bytes(upstream / 'taxonomy.json', provenance['artifacts']['taxonomy.json']))
    require(len(classes) == 46 and len(set(classes)) == 46 and all(type(c) is int and 0 <= c < len(taxonomy['names']) and c < len(taxonomy['srgb_colormap']) for c in classes), 'Invalid upstream class mapping')
    rgb = read_rgb(args.image, source_hash)
    h, w = rgb.shape[:2]
    model_path = upstream / 'DMS46_v1.pt'
    model_raw = admitted_bytes(model_path, provenance['artifacts']['DMS46_v1.pt'])
    model = torch.jit.load(io.BytesIO(model_raw), map_location=args.device).eval()
    tensor = torch.from_numpy(rgb.transpose(2, 0, 1).copy()).to(args.device, torch.float32)
    mean = torch.tensor([0.485, 0.456, 0.406], device=args.device)[:, None, None] * 255
    std = torch.tensor([0.229, 0.224, 0.225], device=args.device)[:, None, None] * 255
    tensor = ((tensor - mean) / std).unsqueeze(0)
    print(f'Apple DMS46: native input {w} x {h}, device {args.device}', flush=True)
    with torch.inference_mode():
        labels = model(tensor)[0].cpu().numpy()[0, 0]
    validate_labels(labels, (h,w))
    if digest(args.image) != source_hash:
        raise ValueError('Source changed during inference')
    labels = labels.astype(np.uint8)
    colors = np.asarray(taxonomy['srgb_colormap'], dtype=np.uint8)[classes]
    counts = np.bincount(labels.ravel(), minlength=len(classes))
    rows = [dict(model_index=i, taxonomy_id=c, name=taxonomy['names'][c],
                 pixels=int(counts[i]), fraction=float(counts[i] / (w*h)),
                 rgb=colors[i].tolist()) for i, c in enumerate(classes)]
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temp:
        out = Path(temp) / 'result'
        out.mkdir()
        Image.fromarray(labels).save(out / 'labels.png')
        colored = colors[labels]
        Image.fromarray(colored).save(out / 'materials.png')
        Image.blend(Image.fromarray(rgb), Image.fromarray(colored), 0.45).save(out / 'overlay.png')
        manifest = dict(schema='apple_dms_materials_v1', source=str(args.image.resolve()),
                        source_sha256=source_hash, width=w, height=h, pixels=w*h,
                        coordinates='source_pixel', input_resampling='none',
                        inference='whole_scene', device=args.device, torch=torch.__version__,
                        upstream_commit=provenance['upstream_commit'],
                        model_sha256=hashlib.sha256(model_raw).hexdigest(), output_type='argmax_material_class',
                        classes=rows, elapsed_seconds=time.monotonic()-started,
                        artifacts={p.name:digest(p) for p in out.iterdir()})
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n')
        publish_staged(out,args.output)
    print(json.dumps(sorted(rows, key=lambda r: -r['pixels'])[:8], indent=2), flush=True)
    print(f'Published {args.output}', flush=True)


if __name__ == '__main__':
    main()
