"""Loopback-only viewer of native retained material scores."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import numpy as np
from evidence import digest, require
from evidence import snapshot, read_manifest
from contextlib import ExitStack

PAGE = '''<!doctype html><meta charset="utf-8"><title>ID Cadastral · Material scores</title>
<style>body{font:16px system-ui;background:#142029;color:#e9f1f4;margin:24px}select,button{font:inherit;padding:8px}
.views{display:flex;gap:16px}.views figure{width:50%;margin:0}img{width:100%;cursor:crosshair}
table{border-collapse:collapse}td,th{padding:5px 20px;text-align:left}a{color:#89dee8}#scores{columns:3}</style>
<h1>ID Cadastral · Scene assessment</h1>
<h2>Apple material diagnostics</h2><p id="meta"></p>
<label>Material <select id="layer"></select></label> <label><input id="margin" type="checkbox"> Show top-two margin (all 46 classes)</label><p id="scale"></p>
<div class="views"><figure><figcaption>Original — click either image to inspect a native pixel</figcaption><img id="original" src="/original.jpg"></figure>
<figure><figcaption id="caption"></figcaption><img id="map"></figure></div>
<p>Exact pixel: <label>X <input id="x" type="number" min="0" value="0"></label>
<label>Y <input id="y" type="number" min="0" value="0"></label> <button id="inspect">Inspect</button></p>
<h2 id="point">Select a point</h2><div id="scores"></div>
<p><a href="/scores.npy">Download all 46 native float32 layers</a> · <a href="/manifest.json">Manifest</a> · <a href="/margin.npy">Native top-two margin</a></p>
<script>
let manifest;const $=id=>document.getElementById(id);
async function init(){manifest=await (await fetch('/manifest.json')).json();
$('meta').textContent=`${manifest.width} × ${manifest.height} · 46 native score layers · ${manifest.argmax_mismatches} differences from retained winning labels`;
for(const b of manifest.bands){const o=document.createElement('option');o.value=b.index;o.textContent=b.name;$('layer').append(o)}
$('layer').value=manifest.bands.find(b=>b.name==='Plastic, non-clear').index;
$('x').max=manifest.width-1;$('y').max=manifest.height-1;update();}
function update(){const id=$('layer').value;const margin=$('margin').checked;$('layer').disabled=margin;$('map').src=margin?'/margin.png':`/band-${id}.png`;
$('caption').textContent=margin?'Top-two margin (all 46 classes)':$('layer').selectedOptions[0].textContent;const range=margin?manifest.margin_display_scale:manifest.display_scale;
$('scale').textContent=`Black ${range[0].toFixed(3)} → white ${range[1].toFixed(3)}. All material layers share one display scale. Previews reduced for display; pixel readouts use native scores.`;}
async function inspect(x,y){$('x').value=x;$('y').value=y;const response=await fetch(`/pixel?x=${x}&y=${y}`);if(!response.ok){$('point').textContent='Pixel outside raster';return;}
const p=await response.json();$('point').textContent=`Source pixel (${x}, ${y}) · top-two margin ${p.margin.toFixed(4)}`;
$('scores').replaceChildren();for(const b of p.scores){const row=document.createElement('p');row.textContent=`${b.name}: ${b.score.toFixed(4)}`;$('scores').append(row);}}
for(const id of ['map','original'])$(id).onclick=e=>{const r=e.target.getBoundingClientRect();inspect(Math.min(manifest.width-1,Math.floor((e.clientX-r.left)/r.width*manifest.width)),Math.min(manifest.height-1,Math.floor((e.clientY-r.top)/r.height*manifest.height)));};
$('inspect').onclick=()=>inspect(Number($('x').value),Number($('y').value));$('layer').onchange=update;$('margin').onchange=update;init();
</script>'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--port',type=int,default=8780);a=p.parse_args()
    with ExitStack() as stack:
        serve(a,stack)

def admit_scores(dataset, stack):
    manifest=read_manifest(dataset)
    require(manifest['schema']=='apple_dms_scores_v1', 'Unsupported score schema')
    root=stack.enter_context(snapshot(dataset,manifest,list(manifest['artifacts'])))
    scores=np.load(root/'scores.npy',mmap_mode='r',allow_pickle=False)
    margin=np.load(root/'margin.npy',mmap_mode='r',allow_pickle=False)
    require(scores.shape == (46, manifest['height'], manifest['width']), "Evidence validation failed: scores.shape == (46, manifest['height'], manifest['width'])")
    require(scores.dtype==np.float32 and margin.dtype==np.float32 and margin.shape==scores.shape[1:], 'Invalid score/margin arrays')
    require([b['index'] for b in manifest['bands']]==list(range(46)), 'Invalid band order')
    require(len({b['name'] for b in manifest['bands']})==46, 'Duplicate material names')
    for y in range(scores.shape[1]):
        require(np.isfinite(scores[:,y,:]).all() and np.isfinite(margin[y]).all() and (margin[y]>=0).all(), 'Invalid finite score/margin values')
    return manifest, root, scores, margin

def verify_material_lineage(scores, material_bytes):
    import hashlib
    materials=json.loads(material_bytes)
    require(scores.get('baseline_manifest_sha256')==hashlib.sha256(material_bytes).hexdigest(), 'Score material manifest lineage mismatch')
    for name in ('source_sha256','model_sha256','upstream_commit','width','height'):
        require(name in scores and scores[name]==materials.get(name), 'Score material lineage mismatch: '+name)


class ScoreDataset:
    """One admitted score snapshot, reusable by standalone and assembled viewers."""
    def __init__(self, dataset, stack, expected_source=None, expected_size=None):
        self.manifest, self.root, self.scores, self.margin = admit_scores(dataset, stack)
        if expected_source is not None:
            require(self.manifest.get('source_sha256') == expected_source, 'Score source lineage mismatch')
        if expected_size is not None:
            require((self.manifest['width'],self.manifest['height'])==expected_size,'Score source dimensions mismatch')
        self.allowed = set(self.manifest['artifacts']) | {'manifest.json'}

    def respond(self, handler, path, prefix=''):
        u = urlsplit(path)
        if u.path == '/':
            # Prefix static URLs in the existing presentation; no second score viewer.
            page = PAGE.replace('="/', '="'+prefix+'/').replace("fetch('/", "fetch('"+prefix+"/")
            page = page.replace('fetch(`/', 'fetch(`'+prefix+'/').replace("?'/", "?'"+prefix+"/").replace(":`/", ":`"+prefix+"/")
            data=page.encode();kind='text/html';file=None
        elif u.path == '/pixel':
            try:
                q=parse_qs(u.query)
                if set(q)!={'x','y'} or any(len(v)!=1 for v in q.values()):raise ValueError()
                x=int(q['x'][0]);y=int(q['y'][0])
                if not (0<=x<self.manifest['width'] and 0<=y<self.manifest['height']):raise ValueError()
            except (ValueError,KeyError,IndexError):handler.send_error(400);return
            rows=[dict(name=b['name'],index=i,score=float(self.scores[i,y,x])) for i,b in enumerate(self.manifest['bands'])]
            data=json.dumps(dict(x=x,y=y,margin=float(self.margin[y,x]),scores=sorted(rows,key=lambda b:-b['score'])),allow_nan=False).encode()
            kind='application/json';file=None
        elif not u.query and u.path[1:] in self.allowed:
            file=self.root/u.path[1:];data=None
            kind={'.png':'image/png','.jpg':'image/jpeg','.json':'application/json'}.get(file.suffix,'application/octet-stream')
        else:handler.send_error(404);return
        handler.send_response(200)
        handler.send_header('Content-Type',kind)
        handler.send_header('Content-Length',str(file.stat().st_size if file else len(data)))
        handler.send_header('X-Content-Type-Options','nosniff')
        handler.send_header('Cache-Control','no-store')
        handler.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        handler.end_headers()
        try:
            if file:
                with file.open('rb') as stream:
                    while chunk:=stream.read(1024*1024):handler.wfile.write(chunk)
            else:handler.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass


def serve(a,stack):
    dataset=ScoreDataset(a.dataset,stack)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            port=self.server.server_port
            if self.headers.get_all('Host') not in ([f'127.0.0.1:{port}'],[f'localhost:{port}']):
                self.send_error(403);return
            dataset.respond(self,self.path)
        def log_message(self,*args):pass
    with ThreadingHTTPServer(('127.0.0.1',a.port),Handler) as server:
        print(f'http://127.0.0.1:{server.server_port}',flush=True)
        server.serve_forever()


if __name__=='__main__':main()
