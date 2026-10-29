"""Retain boundary observations; publish a conservative interior working area."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image
from rasterio import Affine
from rasterio.features import shapes, rasterize
from rasterio.io import MemoryFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'CardBoundary'))
from native_input import load_native, verify_unchanged
from validate_dataset import validate_dataset
from publication import publish_directory


def encoded(value):return (json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def png(a):
    f=io.BytesIO();Image.fromarray(a).save(f,format='PNG');return f.getvalue()


def column_extents(points):
    result={}
    for x,y in np.asarray(points,dtype=int):
        if int(x) not in result:result[int(x)]=[int(y),int(y)]
        else:result[int(x)]=[min(result[int(x)][0],int(y)),max(result[int(x)][1],int(y))]
    return result


def working_masks(original,candidates,quad,fraction):
    q=np.asarray(quad,float);lengths=np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)
    width=float(min(lengths)*fraction);h,w=original.shape
    corridor=np.zeros((h,w),bool);bottom=np.zeros((h,w),bool)
    # Every source center is evaluated, row-by-row; no sampled geometry.
    xs=np.arange(w)+.5
    for y in range(h):
        p=np.column_stack((xs,np.full(w,y+.5)))
        for s in range(4):
            a=q[s];d=q[(s+1)%4]-a;t=np.clip((p-a)@d/(d@d),0,1)
            hit=np.sum((p-a-t[:,None]*d)**2,axis=1)<=width**2
            corridor[y]|=hit
            if s==2:bottom[y]=hit
    runs=[c for c in candidates if c['sideIndex']==2 and c['tangentialSpanFraction']>=.5]
    if len(runs)!=2:raise ValueError('Expected exactly two majority-span bottom observations; unresolved')
    tangent=(q[3]-q[2])/lengths[2];normal=np.array([-tangent[1],tangent[0]])
    runs.sort(key=lambda c:float(np.median((np.array(c['points'])+.5-q[2])@normal)))
    outer,inner=runs
    a,b=column_extents(inner['points']),column_extents(outer['points'])
    corrected=original.copy();shadow=np.zeros(original.shape,bool);locations=[]
    for x in sorted(a.keys()&b.keys()):
        if not 0<=x<w:raise ValueError('Column outside raster')
        il,ih=a[x];ol,oh=b[x]
        if not (0<=il<=ih<ol<=oh<h):continue
        allowed=bottom[:,x]
        rows=np.arange(h)
        correction=allowed&(rows>=il)&(rows<=oh)
        corrected[correction,x]=False
        shadow[:,x]|=allowed&(rows>ih)&(rows<ol)
        locations.append([x,il,ih,ol,oh])
    if not locations:raise ValueError('No ordered bottom overlap; unresolved')
    changed=original!=corrected
    assert not np.any(changed&~bottom)
    labels=np.zeros(original.shape,np.uint8)
    labels[original]=2;labels[original&~corridor]=1;labels[shadow]=3
    # The complete edge-search corridor remains unassessed even outside the mask.
    labels[corridor&~shadow]=2
    assert np.array_equal(original[~bottom],corrected[~bottom])
    assert not np.any((labels==1)&(~corrected|shadow|corridor))
    return corrected,labels,dict(innerCandidateId=inner['candidateId'],outerCandidateId=outer['candidateId'],
        innerPoints=inner['points'],outerPoints=outer['points'],columnExtents=locations,
        correctedPixelCount=int(changed.sum()),supportedColumnCount=len(locations),
        exclusionCorridorWidthPixels=width,interiorPixelCount=int((labels==1).sum()),
        shadowPixelCount=int(shadow.sum()),originalCardPixelCount=int(original.sum()))


def prepare(base,boundary,candidate_dir,registration,out):
    rgb,meta,hashes=load_native(base);bm=validate_dataset(boundary,base)
    raw=(candidate_dir/'manifest.json').read_bytes();cm=json.loads(raw)
    if cm['sourceHashes']!=hashes:raise ValueError('Candidate source mismatch')
    cb=(candidate_dir/'candidates.json').read_bytes()
    if sha(cb)!=cm['artifacts']['candidates.json']['sha256']:raise ValueError('Candidate hash mismatch')
    rm_raw=(registration/'manifest.json').read_bytes();rm=json.loads(rm_raw)
    if rm['sourceHashes']!=hashes or rm['boundaryId']!=bm['boundaryId']:raise ValueError('Registration lineage mismatch')
    mask_raw=(boundary/'mask.png').read_bytes()
    if sha(mask_raw)!=bm['artifacts']['mask']['sha256']:raise ValueError('Mask changed')
    original=np.array(Image.open(io.BytesIO(mask_raw)))!=0
    cs=json.loads(cb)['candidates'];q=[[p['x'],p['y']] for p in meta['derivation']['id1Geometry']['sourceCorners']]
    corrected,labels,evidence=working_masks(original,cs,q,cm['configuration']['corridorFraction'])
    features=[{'type':'Feature','properties':{'role':'working_card'},'geometry':g} for g,v in shapes(corrected.astype(np.uint8),mask=corrected) if v==1]
    parity=rasterize([(f['geometry'],1) for f in features],out_shape=original.shape,dtype='uint8')
    if not np.array_equal(parity!=0,corrected):raise ValueError('Working geometry parity mismatch')
    output=rm['output'];size=(output['width'],output['height'])
    hmat=np.array(rm['transforms']['sourceToRectifiedPixelCenters']).reshape(3,3)
    weights=cv2.warpPerspective((labels==1).astype(np.float32),hmat,size,flags=cv2.INTER_LINEAR)
    eligible=(weights==1).astype(np.uint8)
    files={'source-labels.png':png(labels),'working-mask.png':png(corrected.astype(np.uint8)),
           'working-geometry.json':encoded({'type':'FeatureCollection','features':features}),
           'bottom-observations.json':encoded(evidence),'rectified-interior.png':png(eligible)}
    # Scene overlay leaves the working interior clear for actual feature inspection.
    rgba=np.zeros((*labels.shape,4),np.uint8);rgba[labels==2]=[245,190,55,65];rgba[labels==3]=[146,105,230,130]
    files['source-overlay.png']=png(rgba)
    rectoverlay=cv2.warpPerspective(rgba,hmat,size,flags=cv2.INTER_NEAREST)
    files['rectified-overlay.png']=png(rectoverlay)
    scale=output['pixelsPerMillimeter'];ox,oy=output['originCardMillimeters']
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',height=size[1],width=size[0],count=1,dtype='uint8',
                         transform=Affine(1/scale,0,ox,0,-1/scale,-oy),compress='deflate') as ds:
            ds.write(eligible,1);ds.set_band_description(1,'interior_eligible')
            ds.update_tags(coordinate_type='local_engineering',unit='mm',registration_sha256=sha(rm_raw))
        files['interior.tif']=memory.read()
    manifest=dict(schemaVersion=1,type='id_cadastral_interior_working_area',sourceHashes=hashes,
        boundaryId=bm['boundaryId'],candidateManifestSHA256=sha(raw),registrationManifestSHA256=sha(rm_raw),
        policy={'bottomInterpretation':'owner_directed_inner_transition','minimumSideSpanFraction':.5,
                'exclusionCorridorFraction':cm['configuration']['corridorFraction'],'gapFilling':False},
        labels={'0':'surroundings','1':'interior_eligible','2':'edge_unresolved','3':'shadow_working_region'},
        sourceDimensions=[rgb.shape[1],rgb.shape[0]],rectifiedOutput=output,
        summary={k:v for k,v in evidence.items() if k not in ('innerPoints','outerPoints','columnExtents')},
        verification={'unchangedOutsideBottomCorridor':True,'workingGeometryMaskParity':True,
                      'interiorExcludesEdgeAndShadow':True,'sourcePixelsResampled':False},
        registrationStatus='existing_nominal_registration',boundaryStatus='working_partial',
        implementationSHA256=sha(Path(__file__).read_bytes()),
        artifacts={n:{'sha256':sha(v),'bytes':len(v)} for n,v in files.items()})
    files['manifest.json']=encoded(manifest);verify_unchanged(base,hashes)
    publish_directory(out,files);print(json.dumps(manifest['summary']),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('baseline','boundary','candidates','registration','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();prepare(a.baseline,a.boundary,a.candidates,a.registration,a.output)
