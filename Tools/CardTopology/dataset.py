"""Immutable topology snapshot admission."""
import io
import sys
from pathlib import Path
import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from CardEdges.dataset import digest
from CardBoundary.json_contract import strict_json
ARRAYS={'path_points':'<f8','path_offsets':'<i8','path_nodes':'<i8','path_components':'<i4','nodes':'<f8','degrees':'<i4','node_components':'<i4','path_source_segments':'<i8'}
NAMES=tuple(key+'.npy' for key in ARRAYS)+('regions.geojson','topology.json','cuts.wkb','dangles.wkb','invalid.wkb')

def validate_files(files,source_hashes=None,edge_manifest_hash=None):
    m=strict_json(files['manifest.json'])
    if type(m.get('schemaVersion')) is not int or m.get('schemaVersion')!=1 or m.get('type')!='id_cadastral_edge_topology':raise ValueError('Unsupported topology')
    if source_hashes is not None and m['sourceHashes']!=source_hashes:raise ValueError('Source mismatch')
    if edge_manifest_hash is not None and m['edgeManifestSHA256']!=edge_manifest_hash:raise ValueError('Edge lineage mismatch')
    if m.get('method') != {'noding':'shapely.node','components':'scipy.sparse.csgraph.connected_components','faces':'shapely.polygonize_full','intersectionPolicy':'exact_geometric','gapBridging':False,'snapping':False,'simplification':False,'downsampling':False}:raise ValueError('Unsupported topology method')
    if set(m['artifacts'])!=set(NAMES):raise ValueError('Unexpected topology artifacts')
    for name in NAMES:
        if m['artifacts'][name]!={'sha256':digest(files[name]),'bytes':len(files[name])}:raise ValueError('Topology artifact mismatch: '+name)
    c=m['coordinateSystem'];w,h=c['width'],c['height']
    if type(w)is not int or type(h)is not int or min(w,h)<1 or c!={'type':'image_pixel_indices','origin':'top_left','xDirection':'right','yDirection':'down','width':w,'height':h,'pixelCenterOffset':[.5,.5]}:raise ValueError('Coordinate contract')
    arrays={}
    for key,dtype in ARRAYS.items():
        a=np.load(io.BytesIO(files[key+'.npy']),allow_pickle=False)
        if a.dtype!=np.dtype(dtype) or not np.isfinite(a).all():raise ValueError('Invalid topology array '+key)
        arrays[key]=a
    p,o,n,links=arrays['path_points'],arrays['path_offsets'],arrays['nodes'],arrays['path_nodes']
    for a in(p,n):
        if a.ndim!=2 or a.shape[1]!=2 or np.any(a<0) or np.any(a[:,0]>=w) or np.any(a[:,1]>=h):raise ValueError('Invalid coordinates')
    if o.ndim!=1 or len(o)<1 or o[0]!=0 or o[-1]!=len(p) or np.any(o<0) or np.any(o>len(p)) or np.any(np.diff(o)<2):raise ValueError('Invalid offsets')
    k=len(o)-1
    if links.shape!=(k,2) or np.any(links<0) or np.any(links>=len(n)):raise ValueError('Invalid path links')
    if not np.array_equal(n[links[:,0]],p[o[:-1]]) or not np.array_equal(n[links[:,1]],p[o[1:]-1]):raise ValueError('Path endpoint mismatch')
    d,labels,components=arrays['degrees'],arrays['node_components'],arrays['path_components']
    if d.shape!=(len(n),) or not np.array_equal(d,np.bincount(links.ravel(),minlength=len(n))):raise ValueError('Invalid degrees')
    if labels.shape!=(len(n),) or components.shape!=(k,) or np.any(labels<0) or not np.array_equal(components,labels[links[:,0]]) or not np.array_equal(components,labels[links[:,1]]):raise ValueError('Invalid components')
    sparse=coo_matrix((np.ones(k,dtype=np.uint8),(links[:,0],links[:,1])),shape=(len(n),len(n))).tocsr()
    component_count, expected_labels=connected_components(sparse,directed=False)
    if not np.array_equal(labels,expected_labels):raise ValueError('Graph connectivity mismatch')
    prov=arrays['path_source_segments']
    if prov.ndim!=2 or prov.shape[1]!=2 or np.any(prov<0) or np.any(prov[:,0]>=k) or np.any(prov[:,1]>=m['summary']['inputPointCount']-1):raise ValueError('Invalid provenance')
    summary=strict_json(files['topology.json'])
    if summary!=m['summary'] or summary['nodeCount']!=len(n) or summary['pathCount']!=k:raise ValueError('Invalid summary')
    expected_counts={'nodeCount':len(n),'pathCount':k,'planarComponentCount':int(component_count),'endpointCount':int(np.sum(d==1)),'junctionCount':int(np.sum(d>=3)),'isolatedNodeCount':int(np.sum(d==0)),'cycleRank':int(k-len(n)+component_count)}
    if any(summary.get(key)!=value for key,value in expected_counts.items()):raise ValueError('Graph summary mismatch')
    for name in ('cuts','dangles','invalid'):
        g=shapely.from_wkb(files[name+'.wkb'])
        count_key={'cuts':'cutPathCount','dangles':'danglePathCount','invalid':'invalidRingCount'}[name]
        if g.geom_type!='GeometryCollection' or len(g.geoms)!=summary[count_key]:raise ValueError('Invalid polygonization leftovers')
        cpoints=shapely.get_coordinates(g)
        if not np.isfinite(cpoints).all() or np.any(cpoints<0) or np.any(cpoints[:,0]>=w) or np.any(cpoints[:,1]>=h):raise ValueError('Invalid leftover coordinates')
    regions=strict_json(files['regions.geojson'])
    if regions.get('type')!='FeatureCollection' or len(regions['features'])!=summary['closedRegionCount']:raise ValueError('Invalid regions')
    for i,f in enumerate(regions['features']):
        if f['type']!='Feature' or f['properties']['regionId']!=i or f['geometry']['type']!='Polygon':raise ValueError('Invalid region')
        component=f['properties']['componentId']
        if type(component)is not int or not 0<=component<component_count:raise ValueError('Region component mismatch')
        for ring in f['geometry']['coordinates']:
            coords=np.asarray(ring,dtype=float)
            if coords.ndim!=2 or coords.shape[1]!=2 or len(coords)<4 or not np.isfinite(coords).all() or not np.array_equal(coords[0],coords[-1]) or np.any(coords<0) or np.any(coords[:,0]>=w) or np.any(coords[:,1]>=h):raise ValueError('Invalid region coordinates')
        poly=shapely.geometry.shape(f['geometry'])
        if not poly.is_valid or poly.is_empty or poly.area!=f['properties']['areaSourcePixels2']:raise ValueError('Invalid region geometry')
    for a in arrays.values():a.setflags(write=False)
    return m,arrays,regions,files

def load_dataset(path,source_hashes=None,edge_manifest_hash=None):
    path=Path(path)
    if path.is_symlink() or any((path/n).is_symlink() for n in ('manifest.json',*NAMES)):raise ValueError('Symlink artifacts')
    return validate_files({n:(path/n).read_bytes() for n in ('manifest.json',*NAMES)},source_hashes,edge_manifest_hash)
