"""Exact planar topology of retained native EdgeDrawing chains."""
import argparse
import io
import sys
import time
from pathlib import Path
import numpy as np
import scipy
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import shapely
from shapely.geometry import mapping
from shapely.ops import split
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from CardEdges.dataset import load_dataset as load_edges, digest, json_bytes, npy_bytes
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from publication import publish_directory


def graph(endpoints, extra_points=None):
    flat = endpoints.reshape(-1, 2)
    if extra_points is not None:
        flat = np.concatenate((flat, extra_points))
    nodes, inverse = np.unique(flat, axis=0, return_inverse=True)
    links = inverse[:len(endpoints)*2].reshape(-1, 2)
    sparse = coo_matrix((np.ones(len(links), dtype=np.uint8), (links[:,0], links[:,1])), shape=(len(nodes), len(nodes))).tocsr()
    count, labels = connected_components(sparse, directed=False)
    degrees = np.bincount(links.ravel(), minlength=len(nodes)).astype('<i4')
    return nodes, links, degrees, labels, count


def audit(points, offsets):
    chains = [points[a:b] for a,b in zip(offsets[:-1], offsets[1:])]
    if any(len(p) == 0 for p in chains):
        raise ValueError('Expected nonempty chains')
    if not np.isfinite(points).all() or any(np.any(np.abs(np.diff(p, axis=0)) > 1) for p in chains):
        raise ValueError('Expected native neighboring chain points')
    starts = np.concatenate([np.arange(a,b-1) for a,b in zip(offsets[:-1], offsets[1:])]).astype(np.int64) if chains else np.empty(0,dtype=np.int64)
    valid = np.any(points[starts] != points[starts+1], axis=1)
    starts = starts[valid]
    original_segments = np.stack((points[starts],points[starts+1]), axis=1)
    # Exact-coordinate graph only; duplicate undirected segments do not raise degree.
    original_nodes, inv = np.unique(points, axis=0, return_inverse=True)
    original_links = np.sort(np.column_stack((inv[starts], inv[starts+1])), axis=1)
    original_links = np.unique(original_links, axis=0)
    sparse = coo_matrix((np.ones(len(original_links),dtype=np.uint8),(original_links[:,0],original_links[:,1])),shape=(len(original_nodes),len(original_nodes))).tocsr()
    shared_count, _ = connected_components(sparse,directed=False)
    linear = [shapely.LineString(p) for p in chains if len(p)>1 and np.any(p != p[0])]
    noded = shapely.node(shapely.MultiLineString(linear))
    paths = shapely.get_parts(noded)
    singleton = np.array([p[0] for p in chains if len(p)==1 or np.all(p==p[0])],dtype=float).reshape(-1,2)
    # GEOS node ignores points. Exact singleton contacts must split linework
    # before its endpoint graph is built; split neither snaps nor extends lines.
    if len(singleton) and len(paths):
        hits = shapely.STRtree(paths).query(shapely.points(singleton),predicate='intersects')
        replacements = {}
        for path_id in np.unique(hits[1]):
            contacts = singleton[hits[0,hits[1]==path_id]]
            replacements[int(path_id)] = list(shapely.get_parts(split(paths[path_id],shapely.MultiPoint(contacts))))
        paths = np.array([piece for i,path in enumerate(paths) for piece in replacements.get(i,[path])],dtype=object)
    coords, idx = shapely.get_coordinates(paths, return_index=True)
    sizes = np.bincount(idx, minlength=len(paths))
    path_offsets = np.r_[0,np.cumsum(sizes)].astype('<i8')
    endpoints = np.stack((coords[path_offsets[:-1]],coords[path_offsets[1:]-1]),axis=1)
    # Retain singleton original chains as isolated graph nodes.
    nodes, links, degrees, labels, count = graph(endpoints,singleton)
    components = labels[links[:,0]]
    tree = shapely.STRtree(paths)
    # Quarter and three-quarter points cover both halves of crossing diagonals.
    # Exact intersects, no proximity joins. Every source segment is accounted for.
    probes = np.concatenate((.75*original_segments[:,0]+.25*original_segments[:,1],.25*original_segments[:,0]+.75*original_segments[:,1]))
    hits = tree.query(shapely.points(probes),predicate='intersects')
    source_segment = hits[0] % len(starts) if len(starts) else np.empty(0,dtype=np.int64)
    provenance = np.unique(np.column_stack((hits[1],starts[source_segment])),axis=0).astype('<i8')
    if len(np.unique(provenance[:,1])) != len(starts):
        raise ValueError('Unmapped source segment')
    polygons,cuts,dangles,invalid = shapely.polygonize_full(paths)
    features=[]
    for i,p in enumerate(shapely.get_parts(polygons)):
        vertex = shapely.Point(p.exterior.coords[0])
        matches=tree.query(vertex,predicate='intersects')
        component=int(components[matches[0]])
        features.append({'type':'Feature','properties':{'regionId':i,'componentId':component,'areaSourcePixels2':float(p.area)},'geometry':mapping(p)})
    summary={'inputChainCount':len(chains),'inputPointCount':len(points),'originalClosedChainCount':sum(len(p)>2 and np.array_equal(p[0],p[-1]) for p in chains),'sourceSegmentCount':len(starts),'uniqueSourceSegmentCount':len(original_links),'sharedVertexComponentCount':int(shared_count),'planarComponentCount':int(count),'nodeCount':len(nodes),'pathCount':len(paths),'endpointCount':int(np.sum(degrees==1)),'junctionCount':int(np.sum(degrees>=3)),'isolatedNodeCount':int(np.sum(degrees==0)),'introducedIntersectionNodeCount':int(np.sum(np.any(nodes != np.floor(nodes),axis=1))),'cycleRank':int(len(paths)-len(nodes)+count),'closedRegionCount':len(features),'cutPathCount':len(shapely.get_parts(cuts)),'danglePathCount':len(shapely.get_parts(dangles)),'invalidRingCount':len(shapely.get_parts(invalid)),'zeroLengthSourceSegmentCount':int(np.sum(~valid))}
    arrays={'path_points':coords.astype('<f8'),'path_offsets':path_offsets,'path_nodes':links.astype('<i8'),'path_components':components.astype('<i4'),'nodes':nodes.astype('<f8'),'degrees':degrees,'node_components':labels.astype('<i4'),'path_source_segments':provenance}
    return arrays,{'type':'FeatureCollection','features':features},summary,{'cuts':cuts,'dangles':dangles,'invalid':invalid}


