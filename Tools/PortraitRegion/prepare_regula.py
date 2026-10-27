"""Locate the provider's printed portrait; verify registration against actual pixels.

The provider document image is used ONLY to check coordinate registration.
Density is measured from original-resolution retained edges, never its JPEG.
"""
import argparse
import base64
import io
from pathlib import Path
import sys
import cv2
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PortraitRegion.prepare import digest, encoded, measurements
from CardBoundary.json_contract import strict_json, require
from CardBoundary.native_input import load_native
from CardBoundary.publication import publish_directory
from CardEdges.dataset import load_dataset


def project_geometry(g, source_size):
    """Regula's document raster -> upright source, converting lower-left position."""
    w,h=source_size
    dw,dh=g['documentWidth'],g['documentHeight']
    x,y,rw,rh=[g[k] for k in ('left','top','width','height')]
    require(np.isfinite([dw,dh,x,y,rw,rh]).all() and dw>0 and dh>0 and x>=0 and y>=0 and rw>0 and rh>0 and x+rw<=dw and y+rh<=dh,'Invalid provider portrait bounds')
    corners=np.array([[p['x'],h-p['y']] for p in g['documentPosition']],dtype=np.float64)
    require(corners.shape==(4,2) and np.isfinite(corners).all(),'Invalid provider document position')
    require(np.all(corners>=0) and np.all(corners<=[w,h]),'Provider document outside original')
    sides=np.roll(corners,-1,axis=0)-corners
    turns=sides[:,0]*np.roll(sides,-1,axis=0)[:,1]-sides[:,1]*np.roll(sides,-1,axis=0)[:,0]
    require(np.all(turns>0) or np.all(turns<0),'Nonconvex provider document')
    matrix=cv2.getPerspectiveTransform(np.float32([[0,0],[dw,0],[dw,dh],[0,dh]]),corners.astype(np.float32))
    q=np.array([[x,y,1],[x+rw,y,1],[x+rw,y+rh,1],[x,y+rh,1]])@matrix.T
    require(np.isfinite(q).all() and (np.all(q[:,2]>0) or np.all(q[:,2]<0)),'Singular portrait projection')
    ring=(q[:,:2]/q[:,2,None]).tolist()
    return matrix,ring+[ring[0]]


def registration_correlation(original,document,matrix):
    h,w=document.shape[:2]
    # Explicit provider comparison derivative, never substituted for original evidence.
    projected=cv2.warpPerspective(original,np.linalg.inv(matrix),(w,h))
    correlation=float(np.corrcoef(projected.ravel(),document.ravel())[0,1])
    require(np.isfinite(correlation),'No measurable registration')
    return correlation


def prepare(report,baseline,edges,output,minimum_correlation=.98):
    require(.98<=minimum_correlation<=1,'Registration admission must be at least 0.98')
    report,baseline,edges,output=map(Path,(report,baseline,edges,output))
    raw=report.read_bytes();r=strict_json(raw);p=r['portrait'];g=p['geometry']
    require(g is not None,'Provider portrait geometry was not retained')
    rgb,_,hashes=load_native(baseline);h,w=rgb.shape[:2]
    require(r['sourceSHA256']==p['sourceSHA256']==hashes['front-original.heic'],'Wrong original image')
    require(r.get('callbackAction')=='complete' and r.get('resultPresent') is True,'Incomplete provider result')
    require(p['pageIndex']==g['pageIndex']==g['originalPageIndex']==0,'Unsupported provider page')
    portrait=base64.b64decode(p['data'],validate=True)
    require(digest(portrait)==p['sha256'],'Portrait hash mismatch')
    with Image.open(io.BytesIO(portrait)) as im:
        im.load();require(im.format=='PNG' and im.size==(p['pixelWidth'],p['pixelHeight']),'Portrait raster mismatch')
    sdk=strict_json(r['sdkResultJSON'])
    fields=[f for f in sdk['GraphicResult']['pArrayFields'] if f['FieldType']==201 and f['sourceType']==p['sourceType'] and f['page_idx']==p['pageIndex'] and f['LightType']==p['lightType']]
    require(len(fields)==1,'Ambiguous primary portrait field')
    require(fields[0]['FieldRect']==dict(left=g['left'],top=g['top'],right=g['left']+g['width'],bottom=g['top']+g['height']),'Portrait geometry differs from provider field')
    positions=[v for v in sdk['DocumentPosition'] if v['page_idx']==g['pageIndex']]
    require(len(positions)==1,'Ambiguous document position')
    position=positions[0]
    require([position[k] for k in ('LeftTop','RightTop','RightBottom','LeftBottom')]==g['documentPosition'] and position['Width']==g['documentWidth'] and position['Height']==g['documentHeight'],'Document geometry differs from provider result')
    documents=[f for f in sdk['GraphicResult']['pArrayFields'] if f['FieldType']==207 and f['sourceType']==1 and f['page_idx']==g['pageIndex']]
    require(len(documents)==1,'Ambiguous provider document raster')
    document_bytes=base64.b64decode(documents[0]['image']['image'],validate=True)
    with Image.open(io.BytesIO(document_bytes)) as im:
        require(im.size==(g['documentWidth'],g['documentHeight']),'Provider document dimensions disagree')
        document=np.array(im.convert('RGB'))
    matrix,ring=project_geometry(g,(w,h));correlation=registration_correlation(rgb,document,matrix);del rgb
    require(correlation>=minimum_correlation,'Provider-to-original pixel registration failed')
    _,points,offsets,_,_=load_dataset(edges,source_hashes=hashes)
    metrics=measurements(ring,(w,h),points,offsets)
    provenance=dict(sourceSHA256=p['sourceSHA256'],portraitSHA256=p['sha256'],reportSHA256=digest(raw),
      providerDocumentSHA256=digest(document_bytes),geometry=g,
      documentToSource=matrix.ravel().tolist(),coordinateConversion='provider_position_y_to_upright_height_minus_y',
      registrationCorrelation=correlation,minimumRegistrationCorrelation=minimum_correlation,
      registrationScope='all_provider_document_pixels_against_projection_of_full_original',
      extractorVersion=p['extractorVersion'])
    files={'portrait.png':portrait,'provenance.json':encoded(provenance)}
    manifest=dict(schemaVersion=1,type='retained_portrait_regions',sourceHashes=hashes,
      edgeManifestSHA256=digest((edges/'manifest.json').read_bytes()),sourceSize=[w,h],
      outcomes=[dict(outcome='providerPortraitRegistered')],
      candidates=[dict(recordID=p['sha256'],image='portrait.png',role='printedPortrait',
        imagePixelWidth=p['pixelWidth'],imagePixelHeight=p['pixelHeight'],sourcePolygon=ring,metrics=metrics)],
      implementationSHA256=digest(Path(__file__).read_bytes()),
      interpretation='Primary printed portrait from the provider graphic. Source registration checked against image pixels; not an authenticity result.',
      artifacts={n:dict(sha256=digest(b),bytes=len(b)) for n,b in files.items()})
    require(report.read_bytes()==raw,'Report changed during preparation')
    files['manifest.json']=encoded(manifest);publish_directory(output,files)
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('report','baseline','edges','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=prepare(args.report,args.baseline,args.edges,args.output)
    print('Published registered printed portrait:',args.output)
