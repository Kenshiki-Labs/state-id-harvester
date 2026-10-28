"""Run color/spatial assessment against immutable assembly and native evidence."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from CardEdges.dataset import load_dataset as load_edges
from PerimeterCandidates.dataset import load_dataset,encode,digest
from CardBoundary.publication import publish_directory


def run(edges,candidates,assembly,out):
    implementation={n:digest(Path(__file__).with_name(n).read_bytes()) for n in ('assess_paths.py','path_assessment_run.py')}
    from PerimeterCandidates.assess_paths import assess_paths
    em,points,offsets,_,ef=load_edges(edges)
    cm,cf=load_dataset(candidates,em['sourceHashes'],digest(ef['manifest.json']))
    if assembly.is_symlink() or any((assembly/n).is_symlink() for n in ('manifest.json','assembly.json')):
        raise ValueError('Assembly symlink')
    raw=(assembly/'manifest.json').read_bytes();am=json.loads(raw)
    ar=(assembly/'assembly.json').read_bytes()
    if am.get('type')!='id_cadastral_path_assembly' or am.get('schemaVersion')!=1 or am['candidateManifestSHA256']!=digest(cf['manifest.json']) or am['edgeManifestSHA256']!=digest(ef['manifest.json']) or am['sourceHashes']!=em['sourceHashes']:
        raise ValueError('Assembly lineage mismatch')
    if am['artifacts']!={'assembly.json':{'sha256':digest(ar),'bytes':len(ar)}}:
        raise ValueError('Assembly hash mismatch')
    c=json.loads(cf['candidates.json']);a=json.loads(ar);e=json.loads(cf['evidence.json'])
    result=assess_paths(points,c,a,e)
    files={'assessment.json':encode(result)}
    manifest={'schemaVersion':1,'type':'id_cadastral_path_assessment',
              'sourceHashes':em['sourceHashes'],'assemblyManifestSHA256':digest(raw),
              'candidateManifestSHA256':digest(cf['manifest.json']),
              'edgeManifestSHA256':digest(ef['manifest.json']),
              'implementation':implementation,
              'artifacts':{n:{'sha256':digest(v),'bytes':len(v)} for n,v in files.items()}}
    files['manifest.json']=encode(manifest)
    for root,inputs in [(edges,ef),(candidates,cf),(assembly,{'manifest.json':raw,'assembly.json':ar})]:
        if any((root/n).read_bytes()!=v for n,v in inputs.items()):raise ValueError('Assessment input changed')
    if any(digest(Path(__file__).with_name(n).read_bytes())!=h for n,h in implementation.items()):raise ValueError('Assessment implementation changed during execution')
    publish_directory(out,files)
    print(json.dumps(result.get('summary',{})),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('edges','candidates','assembly','out'):p.add_argument(name,type=Path)
    a=p.parse_args();run(a.edges,a.candidates,a.assembly,a.out)
