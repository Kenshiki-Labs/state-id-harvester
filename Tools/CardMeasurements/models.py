"""Optional models computed only after the complete unsmoothed dataset exists."""
import argparse
import io
import sys
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from CardMeasurements.measure import project, load_dataset
from CardEdges.dataset import digest,json_bytes
from CardBoundary.json_contract import strict_json
from CardBoundary.publication import publish_directory


def corner_distance(radius, local):
    q=radius-local
    return np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(np.max(q,axis=1),0)-radius


def fit_radius(local):
    fit=least_squares(lambda r:corner_distance(r[0],local),[3.],bounds=(0.,26.99),loss='soft_l1',f_scale=.02,xtol=1e-12,ftol=1e-12,gtol=1e-12)
    if not fit.success:raise ValueError('Radius fit failed')
    errors=corner_distance(fit.x[0],local)
    return {'radiusMillimeters':float(fit.x[0]),'pointCount':len(local),'rmsMillimeters':float(np.sqrt(np.mean(errors**2))),
            'maximumAbsoluteResidualMillimeters':float(np.max(np.abs(errors))),
            'status':'conditional_on_perimeter_and_registration'}


def checks(corners):
    result=[]
    for i,c in enumerate(corners):
        a=corners[(i-1)%4]-c;b=corners[(i+1)%4]-c;a/=np.linalg.norm(a);b/=np.linalg.norm(b)
        p3=c+3*a;p4=c+4*b;distance=float(np.linalg.norm(p3-p4))
        result.append({'corner':i,'startMillimeters':c.tolist(),'point3Millimeters':p3.tolist(),'point4Millimeters':p4.tolist(),
            'crossDistanceMillimeters':distance,'residualFrom5Millimeters':distance-5,'angleDegrees':float(np.degrees(np.arccos(np.clip(a@b,-1,1))))})
    return result


def run(measurements,rectification,out):
    measurements,rectification,out=map(Path,(measurements,rectification,out))
    raw=(measurements/'manifest.json').read_bytes();m=strict_json(raw)
    m,files=load_dataset(measurements,m['sourceHashes'],m['boundaryId'],m['rectificationManifestSHA256'])
    raw=files['manifest.json']
    rectraw=(rectification/'manifest.json').read_bytes()
    if digest(rectraw)!=m['rectificationManifestSHA256']:raise ValueError('Registration mismatch')
    rect=strict_json(rectraw);p=np.load(io.BytesIO(files['perimeter.npy']),allow_pickle=False)
    mm=p[p[:,7]==0,4:6];corners=np.array([[0,0],[85.6,0],[85.6,53.98],[0,53.98]])
    nearest=np.argmin(np.linalg.norm(mm[:,None,:]-corners[None,:,:],axis=2),axis=1)
    signs=np.array([[1,1],[-1,1],[-1,-1],[1,-1]])
    radii=[]
    for i,c in enumerate(corners):
        local=(mm[nearest==i]-c)*signs[i]
        radii.append(dict(corner=i,**fit_radius(local)))
    sourcecorners=np.array(rect['plane']['corners'])
    mapped=project(rect['transforms']['sourceToCardMillimeters'],sourcecorners)
    result={'schemaVersion':1,'type':'id_cadastral_measurement_models','measurementManifestSHA256':digest(raw),
        'rectificationManifestSHA256':digest(rectraw),'boundaryId':m['boundaryId'],
        'cornerRadii':radii,'cornerRadiusModel':{'shape':'circle_tangent_to_registered_sides','assignment':'nearest_known_frame_corner',
        'allExteriorUnitVerticesUsed':len(mm),'loss':'soft_l1','lossScaleMillimeters':.02,'radiusBoundsMillimeters':[0,26.99],
        'initialRadiusMillimeters':3,'fitOrder':'after_complete_scanline_publication'},
        'sideLines':rect['plane']['lines'],'virtualSourceCorners':sourcecorners.tolist(),'virtualCardCornersMillimeters':mapped.tolist(),
        'rightAngle345Checks':checks(mapped),'expectedDiagonalMillimeters':float(np.hypot(85.6,53.98)),
        'frameDiagonalMillimeters':[float(np.linalg.norm(mapped[2]-mapped[0])),float(np.linalg.norm(mapped[3]-mapped[1]))],
        'checkScope':'registration_consistency','physicalPerimeterStatus':'unresolved',
        'implementationSHA256':digest(Path(__file__).read_bytes())}
    publish_directory(out,{'models.json':json_bytes(result)})
    print(json_bytes(result).decode())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('measurements');p.add_argument('rectification');p.add_argument('out');a=p.parse_args();run(a.measurements,a.rectification,a.out)
