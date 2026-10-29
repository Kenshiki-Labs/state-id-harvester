"""Fixed portrait routes, bound to the same native scene and edge observations."""
import json
import math
from pathlib import Path
from CardBoundary.json_contract import strict_json,require
from PortraitRegion.prepare import verified


def snapshot(root,source_hashes,edge_hash):
    root=Path(root);require(not root.is_symlink(),'Portrait package symlink')
    path=root/'manifest.json';require(not path.is_symlink(),'Portrait manifest symlink')
    raw=path.read_bytes();m=strict_json(raw)
    require(m.get('schemaVersion')==1 and m.get('type')=='retained_portrait_regions','Portrait schema mismatch')
    require(m['sourceHashes']==source_hashes and m['edgeManifestSHA256']==edge_hash,'Portrait scene/edge lineage mismatch')
    routes={'/portraits/manifest.json':(raw,'application/json')}
    for name,a in m['artifacts'].items():
        data=verified(root,name,a['sha256']);require(len(data)==a['bytes'],'Portrait byte count mismatch')
        routes['/portraits/'+name]=(data,'image/png' if name.endswith('.png') else 'application/json')
    for c in m['candidates']:
        require('/portraits/'+c['image'] in routes,'Missing portrait image')
        ring=c['sourcePolygon'];require(len(ring)==5 and ring[0]==ring[-1] and all(len(p)==2 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in p) for p in ring),'Invalid portrait polygon')
    require(path.read_bytes()==raw,'Portrait package changed during admission')
    return routes
