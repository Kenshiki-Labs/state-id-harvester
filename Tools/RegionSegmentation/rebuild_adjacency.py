"""Re-evaluate retained partitions with exact side-sharing topology."""
import argparse
from pathlib import Path
import tempfile
import time
import numpy as np
from experiment import features, load_native, verify_unchanged, json_bytes, digest, publish_directory
from adjacency import graph_records
from json_contract import strict_json


def rebuild(base,run,out):
    data=(run/'manifest.json').read_bytes();manifest=strict_json(data)
    rgb,_,hashes=load_native(base)
    if hashes!=manifest['sourceHashes']:raise ValueError('Source mismatch')
    _,lab,texture,_=features(rgb,manifest['nominalScale']['meanPixelsPerMM'])
    feature_file=run/'elevations.npz'
    if digest(feature_file.read_bytes())!=manifest['artifacts']['elevations.npz']['sha256']:raise ValueError('Feature mismatch')
    elevation=np.load(feature_file,allow_pickle=False)
    records=[];files={};started=time.monotonic()
    for condition in manifest['conditions']:
        name=condition['condition'];filename=name+'-labels.npz';payload=(run/filename).read_bytes()
        if digest(payload)!=manifest['artifacts'][filename]['sha256']:raise ValueError('Labels mismatch')
        print('Exact adjacency: '+name,flush=True)
        with np.load(run/filename,allow_pickle=False) as archive:labels=archive['labels']
        graph=graph_records(labels,elevation[condition['cueMode']],lab,texture)
        filename=name+'-regions.json';files[filename]=json_bytes(graph)
        records.append({'condition':name,'regionCount':len(graph['regions']),'adjacencyCount':len(graph['adjacencies'])})
        print(records[-1],flush=True)
    verify_unchanged(base,hashes)
    result={'schemaVersion':1,'sourceRunManifestSHA256':digest(data),'sourceHashes':hashes,
      'method':'skimage_rag_four_connected_exact_interfaces','conditions':records,
      'replaces':'rag_boundary_adjacency_statistics','runtimeSeconds':time.monotonic()-started,
      'scriptSHA256':digest(Path(__file__).read_bytes()),'adjacencyScriptSHA256':digest(Path(__file__).with_name('adjacency.py').read_bytes()),
      'artifacts':{name:{'sha256':digest(value)} for name,value in files.items()}}
    files['manifest.json']=json_bytes(result);publish_directory(out,files)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args();rebuild(a.baseline,a.run,a.output)
