"""Publish a plain local comparison page without mutating the experiment run."""
import argparse
import hashlib
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from publication import publish_directory


def report(run, output, review=None, adjacency=None):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.exists() or output == run or run in output.parents:
        raise ValueError('Report must use a new directory outside the immutable run')
    raw_manifest = (run / 'manifest.json').read_bytes()
    manifest = json.loads(raw_manifest)
    if manifest.get('type') != 'id_cadastral_region_experiment' or manifest.get('schemaVersion') != 1:
        raise ValueError('Unsupported region experiment')
    run_hash = hashlib.sha256(raw_manifest).hexdigest()
    review_data = None
    if review is not None:
        review = Path(review).resolve()
        review_data = json.loads(review.read_bytes())
        if review_data.get('experimentManifestSHA256') != run_hash:
            raise ValueError('Review belongs to another experiment')
    exact_native = manifest.get('adjacencyMethod') == 'skimage_rag_four_connected_exact_interfaces'
    corrected = {}
    if adjacency is not None:
        adjacency = Path(adjacency).resolve()
        adjacency_manifest = json.loads((adjacency / 'manifest.json').read_bytes())
        if (adjacency_manifest.get('sourceRunManifestSHA256') != run_hash or
                adjacency_manifest.get('method') != 'skimage_rag_four_connected_exact_interfaces'):
            raise ValueError('Corrected adjacency belongs to another experiment or method')
        for condition in adjacency_manifest['conditions']:
            name = condition['condition'] + '-regions.json'
            if Path(name).name != name:
                raise ValueError('Invalid corrected artifact filename')
            data = (adjacency / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != adjacency_manifest['artifacts'][name]['sha256']:
                raise ValueError('Corrected adjacency artifact integrity mismatch')
            corrected[condition['condition']] = (condition['adjacencyCount'],
                quote(os.path.relpath(adjacency / name, output), safe='/'))

    def verified_link(name):
        if Path(name).name != name or name not in manifest['artifacts']:
            raise ValueError('Artifact is not a manifest filename')
        path = run / name
        data = path.read_bytes()
        recorded = manifest['artifacts'][name]
        if hashlib.sha256(data).hexdigest() != recorded['sha256'] or len(data) != recorded['bytes']:
            raise ValueError('Artifact integrity mismatch: ' + name)
        return quote(os.path.relpath(path, output), safe='/')

    conditions = manifest['conditions']
    expected = {(mode, depth) for mode in ['luminance', 'chroma_texture'] for depth in [.08, .16]}
    if {(c['cueMode'], c['markerDepth']) for c in conditions} != expected or len(conditions) != 4:
        raise ValueError('Expected the four preregistered conditions')
    windows = list(conditions[0]['diagnosticWindows'])
    if any(set(c['diagnosticWindows']) != set(windows) for c in conditions):
        raise ValueError('Mismatched diagnostic windows')
    rows = []
    for condition in conditions:
        name = condition['condition']
        url = verified_link(name + '-regions.json')
        exact = str(condition['adjacencyCount']) if exact_native else 'Not supplied'
        if name in corrected:
            count, corrected_url = corrected[name]
            exact = str(count) + ' — <a href="' + corrected_url + '">Exact interface JSON</a>'
        recorded_count = '—' if exact_native else str(condition['adjacencyCount'])
        evidence_label = 'Exact interface JSON' if exact_native else 'Legacy region JSON'
        rows.append('<tr><td>' + escape(name) + '</td><td>' + str(condition['regionCount']) +
                    '</td><td>' + recorded_count + '</td><td>' +
                    exact + '</td><td>' + str(condition['assignedPixels']) + '</td><td><a href="' + url +
                    '">' + evidence_label + '</a></td></tr>')
    comparisons = []
    for window in windows:
        bounds = conditions[0]['diagnosticWindows'][window]['sourceBounds']
        cards = ['<figure><figcaption>Original pixels</figcaption><img src="' +
                 verified_link('source-' + window + '.png') + '" alt="Original ' +
                 escape(window, quote=True) + '"></figure>']
        for condition in conditions:
            name = condition['condition']
            if condition['diagnosticWindows'][window]['sourceBounds'] != bounds:
                raise ValueError('Diagnostic coordinate mismatch')
            cards.append('<figure><figcaption>' + escape(name) + '</figcaption><img src="' +
                         verified_link(name + '-' + window + '.png') +
                         '" alt="Region boundaries for ' + escape(window, quote=True) + '"></figure>')
        comparisons.append('<section><h2>' + escape(window) + '</h2><p>Source pixel bounds: ' +
                           escape(str(bounds)) + '</p><div class="comparison">' + ''.join(cards) +
                           '</div></section>')
    manifest_url = quote(os.path.relpath(run / 'manifest.json', output), safe='/')
    width, height = manifest['sourceSize']
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ID Cadastral — native region comparison</title>
<style>body{font:16px system-ui;margin:24px;line-height:1.5;background:#fafafa;color:#171717}
table{border-collapse:collapse}th,td{padding:8px 16px;border:1px solid #ccc;text-align:left}
.comparison{display:flex;gap:12px;overflow-x:auto;align-items:flex-start}figure{margin:0;flex:none}
figcaption{margin-bottom:8px;font-weight:600}img{display:block;image-rendering:pixelated;max-width:80vw;max-height:75vh;object-fit:contain}
section{margin-top:32px}pre{white-space:pre-wrap;max-width:1000px}</style>
<h1>ID Cadastral — native region comparison</h1>
<p>Four automatic full-scene partitions. Magenta marks region boundaries.
Region meanings are unassigned; these are not accepted card perimeters.</p>'''
    if review_data is None:
        page += '<p><strong>Review status: unassessed. No review was supplied.</strong></p>'
    else:
        review_url = quote(os.path.relpath(review, output), safe='/')
        page += '<p><strong>Review status: ' + escape(review_data['status'].replace('_', ' ')) + \
                '.</strong> <a href="' + review_url + '">Independent review JSON</a></p>'
        page += '<p>' + escape(review_data['interpretation']['conclusion']) + '</p>'
        page += '<ul>' + ''.join('<li>' + escape(review_data['interpretation'][key]) + '</li>'
                    for key in ['luminance_h008', 'higher_depth', 'chroma_texture_h008']) + '</ul>'
    page += '<p>Native source: ' + str(width) + ' × ' + str(height) + ' (' + str(width * height) + \
            ' pixels). <a href="' + manifest_url + '">Run manifest</a>.</p>'
    if manifest.get('diagnosticScope') == 'full_scene':
        page += '<p>These panels cover the complete source image. No historical inspection coordinates or damage observations were applied to this capture.</p>'
    else:
        page += '<p>The diagnostic windows are retained historical inspection coordinates. Their applicability to a new capture must be established separately.</p>'
    page += ('<p>The recorded graphs count exact four-connected pixel interfaces. No physical boundary is selected.</p>' if exact_native else
             '<p>The initial graph is retained as legacy evidence; corrected side-sharing graphs are separate artifacts.</p>')
    page += '<table><thead><tr><th>Condition</th><th>Regions</th><th>Legacy library graph edges</th><th>Corrected side-sharing edges</th>' \
            '<th>Assigned pixels</th><th>Evidence</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    page += ''.join(comparisons)
    page += '<h2>Recorded parameters</h2><pre>' + escape(json.dumps(manifest['parameters'], indent=2)) + '</pre>'
    page += '<p>Report source manifest SHA256: <code>' + hashlib.sha256(raw_manifest).hexdigest() + '</code>.</p>'
    page += '</html>'
    if (run / 'manifest.json').read_bytes() != raw_manifest:
        raise ValueError('Manifest changed during report generation')
    output.parent.mkdir(parents=True, exist_ok=True)
    publish_directory(output, {'report.html': page.encode('utf-8')})
    return output / 'report.html'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--adjacency', type=Path)
    args = parser.parse_args()
    print(report(args.run, args.output, args.review, args.adjacency))
