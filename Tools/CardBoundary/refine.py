"""Evaluate automatic GrabCut seeds; publish candidates without replacing geometry."""
import argparse,hashlib,json,time,math,resource,tempfile
from publication import publish_directory
from native_input import load_native
import rasterio,shapely
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon, box, mapping, shape
from rasterio.features import rasterize, shapes
from rasterio import Affine


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)

def segment_native(rgb,seeds):
    """Native RGB + automatic label seeds -> GrabCut labels; inputs unchanged."""
    require(rgb.dtype==np.uint8 and rgb.ndim==3 and rgb.shape[2]==3,'Expected native RGB8')
    require(seeds.dtype==np.uint8 and seeds.shape==rgb.shape[:2],'Seed dimensions/type mismatch')
    mask=seeds.copy()
    cv2.setRNGSeed(0);cv2.setNumThreads(1)
    bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
    require(np.array_equal(bgr[:,:,::-1],rgb),'BGR reorder changed samples')
    cv2.grabCut(bgr,mask,None,np.zeros((1,65),np.float64),
                np.zeros((1,65),np.float64),5,cv2.GC_INIT_WITH_MASK)
    return mask


def select_foreground(mask,seeds):
    """Labels -> four-connected foreground containing the definite core."""
    foreground=np.isin(mask,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype('uint8')
    count,labels,_,_=cv2.connectedComponentsWithStats(foreground,connectivity=4)
    seed_components=np.unique(labels[seeds==cv2.GC_FGD])
    require(len(seed_components)==1 and seed_components[0]!=0,'Foreground core split or missing')
    component=(labels==int(seed_components[0])).astype('uint8')
    return foreground,component,count


def polygonize_native(component):
    """Binary native mask -> exact pixel-edge polygon, retaining interior rings."""
    h,w=component.shape;transform=Affine.identity()
    geoms=[shape(geom) for geom,value in shapes(component,mask=component.astype(bool),
           transform=transform,connectivity=4) if value==1]
    require(len(geoms)==1 and geoms[0].geom_type=='Polygon','Unsupported contour topology')
    polygon=geoms[0]
    require(polygon.is_valid and not polygon.is_empty,'Invalid contour')
    require(not polygon.boundary.intersects(box(0,0,w,h).boundary),'Contour clipped by frame')
    roundtrip=rasterize([(mapping(polygon),1)],out_shape=(h,w),transform=transform,
                        dtype='uint8',all_touched=False)
    require(np.array_equal(roundtrip,component),'Polygon-mask round trip mismatch')
    return polygon


def _run_stage(base,out,fraction):
    require(not out.exists(),'Output exists')
    out.mkdir(parents=True)
    safe_fraction=fraction if isinstance(fraction,(int,float)) and math.isfinite(fraction) else None
    result={'schemaVersion':2,'status':'failed','failureCode':None,'geometry':None,
            'assessment':'unevaluated','method':'opencv_grabcut_auto_seeds',
            'implementation':{'opencv':cv2.__version__,'rasterio':rasterio.__version__,'gdal':rasterio.__gdal_version__,'shapely':shapely.__version__,'geos':shapely.geos_version_string,'scriptSHA256':sha(Path(__file__)),'nativeInputSHA256':sha(Path(__file__).with_name('native_input.py')),'jsonContractSHA256':sha(Path(__file__).with_name('json_contract.py')),'publicationSHA256':sha(Path(__file__).with_name('publication.py'))},
            'parameters':{'seedBandFractionOfShortEdge':safe_fraction,'workingResolution':'native','workingExtent':'full_frame',
                          'iterations':5,'rngSeed':0,'threads':1,'resampling':'none'}}
    try:
        require(math.isfinite(fraction) and 0 < fraction < .5,'Invalid seed band fraction')
        rgb,meta,hashes=load_native(base);result['sourceHashes']=hashes
        g=meta['derivation']['id1Geometry'];h,w=rgb.shape[:2]
        corners=np.array([[p['x'],p['y']] for p in g['sourceCorners']],dtype=float)
        require(corners.shape==(4,2) and np.all(np.isfinite(corners)),'Expected four finite corners')
        quad=Polygon(corners)
        require(len(np.unique(corners,axis=0))==4 and quad.area>0 and
                quad.convex_hull.geom_type=='Polygon' and len(quad.convex_hull.exterior.coords)==5 and
                quad.equals(quad.convex_hull),'Expected convex ordered quadrilateral')
        require(quad.is_valid and box(0,0,w,h).covers(quad),'Invalid prior')
        band=fraction*min(np.linalg.norm(np.roll(corners,-1,axis=0)-corners,axis=1))
        inner=quad.buffer(-band);outer=quad.buffer(band)
        require(not inner.is_empty and box(0,0,w,h).contains(outer),'Seed geometry outside source')
        working=rgb
        ww,hh=w,h
        transform=Affine.identity()
        working_hash=hashlib.sha256(working.tobytes()).hexdigest()
        result['fidelity']={'workingExtent':'full_frame','sourceSize':[w,h],'workingSize':[ww,hh],
                            'workingToSourceAffine':list(transform)[:6],
                            'sourceRGBSHA256':working_hash,'workingRGBSHA256':working_hash,
                            'resampled':False,'cropped':False,'sourcePixelsAdmitted':w*h}
        mask=rasterize([(mapping(outer),cv2.GC_PR_BGD),(mapping(quad),cv2.GC_PR_FGD),
                        (mapping(inner),cv2.GC_FGD)],out_shape=(hh,ww),transform=transform,
                        fill=cv2.GC_BGD,dtype='uint8',all_touched=False)
        require(all(np.any(mask==label) for label in [cv2.GC_BGD,cv2.GC_FGD]),'Missing definite seed class')
        seeds=mask.copy();Image.fromarray(seeds).save(out/'seeds.png')
        start=time.monotonic()
        mask=segment_native(working,seeds)
        result['fidelity']['bgrRoundTripEqual']=True
        foreground,component,count=select_foreground(mask,seeds)
        polygon=polygonize_native(component)
        Image.fromarray(component).save(out/'candidate-mask.png')
        # Pixel-edge polygon comes from GDAL; OpenCV contour used for seed-contact diagnostics.
        contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        definite_bg=(seeds==cv2.GC_BGD).astype('uint8')
        near_bg=cv2.dilate(definite_bg,np.ones((3,3),np.uint8))
        coords=np.concatenate(contours).reshape(-1,2)
        touching=int(np.count_nonzero(near_bg[coords[:,1],coords[:,0]]))
        result.update(status='candidate',failureCode=None,geometry=mapping(polygon),
            coordinateSystem={'type':'image_pixels','origin':'top_left_edge','xDirection':'right','yDirection':'down','width':w,'height':h},
            diagnostics={'runtimeSeconds':time.monotonic()-start,'peakResidentBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'workingSize':[ww,hh],
                         'workingToSourceAffine':list(transform)[:6],'seedBandSourcePixels':band,
                         'seedCounts':{str(i):int(np.count_nonzero(seeds==i)) for i in range(4)},
                         'components':count-1,'discardedForegroundPixels':int(foreground.sum()-component.sum()),
                         'holes':len(polygon.interiors),'contourSamples':len(coords),
                         'seedBoundaryContactSamples':touching,'areaSquarePixels':polygon.area,
                         'addedAreaSquarePixels':polygon.difference(quad).area,
                         'removedAreaSquarePixels':quad.difference(polygon).area,
                         'bounds':list(polygon.bounds)},
            sourceSHA256=hashes['front-original.heic'])
        require(hashes=={p:sha(base/p) for p in hashes},'Source mutated during experiment')
        result['verification']={'sourceHashesUnchanged':True,'validPolygon':True,'fullFrameContained':True,'polygonMaskRoundTrip':True}
        # Separate diagnostic crops only. Orange=observed segmentation contour.
        points={f'corner-{i}':p for i,p in enumerate(corners)}
        points.update({f'edge-{i}':(corners[i]+corners[(i+1)%4])/2 for i in range(4)})
        for name,p in points.items():
            r=220;left,top=int(p[0])-r,int(p[1])-r
            tile=Image.fromarray(rgb).crop((left,top,left+2*r,top+2*r))
            draw=ImageDraw.Draw(tile)
            for ring in [polygon.exterior,*polygon.interiors]:draw.line([(x-left,y-top) for x,y in ring.coords],fill='#ff914d',width=2)
            tile.save(out/(name+'.png'))
    except (ValueError,TypeError,IndexError,cv2.error,OSError,KeyError,MemoryError,KeyboardInterrupt) as e:
        result.update(status='failed',geometry=None,failureCode=type(e).__name__,failureDetail=str(e))
    (out/'candidate.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result.get(k) for k in ['status','failureDetail','diagnostics']},indent=2),flush=True)
    return result

def run(base,out,fraction):
    """Derive privately; publish only a complete success or failure record."""
    base,out=Path(base),Path(out)
    require(not out.exists() and not out.is_symlink(),'Output exists')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.'+out.name+'.processing-',dir=out.parent) as scratch:
        stage=Path(scratch)/'run'
        result=_run_stage(base,stage,fraction)
        publish_directory(out,{p.name:p.read_bytes() for p in stage.iterdir() if p.is_file()})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--band-fraction',type=float,default=.04)
    a=p.parse_args();result=run(a.baseline.resolve(),a.output.resolve(),a.band_fraction)
    raise SystemExit(0 if result['status']=='candidate' else 1)