def run(edge_path,out):
    started=time.monotonic()
    manifest,points,offsets,_,inputs=load_edges(edge_path)
    source_code={p.name:digest(p.read_bytes()) for p in (Path(__file__),Path(__file__).with_name('dataset.py'))}
    arrays,regions,summary,extras=audit(points,offsets)
    files={key+'.npy':npy_bytes(value) for key,value in arrays.items()}
    files['regions.geojson']=json_bytes(regions)
    files['topology.json']=json_bytes(summary)
    for key,value in extras.items():
        files[key+'.wkb']=shapely.to_wkb(value)
    record={'schemaVersion':1,'type':'id_cadastral_edge_topology','coordinateSystem':manifest['coordinateSystem'],'sourceHashes':manifest['sourceHashes'],'edgeManifestSHA256':digest(inputs['manifest.json']),'inputArtifacts':{k:digest(v) for k,v in inputs.items()},'method':{'noding':'shapely.node','components':'scipy.sparse.csgraph.connected_components','faces':'shapely.polygonize_full','intersectionPolicy':'exact_geometric','gapBridging':False,'snapping':False,'simplification':False,'downsampling':False},'implementation':{'shapely':shapely.__version__,'geos':shapely.geos_version_string,'scipy':scipy.__version__,'numpy':np.__version__,'sourceCodeSHA256':source_code},'summary':summary,'elapsedSeconds':time.monotonic()-started,'artifacts':{k:{'sha256':digest(v),'bytes':len(v)} for k,v in files.items()}}
    files['manifest.json']=json_bytes(record)
    if any((Path(edge_path)/name).read_bytes()!=data for name,data in inputs.items()):
        raise ValueError('Input changed during audit')
    from CardTopology.dataset import validate_files
    validate_files(files,manifest['sourceHashes'],digest(inputs['manifest.json']))
    publish_directory(Path(out),files)
    print(record['summary'],flush=True)
    return record

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('edges',type=Path);parser.add_argument('out',type=Path)
    args=parser.parse_args();run(args.edges,args.out)
