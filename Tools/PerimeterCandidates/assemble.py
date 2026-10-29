"""Assemble exact native linework into maximal paths; branches remain explicit."""
import argparse
import io
import json
from pathlib import Path
import sys
import numpy as np
import shapely
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from CardTopology.audit import audit, graph
from CardEdges.dataset import load_dataset as load_edges
from PerimeterCandidates.dataset import load_dataset, encode, digest
from CardBoundary.publication import publish_directory


def assemble(points, offsets, candidates):
    # Candidate ranges overlap at corners. Keep their union without creating a
    # segment between separate ranges or separate original chains.
    keep=np.zeros(len(points),bool)
    for c in candidates:
        a,b=c['sourcePointStart'],c['sourcePointStopExclusive']
        chain=c['sourceChainIndex']
        if not 0<=chain<len(offsets)-1 or not offsets[chain]<=a<b<=offsets[chain+1]:
            raise ValueError('Candidate outside original chain')
        if not np.array_equal(points[a:b],np.asarray(c['points'])):
            raise ValueError('Candidate geometry differs from source')
        keep[a:b]=True
    source_indices=[];parts=[];compact_offsets=[0]
    for a,b in zip(offsets[:-1],offsets[1:]):
        k=keep[a:b]
        starts=np.flatnonzero(k & np.r_[True,~k[:-1]]) if len(k) else []
        ends=np.flatnonzero(k & np.r_[~k[1:],True])+1 if len(k) else []
        for start,end in zip(starts,ends):
            ids=np.arange(a+start,a+end)
            source_indices.extend(ids.tolist());parts.append(points[ids])
            compact_offsets.append(compact_offsets[-1]+len(ids))
    if not parts:
        return {'paths':[],'nodes':[],'isolatedPoints':[],'summary':{'pathCount':0,'status':'no_candidates'}}
    compact=np.concatenate(parts);indices=np.asarray(source_indices)
    arr,_,topology,_=audit(compact,np.asarray(compact_offsets))
    lines=[shapely.LineString(arr['path_points'][a:b]) for a,b in zip(arr['path_offsets'][:-1],arr['path_offsets'][1:])]
    merged=list(shapely.get_parts(shapely.line_merge(shapely.MultiLineString(lines))))
    # Geometry equality is required; line_merge may reverse traversal but must
    # not remove dents, bridge gaps or add observations.
    before=shapely.MultiLineString(lines);after=shapely.MultiLineString(merged)
    if not shapely.symmetric_difference(before,after).is_empty:
        raise ValueError('Assembly changed observed linework')
    merged.sort(key=lambda g:(-g.length,tuple(g.bounds),tuple(g.coords[0])))
    endpoints=np.array([[g.coords[0],g.coords[-1]] for g in merged]).reshape(-1,2,2)
    isolated=arr['nodes'][arr['degrees']==0]
    nodes,links,degrees,components,count=graph(endpoints,isolated)
    starts=np.concatenate([np.arange(a,b-1) for a,b in zip(compact_offsets[:-1],compact_offsets[1:])])
    starts=starts[np.any(compact[starts]!=compact[starts+1],axis=1)]
    probes=np.concatenate((.75*compact[starts]+.25*compact[starts+1],.25*compact[starts]+.75*compact[starts+1]))
    hits=shapely.STRtree(merged).query(shapely.points(probes),predicate='intersects')
    provenance=[set() for _ in merged]
    for path,segment in zip(hits[1],hits[0]%len(starts) if len(starts) else []):
        provenance[int(path)].add(int(indices[starts[segment]]))
    covered=set().union(*provenance) if provenance else set()
    if covered != set(indices[starts].tolist()):
        raise ValueError('Missing source segments')
    candidate_segments={}
    for c in candidates:
        for index in range(c['sourcePointStart'],c['sourcePointStopExclusive']-1):
            candidate_segments.setdefault(index,set()).add(c['candidateId'])
    candidate_by_id={c['candidateId']:c for c in candidates}
    paths=[];incidence=[[] for _ in nodes]
    for i,g in enumerate(merged):
        for n in links[i]:incidence[n].append(i)
        ids=sorted(set().union(*(candidate_segments.get(s,set()) for s in provenance[i])))
        paths.append({'pathId':i,'points':list(map(list,g.coords)),
                      'nodeIds':links[i].tolist(),'componentId':int(components[links[i,0]]),
                      'closed':bool(g.is_closed),'lengthSourcePixels':float(g.length),
                      'sourceSegmentStartIndices':sorted(provenance[i]),'candidateIds':ids,
                      'sideIndices':sorted({candidate_by_id[c]['sideIndex'] for c in ids})})
    records=[{'nodeId':i,'point':p.tolist(),'degree':int(degrees[i]),
              'kind':'open_end' if degrees[i]==1 else 'branch' if degrees[i]>2 else 'isolated' if degrees[i]==0 else 'cycle_join',
              'incidentPathIds':incidence[i], 'componentId':int(components[i])} for i,p in enumerate(nodes)]
    return {'paths':paths,'nodes':records,'isolatedPoints':isolated.tolist(),
            'summary':{'inputCandidates':len(candidates),'retainedSourcePoints':len(compact),
                       'pathCount':len(paths),'componentCount':int(count),
                       'branchCount':int(sum(degrees>2)),'openEndCount':int(sum(degrees==1)),
                       'closedPathCount':sum(p['closed'] for p in paths),
                       'pathsTouchingMultipleSideCorridors':sum(len(p['sideIndices'])>1 for p in paths),
                       'topologyBeforeMerge':topology,
                       'geometrySymmetricDifferenceEmpty':True,
                       'status':'assembled_observed_paths','physicalSelection':'unresolved'},
            'gapPolicy':'open ends retained; no unsupported endpoint pairing or inserted segment',
            'branchPolicy':'incident paths represent all available continuations; no branch chosen'}


def run(edge_dir,candidate_dir,out):
    em,p,o,_,ef=load_edges(edge_dir)
    cm,cf=load_dataset(candidate_dir,em['sourceHashes'],digest(ef['manifest.json']))
    data=json.loads(cf['candidates.json'])
    result=assemble(p,o,data['candidates'])
    result['prior']=data['prior']
    files={'assembly.json':encode(result)}
    manifest={'schemaVersion':1,'type':'id_cadastral_path_assembly',
              'sourceHashes':em['sourceHashes'],'edgeManifestSHA256':digest(ef['manifest.json']),
              'candidateManifestSHA256':digest(cf['manifest.json']),
              'coordinateSystem':em['coordinateSystem'],
              'method':{'noding':'existing CardTopology.audit','assembly':'shapely.line_merge',
                        'snap':False,'gapBridging':False,'simplification':False,'pathOrder':'descending observed length; not confidence'},
              'implementation':{'shapely':shapely.__version__,'geos':shapely.geos_version_string,'sourceSHA256':digest(Path(__file__).read_bytes())},
              'summary':result['summary'],'artifacts':{n:{'sha256':digest(v),'bytes':len(v)} for n,v in files.items()}}
    for directory,inputs in [(edge_dir,ef),(candidate_dir,cf)]:
        if any((directory/n).read_bytes()!=v for n,v in inputs.items()):raise ValueError('Inputs changed')
    files['manifest.json']=encode(manifest);publish_directory(out,files)
    print(json.dumps(result['summary']),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('edges',type=Path);ap.add_argument('candidates',type=Path);ap.add_argument('out',type=Path)
    a=ap.parse_args();run(a.edges,a.candidates,a.out)
