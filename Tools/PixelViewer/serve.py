#!/usr/bin/env python3
"""Serve only the viewer and verified baseline derivatives on loopback."""
import argparse
import hashlib
import json
import io
import math
import sys
from types import MappingProxyType
from contextlib import ExitStack
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = Path(__file__).resolve().parent
sys.path.insert(0, str(WEB.parent / 'CardBoundary'))
from validate_dataset import validate_dataset


def rectification_snapshot(directory, boundary_manifest, boundary_geometry):
    """Validate the exact optional package bytes retained for serving."""
    import numpy as np
    from PIL import Image
    payload = (directory / 'manifest.json').read_bytes()
    manifest = json.loads(payload)
    if (manifest.get('schemaVersion') != 1 or manifest.get('type') != 'id_cadastral_rectification'
            or manifest.get('boundaryId') != boundary_manifest.get('boundaryId')
            or manifest.get('sourceHashes') != boundary_manifest['sourceHashes']):
        raise ValueError('Rectification schema or lineage mismatch')
    output = manifest['output']
    if any(type(output.get(k)) is not int or output[k] <= 0 for k in ('width', 'height')):
        raise ValueError('Rectification dimensions invalid')
    scale = output.get('pixelsPerMillimeter')
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Rectification scale invalid')
    matrices = {}
    for key in ('sourceToRectified', 'rectifiedToSource', 'sourceToCardMillimeters', 'cardMillimetersToSource'):
        values = manifest['transforms'][key]
        if not isinstance(values, list) or len(values) != 9 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('Rectification transform invalid')
        matrices[key] = np.array(values).reshape(3, 3)
    def equivalent(a, b):
        return abs(a[2, 2]) > 1e-12 and abs(b[2, 2]) > 1e-12 and np.allclose(a/a[2, 2], b/b[2, 2], rtol=1e-9, atol=1e-8)
    for forward, inverse in [('sourceToRectified', 'rectifiedToSource'), ('sourceToCardMillimeters', 'cardMillimetersToSource')]:
        if not equivalent(matrices[forward] @ matrices[inverse], np.eye(3)):
            raise ValueError('Rectification transform inverse mismatch')
    origin = output.get('originCardMillimeters')
    if not isinstance(origin, list) or len(origin) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in origin):
        raise ValueError('Rectification origin invalid')
    card_to_pixel = np.array([[scale, 0, -origin[0]*scale], [0, scale, -origin[1]*scale], [0, 0, 1]])
    if not equivalent(card_to_pixel @ matrices['sourceToCardMillimeters'], matrices['sourceToRectified']):
        raise ValueError('Rectification coordinate scale mismatch')
    snapshot = {'/rectification-manifest.json': (payload, 'application/json')}
    artifacts = {}
    for key, name, mime in [('image', 'rectified.png', 'image/png'), ('contour', 'contour.json', 'application/json'), ('residuals', 'residuals.npz', 'application/octet-stream')]:
        entry = manifest['artifacts'][key]
        if entry['path'] != name:
            raise ValueError('Rectification artifact path invalid')
        data = (directory / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Rectification artifact hash mismatch: ' + key)
        artifacts[key] = data
        snapshot['/rectification-' + name] = (data, mime)
    with Image.open(io.BytesIO(artifacts['image'])) as image:
        image.load()
        if image.format != 'PNG' or image.mode != 'RGB' or image.size != (output['width'], output['height']):
            raise ValueError('Rectification image dimensions or mode mismatch')
    contour = json.loads(artifacts['contour'])
    if contour.get('type') != 'Polygon' or len(contour.get('coordinates', [])) != len(boundary_geometry['coordinates']):
        raise ValueError('Rectification contour invalid')
    for original, transformed in zip(boundary_geometry['coordinates'], contour['coordinates']):
        points = np.asarray(original, dtype=float)
        projected = np.column_stack((points, np.ones(len(points)))) @ matrices['sourceToRectified'].T
        if np.any(np.abs(projected[:, 2]) < 1e-12):
            raise ValueError('Rectification contour projection singular')
        expected = projected[:, :2] / projected[:, 2, None]
        actual = np.asarray(transformed, dtype=float)
        if actual.shape != expected.shape or not np.isfinite(actual).all() or not np.allclose(actual, expected, rtol=1e-9, atol=1e-7):
            raise ValueError('Rectification observed contour mismatch')
        if np.any(actual < 0) or np.any(actual[:, 0] > output['width']) or np.any(actual[:, 1] > output['height']):
            raise ValueError('Rectification observed contour clipped')
    return snapshot


def edge_snapshot(directory, source_hashes):
    """Retain only the edge package bytes admitted by its shared validator."""
    sys.path.insert(0, str(WEB.parent))
    from CardEdges.dataset import load_dataset
    _, _, _, _, files = load_dataset(directory, source_hashes=source_hashes)
    return {'/edges-' + name: (files[name], 'application/json' if name.endswith('.json') else 'application/octet-stream')
            for name in ('manifest.json', 'points.npy', 'offsets.npy', 'chains.json')}


def topology_snapshot(directory, source_hashes, edge_manifest_hash=None):
    """Serve only bytes admitted by the topology package's shared validator."""
    sys.path.insert(0, str(WEB.parent))
    from CardTopology.dataset import load_dataset
    _, _, _, files = load_dataset(directory, source_hashes=source_hashes,
                                  edge_manifest_hash=edge_manifest_hash)
    return {'/topology-' + name: (data, 'application/json' if name.endswith(('.json', '.geojson')) else 'application/octet-stream')
            for name, data in files.items()}


def measurement_snapshot(directory, model_directory, boundary_manifest, rectification_bytes):
    sys.path.insert(0, str(WEB.parent))
    from CardMeasurements.measure import load_dataset
    from CardBoundary.json_contract import strict_json
    registration_hash=hashlib.sha256(rectification_bytes).hexdigest()
    _,files=load_dataset(directory,boundary_manifest['sourceHashes'],boundary_manifest['boundaryId'],registration_hash)
    routes={'/measurements-'+n:(v,'application/json' if n.endswith('.json') else 'application/octet-stream') for n,v in files.items()}
    if model_directory is not None:
        path=model_directory/'models.json'
        if path.is_symlink():raise ValueError('Model artifact symlink')
        data=path.read_bytes();model=strict_json(data)
        if model.get('measurementManifestSHA256')!=hashlib.sha256(files['manifest.json']).hexdigest() or model.get('rectificationManifestSHA256')!=registration_hash:
            raise ValueError('Model lineage mismatch')
        routes['/measurement-models.json']=(data,'application/json')
    return routes


def perimeter_snapshot(directory, source_hashes, edge_hash):
    sys.path.insert(0, str(WEB.parent))
    from PerimeterCandidates.dataset import load_dataset
    _, files = load_dataset(directory, source_hashes, edge_hash)
    result = {'/perimeter/' + name: (data, 'application/json' if name.endswith('.json') else 'application/octet-stream') for name, data in files.items()}
    for name, route, mime in [('report.html', '/perimeter-report.html', 'text/html; charset=utf-8'), ('report.js', '/perimeter-report.js', 'text/javascript; charset=utf-8')]:
        result[route] = ((WEB.parent / 'PerimeterCandidates' / name).read_bytes(), mime)
    return result


def assembly_snapshot(directory, source_hashes, candidate_hash):
    raw=(directory/'manifest.json').read_bytes()
    manifest=json.loads(raw)
    if manifest.get('type')!='id_cadastral_path_assembly' or manifest.get('schemaVersion')!=1 or manifest.get('sourceHashes')!=source_hashes or manifest.get('candidateManifestSHA256')!=candidate_hash:
        raise ValueError('Assembly lineage mismatch')
    path=directory/'assembly.json'
    if directory.is_symlink() or path.is_symlink() or (directory/'manifest.json').is_symlink():raise ValueError('Assembly symlink')
    data=path.read_bytes()
    if manifest.get('artifacts')!={'assembly.json':{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}}:raise ValueError('Assembly artifact mismatch')
    return {'/assembly/manifest.json':(raw,'application/json'), '/assembly/assembly.json':(data,'application/json'),
            '/assembly.html':((WEB.parent/'PerimeterCandidates/assembly.html').read_bytes(),'text/html; charset=utf-8'),
            '/assessment-ui.js':((WEB.parent/'PerimeterCandidates/assessment-ui.js').read_bytes(),'text/javascript; charset=utf-8'),
            '/assembly.js':((WEB.parent/'PerimeterCandidates/assembly.js').read_bytes(),'text/javascript; charset=utf-8')}


def path_assessment_snapshot(directory, source_hashes, assembly_hash):
    if directory.is_symlink() or any((directory/n).is_symlink() for n in ('manifest.json','assessment.json')):raise ValueError('Assessment symlink')
    raw=(directory/'manifest.json').read_bytes();m=json.loads(raw)
    if m.get('schemaVersion')!=1 or m.get('type')!='id_cadastral_path_assessment' or m.get('sourceHashes')!=source_hashes or m.get('assemblyManifestSHA256')!=assembly_hash:raise ValueError('Path assessment lineage mismatch')
    data=(directory/'assessment.json').read_bytes()
    if m.get('artifacts')!={'assessment.json':{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}}:raise ValueError('Path assessment hash mismatch')
    return {'/path-assessment.json':(data,'application/json'),'/path-assessment-manifest.json':(raw,'application/json')}


def snapshot_files(baseline, boundary, rectification=None, edges=None, topology=None, measurements=None, measurement_models=None, perimeter=None, assembly=None, path_assessment=None, working_area=None):
    """Admit the dataset, then retain verified response bytes for this server run."""
    manifest = validate_dataset(boundary, baseline)
    out = baseline / 'browser-viewer'
    files = {
        '/': (WEB / 'index.html', 'text/html; charset=utf-8'),
        '/app.js': (WEB / 'app.js', 'text/javascript; charset=utf-8'),
        '/boundary-manifest.json': (boundary / 'manifest.json', 'application/json'),
        '/boundary-geometry.json': (boundary / 'geometry.json', 'application/json'),
        '/boundary-assessments.json': (boundary / 'assessments.json', 'application/json'),
        '/boundary-mask.png': (boundary / 'mask.png', 'image/png'),
        '/objects.json': (out / 'objects.json', 'application/json'),
        '/objects-mask.png': (out / 'objects-mask.png', 'image/png'),
        '/original.heic': (baseline / 'front-original.heic', 'image/heic'),
        '/original.png': (out / 'original.png', 'image/png'),
        '/geotiff.png': (out / 'geotiff.png', 'image/png'),
        '/front-card.tif': (baseline / 'geotiff/front-card.tif', 'image/tiff'),
        '/geotiff-manifest.json': (baseline / 'geotiff/manifest.json', 'application/json'),
        '/manifest.json': (out / 'manifest.json', 'application/json'),
    }
    snapshot = {route: (path.read_bytes(), mime) for route, (path, mime) in files.items()}
    if json.loads(snapshot['/boundary-manifest.json'][0]) != manifest:
        raise ValueError('Boundary manifest changed during admission')
    # Check the exact retained bytes, including display derivatives that are
    # outside the boundary package, before any HTTP response can be served.
    expected = {str(baseline / name): sha for name, sha in manifest['sourceHashes'].items()}
    for name, artifact in manifest['artifacts'].items():
        expected[str(boundary / artifact['path'])] = artifact['sha256']
    viewer = json.loads(snapshot['/manifest.json'][0])
    objects = json.loads(snapshot['/objects.json'][0])
    geotiff = json.loads(snapshot['/geotiff-manifest.json'][0])
    expected[str(out / 'original.png')] = viewer['viewerDerivation']['outputSHA256']
    expected[str(out / 'geotiff.png')] = viewer['geoTIFFDisplay']['displaySHA256']
    expected[str(out / 'objects-mask.png')] = objects['mask']['sha256']
    expected[str(baseline / 'geotiff/front-card.tif')] = geotiff['output']['sha256']
    if (viewer['derivation']['sourceSHA256'] != manifest['sourceHashes']['front-original.heic']
            or viewer['geoTIFFDisplay']['sourceSHA256'] != geotiff['output']['sha256']):
        raise ValueError('Browser display lineage mismatch')
    for route, (path, _) in files.items():
        if str(path) in expected and hashlib.sha256(snapshot[route][0]).hexdigest() != expected[str(path)]:
            raise ValueError('Snapshot hash mismatch: ' + route)
    if validate_dataset(boundary, baseline) != manifest:
        raise ValueError('Dataset changed during admission')
    snapshot['/viewer-config.json'] = (json.dumps({'rectificationAvailable': rectification is not None, 'edgesAvailable': edges is not None, 'topologyAvailable': topology is not None, 'measurementsAvailable': measurements is not None, 'measurementModelsAvailable': measurement_models is not None, 'perimeterAvailable': perimeter is not None, 'assemblyAvailable': assembly is not None, 'pathAssessmentAvailable': path_assessment is not None, 'workingAreaAvailable': working_area is not None}).encode(), 'application/json')
    if rectification is not None:
        snapshot.update(rectification_snapshot(rectification, manifest, json.loads(snapshot['/boundary-geometry.json'][0])))
    if edges is not None:
        snapshot.update(edge_snapshot(edges, manifest['sourceHashes']))
    if topology is not None:
        edge_hash = hashlib.sha256(snapshot['/edges-manifest.json'][0]).hexdigest() if edges is not None else None
        snapshot.update(topology_snapshot(topology, manifest['sourceHashes'], edge_hash))
    if measurements is not None:
        if rectification is None:raise ValueError('Measurements require their rectification package')
        snapshot.update(measurement_snapshot(measurements,measurement_models,manifest,snapshot['/rectification-manifest.json'][0]))
    elif measurement_models is not None:raise ValueError('Models require measurements')
    if perimeter is not None:
        if edges is None:raise ValueError('Perimeter candidates require their edge dataset')
        snapshot.update(perimeter_snapshot(perimeter, manifest['sourceHashes'], hashlib.sha256(snapshot['/edges-manifest.json'][0]).hexdigest()))
    if assembly is not None:
        if perimeter is None:raise ValueError('Assembly requires perimeter candidates')
        snapshot.update(assembly_snapshot(assembly,manifest['sourceHashes'],hashlib.sha256(snapshot['/perimeter/manifest.json'][0]).hexdigest()))
    if path_assessment is not None:
        if assembly is None:raise ValueError('Path assessment requires assembly')
        snapshot.update(path_assessment_snapshot(path_assessment,manifest['sourceHashes'],hashlib.sha256(snapshot['/assembly/manifest.json'][0]).hexdigest()))
    if working_area is not None:
        if rectification is None:raise ValueError('Working area requires its registration')
        sys.path.insert(0,str(WEB.parent))
        from CardInterior.viewer import snapshot as working_snapshot
        snapshot.update(working_snapshot(working_area,manifest['sourceHashes'],manifest['boundaryId'],hashlib.sha256(snapshot['/rectification-manifest.json'][0]).hexdigest()))
    snapshot['/working.js']=((WEB/'working.js').read_bytes(),'text/javascript; charset=utf-8')
    snapshot['/analysis.js']=((WEB/'analysis.js').read_bytes(),'text/javascript; charset=utf-8')
    snapshot['/workspace.js']=((WEB/'workspace.js').read_bytes(),'text/javascript; charset=utf-8')
    snapshot['/workspace.css']=((WEB/'workspace.css').read_bytes(),'text/css; charset=utf-8')
    return MappingProxyType(snapshot)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        port = self.server.server_address[1]
        if self.headers.get_all('Host') not in ([f'127.0.0.1:{port}'], [f'localhost:{port}']):
            self.send_error(403)
            return
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith('/materials/') and getattr(self.server,'material_scores',None) is not None:
            self.server.material_scores.respond(self,self.path[len('/materials'):],prefix='/materials')
            return
        item = self.server.snapshot.get(self.path)
        if item is None:
            self.send_error(404)
            return
        data, mime = item
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)


