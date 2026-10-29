"""Measure retained model-pattern separation across an unchanged card mask."""
import argparse
import html
from contextlib import ExitStack
from evidence import snapshot, read_manifest, read_rgb
import json
from pathlib import Path
import tempfile
import os
from evidence import publish_staged
import numpy as np
from PIL import Image
from evidence import digest, require
from metrics import measure


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--scores',type=Path,required=True)
    p.add_argument('--materials',type=Path,required=True)
    p.add_argument('--working',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    with ExitStack() as stack:
        execute(a,stack)

def execute(a,stack):
    if a.output.exists() or a.output.is_symlink():raise FileExistsError(a.output)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    sm=read_manifest(a.scores)
    mm=read_manifest(a.materials)
    wm=read_manifest(a.working)
    require(sm['source_sha256'] == mm['source_sha256'] == wm['sourceHashes']['browser-viewer/original.png'], "Evidence validation failed: sm['source_sha256'] == mm['source_sha256'] == wm['sourceHashes']['browser-viewer/original.png']")
    for root,manifest,names in [(a.scores,sm,['scores.npy']), (a.materials,mm,['labels.png'])]:
        for name in names:assert digest(root/name)==manifest['artifacts'][name]
    for name in ['source-labels.png','working-mask.png']:
        require(digest(a.working / name) == wm['artifacts'][name]['sha256'], "Evidence validation failed: digest(a.working / name) == wm['artifacts'][name]['sha256']")
    source=Path(mm['source']);assert digest(source)==sm['source_sha256']
    require(sm['schema']=='apple_dms_scores_v1' and mm['schema']=='apple_dms_materials_v1', 'Unsupported material schema')
    require(sm['model_sha256']==mm['model_sha256'], 'Model lineage mismatch')
    require(sm['baseline_manifest_sha256']==digest(a.materials/'manifest.json'), 'Material baseline mismatch')
    require(len(sm['bands'])==len(mm['classes'])==46, 'Expected DMS46 class mapping')
    for i,(band,cls) in enumerate(zip(sm['bands'],mm['classes'])):
        require(band['index']==cls['model_index']==i and band['name']==cls['name'] and band['taxonomy_id']==cls['taxonomy_id'], 'Class mapping mismatch')
    a.scores=stack.enter_context(snapshot(a.scores,sm,['scores.npy']))
    a.materials=stack.enter_context(snapshot(a.materials,mm,['labels.png']))
    a.working=stack.enter_context(snapshot(a.working,wm,['source-labels.png','working-mask.png']))
    rgb=read_rgb(source,sm['source_sha256'])
    labels=np.asarray(Image.open(a.materials/'labels.png'))
    regions=np.asarray(Image.open(a.working/'source-labels.png'))
    inside=np.asarray(Image.open(a.working/'working-mask.png'))>0
    require(labels.shape == regions.shape == inside.shape == (sm['height'], sm['width']), "Evidence validation failed: labels.shape == regions.shape == inside.shape == (sm['height'], sm['width'])")
    scores=np.load(a.scores/'scores.npy',mmap_mode='r')
    report,contrast,target_map=measure(scores,labels,regions,inside,sm)
    report['score_manifest_sha256']=digest(a.scores/'manifest.json')
    report['working_manifest_sha256']=digest(a.working/'manifest.json')
    summary=report['regions'];target=report['target_pattern']['index'];other=report['exterior_pattern']['index']
    with tempfile.TemporaryDirectory(dir=a.output.parent) as temp:
        out=Path(temp)/'result';out.mkdir()
        np.save(out/'inside-vs-outside-score.npy',contrast,allow_pickle=False)
        Image.fromarray(target_map.astype('uint8')*255).save(out/'dominant-interior-pattern.png')

        # Both maps are independent model observations, not filled using the mask.
        color=np.where(target_map[...,None],np.array([0,220,160]),np.array([190,80,160])).astype('uint8')
        overlay=Image.blend(Image.fromarray(rgb),Image.fromarray(color),.4)
        overlay.thumbnail((1400,1400));overlay.save(out/'pattern-preview.jpg')
        limit=float(np.abs(contrast).max());v=(np.clip(contrast/limit,-1,1)+1)/2 if limit else np.full_like(contrast,.5)
        color=np.stack([255*(1-v),255*v,np.full_like(v,100)],axis=-1).astype('uint8')
        im=Image.fromarray(color);im.thumbnail((1400,1400));im.save(out/'contrast-preview.jpg')
        report['contrast_display_range']=[-limit,limit]
        report['artifacts']={f.name:digest(f) for f in out.iterdir()}
        (out/'assessment.json').write_text(json.dumps(report,indent=2)+'\n')
        def percentage(value): return '—' if value is None else f'{value:.1%}'
        rows=''.join(f'<tr><td>{k}</td><td>{r["pixels"]:,}</td><td>{percentage(r["dominant_fraction"]) }</td><td>{percentage(r["target_winner_fraction"]) }</td><td>{percentage(r["target_beats_exterior_fraction"]) }</td></tr>' for k,r in summary.items())
        status='Distinct dominant regional patterns observed.' if report['distinct_dominant_patterns'] else 'No distinct dominant regional patterns: both regions select the same channel; the contrast is zero.'
        page=f'''<!doctype html><meta charset="utf-8"><title>ID Cadastral · Surface separation</title>
<style>body{{font:16px system-ui;background:#142029;color:#e9f1f4;margin:24px}}td,th{{padding:8px;text-align:left}}.views{{display:flex;gap:16px}}figure{{width:50%;margin:0}}img{{width:100%}}a{{color:#8de2ef}}</style>
<h1>License surface versus surroundings</h1>
<p>{status}</p>
<p>Existing working boundary · all {inside.size:,} native pixels · unchanged Apple scores</p>
<p>Dominant interior pattern: {html.escape(sm['bands'][target]['name'])}. Dominant outside pattern: {html.escape(sm['bands'][other]['name'])}. Names identify model channels, not verified materials.</p>
<p>Interior-pattern coverage: {report['target_map']['inside_coverage']:.1%}. Of all pixels assigned that pattern, {report['target_map']['precision_inside']:.1%} lie inside. Mask overlap (IoU): {report['target_map']['iou']:.1%}.</p>
<div class="views"><figure><figcaption>Green: dominant interior pattern wins among all 46 classes. Purple: another class wins.</figcaption><img src="pattern-preview.jpg"></figure><figure><figcaption>Green: interior channel stronger. Red: exterior channel stronger. Continuous raw score difference.</figcaption><img src="contrast-preview.jpg"></figure></div>
<table><tr><th>Region</th><th>Pixels</th><th>Own dominant pattern</th><th>Interior pattern wins / 46</th><th>Interior beats exterior channel</th></tr>{rows}</table>
<p>Patterns selected and measured on this sample. This is descriptive separation, not held-out classifier accuracy. No reproduction comparison has been run.</p>
<p><a href="assessment.json">All measurements, boundary transitions and provenance</a> · <a href="inside-vs-outside-score.npy">Native score-difference raster</a> · <a href="dominant-interior-pattern.png">Native target-pattern mask</a></p>'''
        (out/'index.html').write_text(page)
        report['artifacts']['index.html']=digest(out/'index.html')
        (out/'assessment.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        publish_staged(out,a.output)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
