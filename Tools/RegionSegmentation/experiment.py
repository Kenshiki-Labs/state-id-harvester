"""Full-scene native watershed comparison; no card membership is inferred."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import resource

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
import scipy
import skimage
from skimage.color import rgb2lab
from skimage.morphology import h_minima
from skimage.segmentation import watershed, find_boundaries
from skimage.measure import label
from adjacency import graph_records

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'CardBoundary'))
from native_input import load_native, verify_unchanged
from publication import publish_directory
from dataset import json_bytes, digest

# Preregistered experimental conditions; no per-ROI fitting or manual labels.
PARAMETERS={'derivativeSigmaNominalMM':.03,'textureSigmaNominalMM':.15,
            'markerDepths':[.08,.16],'cueModes':['luminance','chroma_texture'],
            'gradientQuantile':.99,'connectivity':1,'compactness':0,
            'textureBrightnessFloor':.01}
FOOTPRINT=ndi.generate_binary_structure(2,1)


def require(value,message):
    if not value: raise ValueError(message)


def gradient(array,sigma):
    dx=ndi.gaussian_filter(array,sigma=sigma,order=(0,1),mode='reflect')
    dy=ndi.gaussian_filter(array,sigma=sigma,order=(1,0),mode='reflect')
    return np.hypot(dx,dy)


def normalize(array):
    q=float(np.quantile(array,PARAMETERS['gradientQuantile']))
    require(math.isfinite(q) and q>0,'Feature has no usable variation')
    return array/q,q


def features(rgb,pixels_per_mm):
    require(rgb.dtype==np.uint8 and rgb.ndim==3 and rgb.shape[2]==3,'Expected native RGB8')
    sigma=PARAMETERS['derivativeSigmaNominalMM']*pixels_per_mm
    neighborhood=PARAMETERS['textureSigmaNominalMM']*pixels_per_mm
    lab=rgb2lab(rgb.astype(np.float32)/255.)
    light=lab[:,:,0]/100.
    smooth=ndi.gaussian_filter(light,neighborhood,mode='reflect')
    relative=(light-smooth)/np.maximum(smooth,PARAMETERS['textureBrightnessFloor'])
    texture=np.sqrt(ndi.gaussian_filter(relative*relative,neighborhood,mode='reflect'))
    lum,lq=normalize(gradient(light,sigma))
    chroma,cq=normalize(np.hypot(gradient(lab[:,:,1]/100.,sigma),gradient(lab[:,:,2]/100.,sigma)))
    tex,tq=normalize(gradient(texture,sigma))
    multi=np.hypot(chroma,tex)/math.sqrt(2.)
    return {'luminance':lum,'chroma_texture':multi},lab,texture,{
        'derivativeSigmaSourcePixels':sigma,'textureSigmaSourcePixels':neighborhood,
        'normalizationQuantiles':{'luminance':lq,'chroma':cq,'texture':tq}}


def partition(elevation,depth):
    require(elevation.ndim==2 and np.isfinite(elevation).all(),'Invalid elevation')
    minima=h_minima(elevation,depth,footprint=FOOTPRINT)
    markers,count=ndi.label(minima,structure=FOOTPRINT)
    require(count>0,'No automatic markers')
    labels=watershed(elevation,markers,connectivity=1,compactness=0,watershed_line=False)
    require(np.all(labels>0),'Unassigned scene pixels')
    _,connected=label(labels,connectivity=1,return_num=True)
    require(connected==count,'Disconnected region labels')
    return labels.astype(np.int32),count


def diagnostic_boxes():
    # Observation-only windows from retained failure diagnostics; never seeds.
    return {'left':(460,3860,680,4340),'bottom-left':(1040,4619,1360,4849),
            'bottom-center':(2240,4633,2560,4863),'bottom-right':(3440,4651,3760,4881),
            'top-midpoint':(2390,2100,2830,2440)}


def diagnostics(rgb,labels,stage,condition,boxes=None):
    boundaries=find_boundaries(labels,connectivity=1,mode='thick')
    records={}
    for name,box in (boxes if boxes is not None else diagnostic_boxes()).items():
        x0,y0,x1,y1=box
        image=rgb[y0:y1,x0:x1].copy();edge=boundaries[y0:y1,x0:x1]
        image[edge]=[255,0,180]
        Image.fromarray(image).save(stage/f'{condition}-{name}.png')
        records[name]={'sourceBounds':list(box),'regionIds':np.unique(labels[y0:y1,x0:x1]).tolist()}
    return records


def run(base,out,full_scene_diagnostics=False):
    base,out=Path(base),Path(out)
    require(not out.exists() and not out.is_symlink(),'Output exists')
    out.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    executed_source=Path(__file__).read_bytes()
    adjacency_source=Path(__file__).with_name('adjacency.py').read_bytes()
    rgb,meta,hashes=load_native(base);h,w=rgb.shape[:2]
    boxes={'full-scene':(0,0,w,h)} if full_scene_diagnostics else diagnostic_boxes()
    corners=np.array([[p['x'],p['y']] for p in meta['derivation']['id1Geometry']['sourceCorners']])
    lengths=np.linalg.norm(np.roll(corners,-1,axis=0)-corners,axis=1)
    scales=lengths/np.array([85.6,53.98,85.6,53.98]);scale=float(np.mean(scales))
    print(json.dumps({'stage':'native_features','dimensions':[w,h],'pixels':w*h,'nominalPixelsPerMM':scale}),flush=True)
    elevations,lab,texture,feature_info=features(rgb,scale)
    records=[]
    with tempfile.TemporaryDirectory(prefix='.'+out.name+'.processing-',dir=out.parent) as scratch:
        stage=Path(scratch)
        np.savez_compressed(stage/'elevations.npz',**elevations)
        for name,box in (boxes if boxes is not None else diagnostic_boxes()).items():
            Image.fromarray(rgb[box[1]:box[3],box[0]:box[2]]).save(stage/f'source-{name}.png')
        for mode in PARAMETERS['cueModes']:
            for depth in PARAMETERS['markerDepths']:
                condition=f'{mode}-h{depth:.2f}'
                print(json.dumps({'stage':'watershed','condition':condition}),flush=True)
                labels,count=partition(elevations[mode],depth)
                np.savez_compressed(stage/f'{condition}-labels.npz',labels=labels)
                graph=graph_records(labels,elevations[mode],lab,texture)
                (stage/f'{condition}-regions.json').write_bytes(json_bytes(graph))
                window_records=diagnostics(rgb,labels,stage,condition,boxes)
                records.append({'condition':condition,'cueMode':mode,'markerDepth':depth,'regionCount':count,
                    'adjacencyCount':len(graph['adjacencies']),'assignedPixels':int(labels.size),
                    'connectedLabels':True,'diagnosticWindows':window_records})
                print(json.dumps({'stage':'condition_complete',**{k:records[-1][k] for k in ['condition','regionCount','adjacencyCount']}}),flush=True)
        verify_unchanged(base,hashes)
        files={p.name:p.read_bytes() for p in stage.iterdir()}
        files['executed-experiment.py.txt']=executed_source
        files['executed-adjacency.py.txt']=adjacency_source
        manifest={'schemaVersion':1,'type':'id_cadastral_region_experiment','sourceHashes':hashes,
            'diagnosticScope':'full_scene' if full_scene_diagnostics else 'historical_registered_windows',
            'adjacencyMethod':'skimage_rag_four_connected_exact_interfaces',
            'sourceSize':[w,h],'sourceRGBSHA256':digest(rgb.tobytes()),'parameters':PARAMETERS,
            'nominalScale':{'meanPixelsPerMM':scale,'edgePixelsPerMM':scales.tolist()},
            'featureDerivation':feature_info,'conditions':records,
            'artifacts':{name:{'sha256':digest(data),'bytes':len(data)} for name,data in files.items()},
            'tools':{'numpy':np.__version__,'scipy':scipy.__version__,'scikitImage':skimage.__version__,
                'scriptSHA256':digest(executed_source),'adjacencyScriptSHA256':digest(adjacency_source)},
            'diagnostics':{'runtimeSeconds':time.monotonic()-started,'peakResidentBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'verification':{'nativeFullScene':True,'sourceHashesUnchanged':True,'manualLabels':False,'cardMaskConstraint':False},
            'assessment':{'status':'unevaluated','cardMembershipInferred':False,'confirmedDamageLocation':'unregistered'}}
        files['manifest.json']=json_bytes(manifest);publish_directory(out,files)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--full-scene-diagnostics',action='store_true')
    a=p.parse_args();run(a.baseline,a.output,a.full_scene_diagnostics)