def create_server(baseline, boundary, port=8765, rectification=None, edges=None, topology=None, measurements=None, measurement_models=None, perimeter=None, assembly=None, path_assessment=None, working_area=None, analysis_run=None, materials=None, scores=None, separation=None, regions=None, region_report=None, portraits=None):
    snapshot = snapshot_files(baseline.resolve(strict=True), boundary.resolve(strict=True), rectification.resolve(strict=True) if rectification is not None else None, edges.resolve(strict=True) if edges is not None else None, topology.resolve(strict=True) if topology is not None else None, measurements.resolve(strict=True) if measurements is not None else None, measurement_models.resolve(strict=True) if measurement_models is not None else None, perimeter.resolve(strict=True) if perimeter is not None else None, assembly.resolve(strict=True) if assembly is not None else None, path_assessment.resolve(strict=True) if path_assessment is not None else None, working_area.resolve(strict=True) if working_area is not None else None)
    sys.path.insert(0,str(WEB.parent/'Cadastral'))
    from run_contract import STAGES, inventory_for
    packages=dict(rectification=rectification,edges=edges,topology=topology,measurements=measurements,
                  **{'measurement-models':measurement_models,'perimeter':perimeter,'assembly':assembly,
                     'path-assessment':path_assessment,'working-area':working_area,'materials':materials,'scores':scores,'separation':separation,'regions':regions,'region-report':region_report})
    snapshot=dict(snapshot)
    source_hashes=json.loads(snapshot['/boundary-manifest.json'][0])['sourceHashes']
    if analysis_run is not None:
        inventory,receipt=inventory_for(analysis_run,baseline,boundary,packages)
        inventory['runReceipt']=True
        snapshot['/analysis-run.json']=(receipt,'application/json')
    else:
        inventory={'schemaVersion':1,'stages':{name:{'state':'available' if packages[name] is not None else 'not-loaded'} for name in STAGES}}
    resources=ExitStack()
    try:
        material_scores=None
        if materials is not None or scores is not None or separation is not None or regions is not None:
            sys.path.insert(0,str(WEB.parent/'AppleMaterials'))
            from evidence import read_manifest, snapshot as admitted_snapshot, require
        if materials is not None:
            m=read_manifest(materials)
            require(m.get('schema')=='apple_dms_materials_v1' and m.get('source_sha256')==source_hashes.get('browser-viewer/original.png'),'Material source lineage mismatch')
            root=resources.enter_context(admitted_snapshot(materials,m,list(m['artifacts'])))
            for name in ('labels.png','materials.png','overlay.png'):
                snapshot['/material-'+name]=((root/name).read_bytes(),'image/png')
            snapshot['/material-manifest.json']=((root/'manifest.json').read_bytes(),'application/json')
        if scores is not None:
            from serve_scores import ScoreDataset
            geometry=json.loads(snapshot['/manifest.json'][0])['derivation']['id1Geometry']
            material_scores=ScoreDataset(scores,resources,source_hashes.get('browser-viewer/original.png'),
                                         (geometry['sourcePixelWidth'],geometry['sourcePixelHeight']))
            if materials is not None:
                from serve_scores import verify_material_lineage
                verify_material_lineage(material_scores.manifest,snapshot['/material-manifest.json'][0])
        if separation is not None:
            if scores is None or working_area is None:raise ValueError('Separation requires scores and working area')
            from launch import admit_separation
            admit_separation({'scores':scores,'working-area':working_area,'separation':separation})
            report=read_manifest(separation,'assessment.json')
            root=resources.enter_context(admitted_snapshot(separation,report,list(report['artifacts']),manifest_name='assessment.json'))
            for name in list(report['artifacts'])+['assessment.json']:
                mime='text/html; charset=utf-8' if name.endswith('.html') else 'application/json' if name.endswith('.json') else 'image/jpeg' if name.endswith('.jpg') else 'image/png' if name.endswith('.png') else 'application/octet-stream'
                snapshot['/separation/'+name]=((root/name).read_bytes(),mime)
        if regions is not None:
            m=read_manifest(regions)
            require(m.get('type')=='id_cadastral_region_experiment' and m.get('sourceHashes')==source_hashes,'Region source lineage mismatch')
            root=resources.enter_context(admitted_snapshot(regions,m,list(m['artifacts'])))
            for name in list(m['artifacts'])+['manifest.json']:
                mime='image/png' if name.endswith('.png') else 'application/json' if name.endswith('.json') else 'application/octet-stream'
                snapshot['/regions/'+name]=((root/name).read_bytes(),mime)
        if region_report is not None:
            if regions is None or analysis_run is None:raise ValueError('Region report requires its prepared run and region package')
            payload=(region_report/'report.html').read_bytes()
            receipt=json.loads(snapshot['/analysis-run.json'][0])
            if hashlib.sha256(payload).hexdigest()!=receipt['stages']['region-report']['entrySHA256']:raise ValueError('Region report changed during admission')
            snapshot['/region-report/report.html']=(payload,'text/html; charset=utf-8')
        if portraits is not None:
            from PortraitRegion.viewer import snapshot as portrait_snapshot
            if edges is None:raise ValueError('Portrait measurements require their edge package')
            snapshot.update(portrait_snapshot(portraits,source_hashes,hashlib.sha256(snapshot['/edges-manifest.json'][0]).hexdigest()))
        snapshot['/portrait-config.json']=(json.dumps({'available':portraits is not None}).encode(),'application/json')
        snapshot['/portraits.js']=((WEB/'portraits.js').read_bytes(),'text/javascript; charset=utf-8')
        snapshot['/analysis-inventory.json']=(json.dumps(inventory,allow_nan=False).encode(),'application/json')
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except BaseException:
        resources.close();raise
    server.snapshot = MappingProxyType(snapshot)
    server.material_scores=material_scores
    close=server.server_close
    def close_resources():
        try:close()
        finally:resources.close()
    server.server_close=close_resources
    return server


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True, type=Path, help='Baseline directory')
    parser.add_argument('--boundary', required=True, type=Path, help='Versioned boundary dataset directory')
    parser.add_argument('--rectification', type=Path, help='Optional boundary-derived rectification package')
    parser.add_argument('--edges', type=Path, help='Optional native edge candidate package')
    parser.add_argument('--topology', type=Path, help='Optional native edge topology package')
    parser.add_argument('--measurements', type=Path, help='Complete source/rectified scanline measurements')
    parser.add_argument('--measurement-models', type=Path, help='Separate post-measurement radius and line models')
    parser.add_argument('--perimeter', type=Path, help='Native perimeter candidate and evidence package')
    parser.add_argument('--assembly', type=Path, help='Assembled observed paths')
    parser.add_argument('--path-assessment', type=Path, help='Color and spatial evidence linked to assembled paths')
    parser.add_argument('--working-area', type=Path, help='Interior working dataset')
    for name in ('analysis-run','materials','scores','separation','regions','region-report','portraits'):
        parser.add_argument('--'+name,type=Path)
    parser.add_argument('--port', type=int, default=8765, help='Loopback HTTP port (1–65535)')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    return args


if __name__ == '__main__':
    args = parse_args()
    try:
        with create_server(args.baseline, args.boundary, args.port, args.rectification, args.edges, args.topology, args.measurements, args.measurement_models, args.perimeter, args.assembly, args.path_assessment, args.working_area, args.analysis_run, args.materials, args.scores, args.separation, args.regions, args.region_report, args.portraits) as server:
            print(f'ID Cadastral: http://127.0.0.1:{args.port}', flush=True)
            server.serve_forever()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f'Cannot serve dataset: {error}') from error
