#!/usr/bin/env python3
"""Discover and assess native perimeter alternatives from explicit input datasets."""
import argparse
import io
import json
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'CardBoundary'))
from native_input import load_native, verify_unchanged
from publication import publish_directory
from CardEdges.dataset import load_dataset as load_edges
from PerimeterCandidates.discovery import discover
from PerimeterCandidates.evidence import assess_surroundings
from PerimeterCandidates.dataset import encode, digest, load_dataset


def relationships(candidates):
    by_chain = {}
    for candidate in candidates:
        by_chain.setdefault(candidate['sourceChainIndex'], []).append(candidate)
    links = []
    for chain, runs in by_chain.items():
        for i, a in enumerate(runs):
            for b in runs[i+1:]:
                if a['sideIndex'] == b['sideIndex']:
                    continue
                lo=max(a['sourcePointStart'],b['sourcePointStart'])
                hi=min(a['sourcePointStopExclusive'],b['sourcePointStopExclusive'])
                links.append({'candidateIds':[a['candidateId'],b['candidateId']],
                              'sourceChainIndex':chain,'sharedPointCount':max(0,hi-lo),
                              'relationship':'shared_source_points' if hi>lo else 'same_source_chain',
                              'impliesPhysicalPerimeter':False})
    return {'summary':{'crossSideRelationships':len(links),
                       'sharedPointRelationships':sum(v['sharedPointCount']>0 for v in links),
                       'closedPhysicalPerimetersEstablished':0,
                       'status':'unresolved',
                       'reason':'Connectivity and appearance do not establish which transition is the physical edge.'},
            'links':links}


def run(base, edge_dir, out, config_path):
    if out.exists():
        raise FileExistsError(out)
    rgb, meta, hashes = load_native(base)
    em, points, offsets, _, edge_files = load_edges(edge_dir, hashes)
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    if config.get('schemaVersion') != 1:
        raise ValueError('Unsupported configuration')
    quad = [[p['x'],p['y']] for p in meta['derivation']['id1Geometry']['sourceCorners']]
    discovery = discover(points, offsets, quad, config['corridorFraction'])
    print('Discovered', len(discovery['candidates']), 'native runs', flush=True)
    evidence = assess_surroundings(rgb, points, discovery['candidates'])
    print('Surrounding evidence complete', flush=True)
    candidates = discovery['candidates']
    for candidate in candidates:
        candidate['points'] = points[candidate['sourcePointStart']:candidate['sourcePointStopExclusive']].tolist()
    array_stream=io.BytesIO()
    np.savez_compressed(array_stream, **discovery.pop('arrays'))
    files={'candidates.json':encode(discovery),'evidence.json':encode(evidence),
           'relationships.json':encode(relationships(candidates)),
           'membership.npz':array_stream.getvalue()}
    manifest={'schemaVersion':1,'type':'id_cadastral_perimeter_candidates',
              'sourceHashes':hashes,'edgeManifestSHA256':digest(edge_files['manifest.json']),
              'configuration':config,'configurationSHA256':digest(config_raw),
              'coordinateSystem':em['coordinateSystem'], 'method':discovery['method'],
              'summary':{**discovery['summary'], 'evidence':evidence['summary']},
              'physicalSelection':{'status':'unresolved','selectedCandidateIds':[]},
              'implementation':{p.name:digest(p.read_bytes()) for p in HERE.glob('*.py')},
              'artifacts':{n:{'sha256':digest(v),'bytes':len(v)} for n,v in files.items()}}
    files['manifest.json']=encode(manifest)
    verify_unchanged(base, hashes)
    for name, data in edge_files.items():
        if (edge_dir/name).read_bytes()!=data:
            raise ValueError('Edge inputs changed during analysis')
    publish_directory(out,files)
    load_dataset(out,hashes,digest(edge_files['manifest.json']))
    print(json.dumps({k:v for k,v in manifest['summary'].items() if k!='sharedSourceChainsAcrossSides'}), flush=True)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('baseline',type=Path)
    parser.add_argument('edges',type=Path)
    parser.add_argument('out',type=Path)
    parser.add_argument('--config',type=Path,default=HERE/'config.json')
    args=parser.parse_args()
    run(args.baseline,args.edges,args.out,args.config)
