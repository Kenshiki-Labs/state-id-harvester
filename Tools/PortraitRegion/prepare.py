"""Locate retained SDK portrait crops in native pixels; no detection or image resampling."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
from uuid import UUID
import numpy as np
from PIL import Image
from rasterio.features import rasterize
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from CardEdges.dataset import load_dataset
from CardBoundary.json_contract import strict_json, require
from CardBoundary.native_input import load_native
from CardBoundary.publication import publish_directory


def digest(data):return hashlib.sha256(data).hexdigest()
def encoded(value):return (json.dumps(value,indent=2,allow_nan=False)+'\n').encode()


def verified(root,name,expected):
    require(isinstance(name,str) and Path(name).name==name and name not in ('','.','..'),'Invalid artifact filename')
    path=root/name
    require(path.is_file() and not path.is_symlink(),'Expected regular portrait artifact')
    data=path.read_bytes();require(digest(data)==expected,'Portrait artifact hash mismatch: '+name)
    return data


def footprint(rect,derivation):
    """Saved crop pixel edges -> nominal card plane -> upright original pixel edges."""
    x,y,w,h=[rect[k] for k in ('x','y','width','height')]
    require(all(type(v) is int for v in (x,y,w,h)) and x>=0 and y>=0 and w>0 and h>0,'Invalid crop bounds')
    require(x+w<=derivation['outputPixelWidth'] and y+h<=derivation['outputPixelHeight'],'Crop outside saved derivative')
    g=derivation['id1Geometry'];scale=g['outputPixelsPerMillimeter']
    require(np.isfinite(scale) and scale>0,'Invalid saved scale')
    matrix=np.array(g['cardMillimetersToSource'],dtype=float).reshape(3,3)
    inverse=np.array(g['sourceToCardMillimeters'],dtype=float).reshape(3,3)
    product=matrix@inverse
    require(np.isfinite(matrix).all() and abs(product[2,2])>1e-12 and np.allclose(product/product[2,2],np.eye(3),atol=1e-7),'Invalid inverse registration')
    points=np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],dtype=float)/scale
    mapped=np.column_stack((points,np.ones(4)))@matrix.T
    require(np.isfinite(mapped).all() and np.all(np.abs(mapped[:,2])>1e-12) and (np.all(mapped[:,2]>0) or np.all(mapped[:,2]<0)),'Singular crop registration')
    result=(mapped[:,:2]/mapped[:,2,None]).tolist()
    return result+[result[0]]


def measurements(ring,size,points,offsets):
    w,h=size
    # Rasterize membership at every source pixel center; do not rasterize display strokes.
    mask=rasterize([({'type':'Polygon','coordinates':[ring]},1)],out_shape=(h,w),dtype='uint8',all_touched=False).astype(bool)
    flat=points[:,1].astype(np.int64)*w+points[:,0]
    inside=mask.ravel()[flat]
    count=int(np.unique(flat[inside]).size);area=int(mask.sum())
    require(area>0,'Empty source footprint')
    delta=np.diff(points.astype(np.int64),axis=0)
    paired=inside[:-1]&inside[1:]
    boundaries=offsets[1:-1]-1
    paired[boundaries]=False
    delta=delta[paired];lengths=np.linalg.norm(delta,axis=1)
    directions={}
    for name,chosen in [('horizontal',delta[:,1]==0),('vertical',(delta[:,0]==0)&(delta[:,1]!=0)),('diagonal_down',delta[:,0]*delta[:,1]>0),('diagonal_up',delta[:,0]*delta[:,1]<0)]:
        directions[name]=float(lengths[chosen].sum())
    touched=sum(bool(inside[a:b].any()) for a,b in zip(offsets[:-1],offsets[1:]))
    return dict(sourcePixelCount=area,uniqueEdgePixelCount=count,edgePixelFraction=count/area,
        intersectingChainCount=touched,interiorSegmentLengthSourcePixels=float(lengths.sum()),
        directionLengthsSourcePixels=directions,
        membership='source_pixel_center_in_projected_crop',segmentPolicy='both_endpoints_inside_same_retained_chain')


def prepare(export,capture_id,baseline,edges,output):
    export,baseline,edges,output=map(Path,(export,baseline,edges,output))
    require(not export.is_symlink(),'Export symlink')
    capture_id=str(UUID(capture_id)).upper()
    raw_index=(export/'index.json').read_bytes();index=strict_json(raw_index)
    require(index.get('kind')=='sdk_viewer_export' and index.get('schemaVersion')==1,'Unsupported export')
    entries=[c for c in index['captures'] if c['captureID']==capture_id]
    require(len(entries)==1,'Ambiguous exported capture');entry=entries[0];source=export/capture_id
    require(not source.is_symlink(),'Capture symlink')
    geometry_bytes=verified(source,'geometry.json',entry['geometrySHA256'])
    geometry=strict_json(geometry_bytes)
    require(geometry_bytes==(baseline/'front-geometry.json').read_bytes(),'Export belongs to another derivative')
    rgb,meta,source_hashes=load_native(baseline);height,width=rgb.shape[:2];del rgb
    require(entry['sourceSHA256']==source_hashes['front-original.heic']==geometry['sourceSHA256'],'Export belongs to another original')
    edge_manifest,points,offsets,_,_=load_dataset(edges,source_hashes=source_hashes)
    derivation=geometry['derivation'];derivative_hash=derivation['outputSHA256']
    require(entry['derivativeSHA256']==derivative_hash,'Derivative hash mismatch')
    files={};candidates=[];outcomes=[];seen=set()
    require('portraits' in entry,'Export predates portrait integration')
    for record in entry['portraits']:
        raw=verified(source,record['extractionFile'],record['extractionSHA256'])
        link_raw=verified(source,record['linkFile'],record['linkSHA256'])
        extraction_record=strict_json(raw);link=strict_json(link_raw)
        require(link['recordKind']=='portraitExtraction' and link['captureID']==capture_id and link['sourceSHA256']==entry['sourceSHA256'],'Portrait link mismatch')
        files[record['extractionFile']]=raw;files[record['linkFile']]=link_raw
        outcomes.append(dict(recordID=record['recordID'],outcome=extraction_record['outcome']))
        if extraction_record['outcome']!='completed':
            require(not record['crops'],'Failed extraction cannot supply crops');continue
        extraction=extraction_record['extraction']
        require(link['derivativeSHA256']==derivative_hash==extraction['sourceSHA256'],'Portrait derivative mismatch')
        require((extraction['sourcePixelWidth'],extraction['sourcePixelHeight'])==(derivation['outputPixelWidth'],derivation['outputPixelHeight']),'Portrait source dimensions mismatch')
        require(len(extraction_record['crops'])==len(extraction['assessment']['candidates'])==len(record['crops']),'Portrait count mismatch')
        exported={c['recordID']:c for c in record['crops']}
        for crop,assessment in zip(extraction_record['crops'],extraction['assessment']['candidates']):
            identity=crop['recordID'];require(identity not in seen,'Duplicate portrait');seen.add(identity)
            d=crop['derivation'];require(d['sourceSHA256']==derivative_hash and d['geometry']==assessment,'Crop lineage mismatch')
            artifact=exported[identity];data=verified(source,artifact['file'],d['outputSHA256'])
            require(artifact['sha256']==d['outputSHA256'],'Crop export hash mismatch')
            rect=assessment['pixelRect']
            with Image.open(io.BytesIO(data)) as image:
                image.load();require(image.format=='PNG' and image.size==(rect['width'],rect['height'])==(d['outputPixelWidth'],d['outputPixelHeight']),'Crop dimensions mismatch')
            ring=footprint(rect,derivation)
            require(all(0<=x<=width and 0<=y<=height for x,y in ring),'Portrait footprint outside original')
            files[artifact['file']]=data
            candidates.append(dict(recordID=identity,image=artifact['file'],role=assessment['role'],
                faceIndex=assessment['faceIndex'],savedDerivativePixelRect=rect,sourcePolygon=ring,
                metrics=measurements(ring,(width,height),points,offsets)))
    manifest=dict(schemaVersion=1,type='retained_portrait_regions',captureID=capture_id,
        sourceHashes=source_hashes,exportIndexSHA256=digest(raw_index),
        edgeManifestSHA256=digest((edges/'manifest.json').read_bytes()),
        sourceSize=[width,height],outcomes=outcomes,candidates=candidates,
        implementationSHA256=digest(Path(__file__).read_bytes()),
        interpretation='Retained face-region footprints; complete printed portrait extent is not established.',
        artifacts={n:dict(sha256=digest(b),bytes=len(b)) for n,b in files.items()})
    require((export/'index.json').read_bytes()==raw_index,'Export changed during preparation')
    files['manifest.json']=encoded(manifest);publish_directory(output,files)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('export','baseline','edges','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--capture-id',required=True);a=p.parse_args()
    m=prepare(a.export,a.capture_id,a.baseline,a.edges,a.output)
    print(json.dumps({'candidates':len(m['candidates']),'outcomes':m['outcomes'],'output':str(a.output)}))
