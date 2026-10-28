"""Complete scanline intersections; no perimeter smoothing or registration fitting."""
import argparse
import io
import sys
from pathlib import Path
import numpy as np
import shapely
from shapely.geometry import shape, LineString
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from CardEdges.dataset import digest, json_bytes, npy_bytes
from CardBoundary.publication import publish_directory
from CardBoundary.json_contract import strict_json
from CardBoundary.validate_dataset import validate_dataset
from PixelViewer.serve import rectification_snapshot


def project(matrix, points):
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    q = np.column_stack((p, np.ones(len(p)))) @ np.asarray(matrix).reshape(3, 3).T
    if not np.isfinite(q).all() or np.any(np.abs(q[:, 2]) < 1e-12):
        raise ValueError('Singular coordinate mapping')
    return q[:, :2] / q[:, 2:]


def parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type in ('Point', 'LineString'):
        return [geometry]
    return [p for g in geometry.geoms for p in parts(g)]


def intersect(poly, a, b, to_source, to_mm):
    """Every connected intersection, including holes, tangent points and overlaps."""
    direction = np.subtract(b, a).astype(float)
    direction /= np.linalg.norm(direction)
    records = []
    for g in parts(shapely.intersection(poly, LineString([a, b]), grid_size=0)):
        p = np.array([g.coords[0], g.coords[-1]], dtype=float)
        if (p[1] - p[0]) @ direction < 0:
            p = p[::-1]
        source, mm = project(to_source, p), project(to_mm, p)
        kind = 1 if g.geom_type == 'Point' else (2 if poly.boundary.covers(g) else 0)
        records.append([*p.ravel(), float(np.linalg.norm(p[1]-p[0])),
                        float(np.linalg.norm(mm[1]-mm[0])), *source.ravel(), kind])
    records.sort(key=lambda r: np.dot(np.array(r[:2])-a, direction))
    return records


def scan(poly, width, height, axis, to_source, to_mm):
    # Integer positions are pixel boundaries; half-integers are pixel centers.
    # Both sets are complete, including the two outer raster boundaries.
    extent = height if axis == 'x' else width
    records, offsets, summary = [], [0], []
    lowx, lowy, highx, highy = poly.bounds
    for twice in range(2*extent+1):
        fixed = twice / 2
        a, b = ([min(-1,lowx-1),fixed],[max(width+1,highx+1),fixed]) if axis=='x' else ([fixed,min(-1,lowy-1)],[fixed,max(height+1,highy+1)])
        pieces = intersect(poly,a,b,to_source,to_mm)
        records.extend(pieces); offsets.append(len(records))
        if pieces:
            ends = np.array([pieces[0][:2],pieces[-1][2:4]])
            mm = project(to_mm,ends)
            span = float(np.linalg.norm(ends[1]-ends[0])); spanmm=float(np.linalg.norm(mm[1]-mm[0]))
        else:
            span=spanmm=0.
        # status codes separate absence, single/multiple spans, tangent and overlap.
        status = 0 if not pieces else (4 if any(p[-1]==2 for p in pieces) else (3 if all(p[-1]==1 for p in pieces) else (1 if len(pieces)==1 else 2)))
        summary.append([fixed,status,len(pieces),span,sum(p[4] for p in pieces),spanmm,sum(p[5] for p in pieces)])
    return {'scans':np.array(summary,dtype='<f8'),'offsets':np.array(offsets,dtype='<i8'),
            'intervals':np.array(records,dtype='<f8').reshape(-1,11)}


def unit_perimeter(geometry):
    values=[]; rings=[]
    for rid,ring in enumerate(geometry['coordinates']):
        for a,b in zip(ring[:-1],ring[1:]):
            a,b=np.array(a),np.array(b);delta=b-a
            length=int(np.abs(delta).sum())
            if length==0 or np.count_nonzero(delta)!=1 or not np.array_equal(delta,np.round(delta)):
                raise ValueError('Expected native pixel-edge polygon')
            values.extend(a+np.arange(length)[:,None]*delta/length);rings.extend([rid]*length)
    return np.array(values,dtype=float),np.array(rings,dtype='<i4')


