"""Read-only edge-transition and adjacent-surface diagnostics for the baseline."""
import atexit
import os
import tempfile

if not os.environ.get('MPLCONFIGDIR'):
    _matplotlib_config = tempfile.TemporaryDirectory(prefix='kenshiki-boundary-matplotlib-')
    os.environ['MPLCONFIGDIR'] = _matplotlib_config.name
    atexit.register(_matplotlib_config.cleanup)
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter1d
from scipy.signal import find_peaks
import scipy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE=Path(__file__).resolve().parents[2]/'Artifacts/gis-baseline-20260911'
OUT=BASE/'boundary-review'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def project(m,xy):
    flat=np.asarray(xy).reshape(-1,2)
    v=np.c_[flat,np.ones(len(flat))]@np.asarray(m).reshape(3,3).T
    return (v[:,:2]/v[:,2,None]).reshape(np.shape(xy))

def run():
    OUT.mkdir(exist_ok=True)
    paths=[BASE/'front-original.heic',BASE/'front-rectified.png',BASE/'front-geometry.json',BASE/'browser-viewer/original.png']
    paths += [BASE/'geotiff/front-card.tif',BASE/'geotiff/manifest.json',BASE/'browser-viewer/objects.json',BASE/'browser-viewer/objects-mask.png']
    before={str(p.relative_to(BASE)):sha(p) for p in paths}
    meta=json.loads(paths[2].read_text());g=meta['derivation']['id1Geometry']
    if before['front-original.heic']!=meta['derivation']['sourceSHA256'] or before['front-rectified.png']!=meta['derivation']['outputSHA256']:raise ValueError('Baseline hash mismatch')
    display=json.loads((BASE/'browser-viewer/manifest.json').read_text())
    if display['viewerDerivation']['sourceSHA256'] != before['front-original.heic']:raise ValueError('Display source lineage mismatch')
    if before['browser-viewer/original.png']!=display['viewerDerivation']['outputSHA256']:raise ValueError('Display hash mismatch')
    im=np.array(Image.open(paths[3]).convert('RGB'))
    h,w,_=im.shape
    channels=[im[:,:,c].astype(np.float32) for c in range(3)]
    if (w,h)!=(g['sourcePixelWidth'],g['sourcePixelHeight']):raise ValueError('Orientation mismatch')
    def sample(xy):
        src=project(g['cardMillimetersToSource'],xy)
        if np.any(src[...,0]<.5) or np.any(src[...,0]>w-.5) or np.any(src[...,1]<.5) or np.any(src[...,1]>h-.5):raise ValueError('Sample outside source')
        # Geometry describes pixel edges, scipy array indices describe centers.
        coords=[src[...,1]-.5,src[...,0]-.5]
        return np.stack([map_coordinates(channels[c],coords,order=1,mode='constant',cval=np.nan,prefilter=False) for c in range(3)],axis=-1),src
    W,H=g['nominalWidthMillimeters'],g['nominalHeightMillimeters']
    edges={'top':(np.array([0.,0.]),np.array([W,0.]),np.array([0.,1.])),
           'right':(np.array([W,0.]),np.array([W,H]),np.array([-1.,0.])),
           'bottom':(np.array([W,H]),np.array([0.,H]),np.array([0.,-1.])),
           'left':(np.array([0.,H]),np.array([0.,0.]),np.array([1.,0.]))}
    distances=np.linspace(-3,3,301);fractions=np.linspace(.1,.9,81)
    result={'schemaVersion':1,'sourceHashes':before,'parameters':{'stationsPerEdge':81,'edgeFractionRange':[.1,.9],
        'distanceRangeNominalMillimeters':[-3,3],'samplingStepNominalMillimeters':.02,
        'smoothingSigmaNominalMillimeters':[.04,.08,.16],'normalDirection':'card_plane_inward',
        'sourceInterpolation':'bilinear','gradient':'euclidean_rgb_derivative','peakRetention':'filtered_local_maxima','peakMinimumSpacingNominalMillimeters':.2,'peakMinimumProminence':5,
        'texturePatchWidthsNominalMillimeters':[.25,.5,1.0],'texturePatchOffsetNominalMillimeters':2,
        'textureStationFractions':[.2,.5,.8]},
        'tools':{'scipy':scipy.__version__,'numpy':np.__version__,'matplotlib':matplotlib.__version__},'edges':{}}
    raw={}; texture=[]
    for name,(a,b,n) in edges.items():
        centers=a+fractions[:,None]*(b-a)
        xy=centers[:,None,:]+distances[None,:,None]*n
        rgb,src=sample(xy);raw[name+'_rgb']=rgb;raw[name+'_source_xy']=src
        all_scales={}
        for sigma in [.04,.08,.16]:
            smooth=gaussian_filter1d(rgb,sigma/.02,axis=1)
            gradient=np.linalg.norm(np.gradient(smooth,.02,axis=1),axis=2)
            stations=[]
            for j,t in enumerate(fractions):
                peaks,_=find_peaks(gradient[j],distance=10,prominence=5)
                best=sorted(peaks,key=lambda i:gradient[j,i],reverse=True)
                candidates=[]
                for index in best:
                    delta=src[j,index]-src[j,150]
                    candidates.append({'offsetNominalMillimeters':float(distances[index]),
                       'offsetRectifiedPixels':float(distances[index]*50),
                       'sourceDisplacementPixels':float(np.linalg.norm(delta)*np.sign(distances[index])),
                       'sourceXY':src[j,index].tolist(),'rectifiedXY':(xy[j,index]*50).tolist(),'gradient':float(gradient[j,index]),
                       'relationToRectifiedFrame':'inside' if distances[index]>0 else 'outside' if distances[index]<0 else 'boundary'})
                stations.append({'edgeFraction':float(t),'candidates':candidates})
            all_scales[str(sigma)]={'stations':stations}
            raw[name+'_gradient_'+str(sigma)]=gradient
        central=all_scales['0.08']['stations']
        strongest=[s['candidates'][0]['offsetNominalMillimeters'] for s in central if s['candidates']]
        result['edges'][name]={'scales':all_scales,'strongestCandidateOffsetQuantilesNominalMillimeters':np.quantile(strongest,[.1,.5,.9]).tolist() if strongest else [],'stationsWithCandidate':len(strongest)}
        fig,axs=plt.subplots(3,1,figsize=(12,9),constrained_layout=True)
        axs[0].imshow(np.clip(rgb,0,255).astype(np.uint8),extent=[-3,3,.9,.1],aspect='auto');axs[0].set_title(name+' — sampled appearance')
        axs[1].imshow(raw[name+'_gradient_0.08'],extent=[-3,3,.9,.1],aspect='auto',cmap='magma');axs[1].set_title('RGB transition strength · sigma 0.08 nominal mm')
        for ax in axs[:2]:ax.axvline(0,color='cyan');ax.set_ylabel('Position along edge')
        for c,color in enumerate(['red','green','blue']):axs[2].plot(distances,np.median(rgb[:,:,c],axis=0),color=color,label=color)
        axs[2].axvline(0,color='black',linestyle='--');axs[2].legend();axs[2].set_ylabel('Median decoded RGB');axs[2].set_xlabel('Offset from saved boundary, nominal mm; negative outside / positive inside')
        fig.savefig(OUT/(name+'-profiles.png'),dpi=120);plt.close(fig)
        # Paired samples are descriptions of appearance; no exclusion masks or material labels.
        for t in [.2,.5,.8]:
            for size in [.25,.5,1.]:
                offsets=np.linspace(-size/2,size/2,round(size*50)+1)
                xx,yy=np.meshgrid(offsets,offsets)
                for side,sign in [('inside',1),('outside',-1)]:
                    center=a+t*(b-a)+sign*2*n
                    patch,_=sample(center+np.stack([xx,yy],axis=-1))
                    diffs=np.r_[np.diff(patch,axis=0).reshape(-1,3),np.diff(patch,axis=1).reshape(-1,3)]
                    texture.append({'edge':name,'fraction':t,'side':side,'widthNominalMillimeters':size,
                       'sampleSpacingNominalMillimeters':float(offsets[1]-offsets[0]),'sampleShape':list(patch.shape[:2]),
                       'meanRGB':np.mean(patch,axis=(0,1)).tolist(),'stdRGB':np.std(patch,axis=(0,1)).tolist(),
                       'adjacentDifferenceRMS':float(np.sqrt(np.mean(diffs**2)))})
    result['pairedSurfaceSamples']=texture
    result['interpretation']={'candidateRole':'image_transition','physicalBoundaryStatus':'unresolved',
                              'geometryModified':False,'sourceImagesModified':False}
    after={str(p.relative_to(BASE)):sha(p) for p in paths}
    if before!=after:raise ValueError('Source changed during review')
    result['verification']={'sourceHashesUnchanged':True,'allSamplesInSource':True}
    result['scriptSHA256']=sha(Path(__file__))
    np.savez_compressed(OUT/'profiles.npz',distanceNominalMillimeters=distances,edgeFractions=fractions,**raw)
    (OUT/'measurements.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v['strongestCandidateOffsetQuantilesNominalMillimeters'] for k,v in result['edges'].items()},indent=2))
    print('Texture RMS means', {side:float(np.mean([v['adjacentDifferenceRMS'] for v in texture if v['side']==side])) for side in ['inside','outside']})
if __name__=='__main__':run()