def run(base,boundary,rectification,out):
    base,boundary,rectification,out=map(Path,(base,boundary,rectification,out))
    admitted=validate_dataset(boundary,base)
    geom_bytes=(boundary/'geometry.json').read_bytes()
    if digest(geom_bytes)!=admitted['boundaryId']:raise ValueError('Boundary changed')
    geometry=strict_json(geom_bytes)
    snap=rectification_snapshot(rectification,admitted,geometry)
    rect_bytes=snap['/rectification-manifest.json'][0];rect=strict_json(rect_bytes)
    transformed=strict_json(snap['/rectification-contour.json'][0])
    ident=np.eye(3);tr=rect['transforms'];o=rect['output'];scale=o['pixelsPerMillimeter'];origin=o['originCardMillimeters']
    rtomm=np.array([[1/scale,0,origin[0]],[0,1/scale,origin[1]],[0,0,1.]])
    cs=admitted['coordinateSystem'];files={};grids={}
    for name,g,w,h,tos,tomm in [('source',geometry,cs['width'],cs['height'],ident,tr['sourceToCardMillimeters']),('rectified',transformed,o['width'],o['height'],tr['rectifiedToSource'],rtomm)]:
        poly=shape(g)
        if not poly.is_valid:raise ValueError('Invalid perimeter')
        grids[name]={'width':w,'height':h}
        for axis in ('x','y'):
            arrays=scan(poly,w,h,axis,tos,tomm)
            for key,value in arrays.items():files[f'{name}-{axis}-{key}.npy']=npy_bytes(value)
    # Record every unit native perimeter vertex before any radius model is run.
    native,ring_ids=unit_perimeter(geometry)
    mm=project(tr['sourceToCardMillimeters'],native);center=np.array([85.6,53.98])/2
    radial=np.column_stack((native,project(tr['sourceToRectified'],native),mm,np.linalg.norm(mm-center,axis=1),ring_ids))
    files['perimeter.npy']=npy_bytes(radial.astype('<f8'))
    diagonals=[];poly=shape(transformed)
    centerpixel=(center-np.array(origin))*scale
    for name,vector in [('top_left_bottom_right',np.array([85.6,53.98])),('bottom_left_top_right',np.array([85.6,-53.98]))]:
        unit=vector/np.linalg.norm(vector); reach=2*max(o['width'],o['height'])
        pieces=intersect(poly,centerpixel-unit*reach,centerpixel+unit*reach,tr['rectifiedToSource'],rtomm)
        endpoints=np.array([p[:2] for p in pieces]+[p[2:4] for p in pieces]).reshape(-1,2)
        mapped=project(rtomm,endpoints)
        signed=(mapped-center)@unit
        negatives=signed[signed<0];positives=signed[signed>0]
        radius=[float(-negatives.max()) if len(negatives) else None,float(positives.min()) if len(positives) else None]
        span=float(signed.max()-signed.min()) if len(signed) else None
        diagonals.append({'id':name,'intersections':pieces,'centerToFirstPerimeterMillimeters':radius,'outerSpanMillimeters':span})
    files['diagonals.json']=json_bytes({'knownID1DimensionsMillimeters':[85.6,53.98],'rectangleDiagonalMillimeters':float(np.hypot(85.6,53.98)),
        'diagonals':diagonals,'physicalPerimeterStatus':'unresolved','cornerRadii':'separate_model'})
    manifest={'schemaVersion':1,'type':'id_cadastral_scanline_measurements','sourceHashes':admitted['sourceHashes'],'boundaryId':admitted['boundaryId'],
        'rectificationManifestSHA256':digest(rect_bytes),'grids':grids,'method':'shapely_intersection_full_grid','scanStepPixels':.5,
        'scanLocations':'pixel_centers_and_edges','processing':{'skippedRows':0,'skippedColumns':0,'smoothing':False,'newFitting':False},
        'physicalPerimeterStatus':'unresolved','boundaryMethod':'retained_grabcut','registration':'retained_rectification',
        'columns':{'scans':['position','status','intervalCount','outerSpanPixels','occupiedLengthPixels','outerSpanMillimeters','occupiedLengthMillimeters'],
        'intervals':['startX','startY','endX','endY','lengthPixels','lengthMillimeters','sourceStartX','sourceStartY','sourceEndX','sourceEndY','kind'],
        'perimeter':['sourceX','sourceY','rectifiedX','rectifiedY','cardXmm','cardYmm','centerRadiusMm','ringId']},
        'statusCodes':{'empty':0,'single':1,'multiple':2,'tangent':3,'boundary_overlap':4},'intervalKinds':{'interior':0,'point':1,'boundary_overlap':2},
        'implementation':{'shapely':shapely.__version__,'geos':shapely.geos_version_string,'sourceSHA256':digest(Path(__file__).read_bytes())},
        'artifacts':{k:{'sha256':digest(v),'bytes':len(v)} for k,v in files.items()}}
    files['manifest.json']=json_bytes(manifest)
    if validate_dataset(boundary,base)!=admitted or (rectification/'manifest.json').read_bytes()!=rect_bytes:raise ValueError('Inputs changed')
    validate_files(files)
    publish_directory(out,files)
    return manifest


def validate_files(files):
    m=strict_json(files['manifest.json'])
    if m.get('schemaVersion')!=1 or m.get('type')!='id_cadastral_scanline_measurements' or m.get('scanStepPixels')!=.5:raise ValueError('Measurement schema')
    expected={f'{f}-{a}-{k}.npy' for f in ('source','rectified') for a in ('x','y') for k in ('scans','offsets','intervals')} | {'perimeter.npy','diagonals.json'}
    if set(m['artifacts'])!=expected or m.get('method')!='shapely_intersection_full_grid' or m.get('processing')!={'skippedRows':0,'skippedColumns':0,'smoothing':False,'newFitting':False}:raise ValueError('Measurement method or artifacts')
    for name,entry in m['artifacts'].items():
        if Path(name).name!=name or entry!={'sha256':digest(files[name]),'bytes':len(files[name])}:raise ValueError('Measurement artifact')
    for frame in ('source','rectified'):
        for axis in ('x','y'):
            arrays={k:np.load(io.BytesIO(files[f'{frame}-{axis}-{k}.npy']),allow_pickle=False) for k in ('scans','offsets','intervals')}
            s,o,p=arrays['scans'],arrays['offsets'],arrays['intervals'];n=m['grids'][frame]['height' if axis=='x' else 'width']*2+1
            if s.shape!=(n,7) or not np.array_equal(s[:,0],np.arange(n)/2) or not np.isfinite(s).all():raise ValueError('Incomplete scan lattice')
            if o.dtype!=np.dtype('<i8') or o.shape!=(n+1,) or o[0]!=0 or np.any(o<0) or np.any(o>len(p)) or np.any(o[1:]<o[:-1]) or o[-1]!=len(p):raise ValueError('Invalid interval offsets')
            if p.ndim!=2 or p.shape[1]!=11 or not np.isfinite(p).all() or not np.array_equal(s[:,2],np.diff(o)):raise ValueError('Invalid intervals')
            for i in range(n):
                rows=p[o[i]:o[i+1]]
                if len(rows):
                    fixed=(rows[:,[1,3]] if axis=='x' else rows[:,[0,2]])
                    if not np.allclose(fixed,s[i,0],rtol=0,atol=1e-9):raise ValueError('Off scanline endpoints')
                    lengths=np.linalg.norm(rows[:,2:4]-rows[:,:2],axis=1)
                    span=np.linalg.norm(rows[-1,2:4]-rows[0,:2])
                    if not np.allclose(lengths,rows[:,4],rtol=1e-10,atol=1e-9) or not np.isclose(span,s[i,3],rtol=1e-10,atol=1e-9) or not np.isclose(lengths.sum(),s[i,4],rtol=1e-10,atol=1e-9) or not np.isclose(rows[:,5].sum(),s[i,6],rtol=1e-10,atol=1e-9):raise ValueError('Inconsistent distances')
                elif np.any(s[i,1:]!=0):raise ValueError('Empty scan has measurement')
    return m


def load_dataset(path,source_hashes,boundary_id,rectification_hash):
    path=Path(path);raw=(path/'manifest.json').read_bytes();m=strict_json(raw)
    if m['sourceHashes']!=source_hashes or m['boundaryId']!=boundary_id or m['rectificationManifestSHA256']!=rectification_hash:raise ValueError('Measurement lineage mismatch')
    names=list(m['artifacts'])
    if path.is_symlink() or any(Path(n).name!=n or (path/n).is_symlink() for n in ['manifest.json']+names):raise ValueError('Measurement artifact path')
    files={'manifest.json':raw,**{n:(path/n).read_bytes() for n in names}}
    validate_files(files);return m,files

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('boundary');p.add_argument('rectification');p.add_argument('out');a=p.parse_args()
    print(run(a.baseline,a.boundary,a.rectification,a.out)['grids'])
