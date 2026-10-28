"""Boundary-derived card plane; preserve observed geometry independently."""
import argparse
import io
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageCms
from scipy.optimize import least_squares
import scipy
from shapely.geometry import Polygon, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from native_input import load_native, verify_unchanged
from validate_dataset import validate_dataset
from dataset import json_bytes, digest
from json_contract import strict_json
from publication import publish_directory

NOMINAL = np.array([85.60, 53.98])


def require(ok, message):
    if not ok:
        raise ValueError(message)


def project(matrix, points):
    points = np.asarray(points, dtype=np.float64)
    mapped = np.column_stack([points, np.ones(len(points))]) @ np.asarray(matrix).T
    require(np.all(np.isfinite(mapped)) and np.all(np.abs(mapped[:, 2]) > 1e-12), 'Singular point mapping')
    return mapped[:, :2] / mapped[:, 2:]


def boundary_positions(geometry):
    """Every exterior unit pixel edge midpoint; canonical ordering, no sampling."""
    require(geometry.get('type') == 'Polygon' and shape(geometry).is_valid, 'Invalid observed polygon')
    ring = np.asarray(geometry['coordinates'][0], dtype=np.float64)
    require(np.isfinite(ring).all() and np.array_equal(ring, np.round(ring)), 'Expected native integer pixel edges')
    points = []
    for a, b in zip(ring[:-1], ring[1:]):
        delta = b-a
        require(np.count_nonzero(delta) == 1, 'Expected nonzero axis-aligned pixel edge')
        length = int(np.abs(delta).sum())
        points.append(a + (np.arange(length)[:, None] + .5) * delta / length)
    points = np.concatenate(points)
    return points[np.lexsort((points[:, 1], points[:, 0]))]


def fit_boundary(geometry, prior_corners, corner_fraction=.1):
    """All unit edges classified; all eligible positions enter each robust solve."""
    require(math.isfinite(corner_fraction) and 0 <= corner_fraction < .4, 'Invalid corner support fraction')
    prior = np.asarray(prior_corners, dtype=np.float64)
    require(prior.shape == (4,2) and np.isfinite(prior).all(), 'Expected four finite prior corners')
    quad = Polygon(prior)
    require(quad.is_valid and quad.area > 0 and quad.equals(quad.convex_hull) and
            len(quad.convex_hull.exterior.coords) == 5, 'Invalid prior quadrilateral')
    positions = boundary_positions(geometry)
    directions = np.roll(prior, -1, axis=0)-prior
    lengths = np.linalg.norm(directions, axis=1)
    along = np.stack([(positions-a) @ d / (d@d) for a,d in zip(prior,directions)], axis=1)
    closest = prior[None,:,:] + np.clip(along,0,1)[:,:,None]*directions[None,:,:]
    assignments = np.argmin(np.linalg.norm(positions[:,None,:]-closest,axis=2),axis=1)
    support = np.zeros(len(positions),dtype=bool)
    residuals = np.zeros(len(positions)); weights = np.zeros(len(positions))
    lines = []
    for index in range(4):
        assigned = assignments == index
        eligible = assigned & (along[:,index] >= corner_fraction) & (along[:,index] <= 1-corner_fraction)
        selected = positions[eligible]
        require(len(selected) >= 3 and np.ptp(along[eligible,index]) >= .4, 'Insufficient distributed edge support')
        support |= eligible
        center = selected.mean(axis=0)
        local = selected-center
        _, _, vt = np.linalg.svd(local,full_matrices=False)
        normal = vt[-1]
        if normal @ (center-prior.mean(axis=0)) < 0: normal = -normal
        initial = local@normal
        # Quantization floor is half a native pixel, not a physical region size.
        scale = max(.5, float(1.4826*np.median(np.abs(initial-np.median(initial)))))
        angle = math.atan2(normal[1],normal[0])
        def residual(parameters):
            theta, offset = parameters
            return local @ np.array([math.cos(theta),math.sin(theta)])-offset
        solution = least_squares(residual, [angle,0.],loss='soft_l1',f_scale=scale,
                                 method='trf',ftol=1e-12,xtol=1e-12,gtol=1e-12,max_nfev=1000)
        require(solution.success and np.isfinite(solution.x).all(), 'Edge fit did not converge')
        normal = np.array([math.cos(solution.x[0]),math.sin(solution.x[0])])
        offset = float(normal@center + solution.x[1])
        values = positions@normal-offset
        residuals[assigned] = values[assigned]
        weights[eligible] = 1/np.sqrt(1+(values[eligible]/scale)**2)
        lines.append({'normal':normal.tolist(),'offset':offset,'supportCount':int(eligible.sum()),
                      'assignedCount':int(assigned.sum()),'softL1ScaleSourcePixels':scale,
                      'supportRMSPixels':float(np.sqrt(np.mean(values[eligible]**2))),
                      'supportMedianAbsolutePixels':float(np.median(np.abs(values[eligible]))),
                      'supportP95AbsolutePixels':float(np.percentile(np.abs(values[eligible]),95)),
                      'solverEvaluations':solution.nfev})
    corners = []
    for previous,current in [(3,0),(0,1),(1,2),(2,3)]:
        normals = np.array([lines[previous]['normal'],lines[current]['normal']])
        require(abs(np.linalg.det(normals)) > 1e-6,'Adjacent fitted lines nearly parallel')
        corners.append(np.linalg.solve(normals,[lines[previous]['offset'],lines[current]['offset']]))
    polygon = Polygon(corners)
    require(polygon.is_valid and polygon.area>0 and polygon.equals(polygon.convex_hull),'Invalid fitted plane')
    return {'corners':np.array(corners).tolist(),'lines':lines,'cornerFraction':corner_fraction,
            'perimeterPositionCount':len(positions),'supportCount':int(support.sum()),
            'excludedCornerCount':int((~support).sum())}, {
                'sourcePositions':positions,'edgeIndex':assignments.astype(np.uint8),
                'fitSupport':support,'signedResidualSourcePixels':residuals,'robustInfluence':weights}


def warp_matrix(edge_matrix):
    return np.array([[1,0,-.5],[0,1,-.5],[0,0,1.]]) @ edge_matrix @ np.array([[1,0,.5],[0,1,.5],[0,0,1.]])


def derive_transform(corners, geometry, pixels_per_mm=50):
    require(math.isfinite(pixels_per_mm) and pixels_per_mm>0,'Invalid pixel density')
    target = np.array([[0,0],[NOMINAL[0],0],NOMINAL,[0,NOMINAL[1]]],np.float32)
    source = np.asarray(corners,dtype=np.float64)
    require(source.shape==(4,2) and np.isfinite(source).all() and Polygon(source).is_valid and
            Polygon(source).area>0,'Invalid plane corners')
    card = cv2.getPerspectiveTransform(source.astype(np.float32),target)
    require(np.isfinite(card).all() and abs(np.linalg.det(card))>1e-14,'Singular card transform')
    nominal = np.diag([pixels_per_mm,pixels_per_mm,1.])@card
    observed = np.concatenate([project(nominal,ring) for ring in geometry['coordinates']])
    low = np.floor(np.minimum(observed.min(axis=0),[0,0]))-2
    high = np.ceil(np.maximum(observed.max(axis=0),NOMINAL*pixels_per_mm))+2
    size = (high-low).astype(int)
    require(np.all(size>0) and np.all(size < np.iinfo(np.int32).max),'Invalid output extent')
    edge = np.array([[1,0,-low[0]],[0,1,-low[1]],[0,0,1.]])@nominal
    return {'sourceToRectified':edge,'rectifiedToSource':np.linalg.inv(edge),
            'sourceToCardMillimeters':card,'cardMillimetersToSource':np.linalg.inv(card),
            'width':int(size[0]),'height':int(size[1]),'originCardMillimeters':(low/pixels_per_mm).tolist()}


def rectify(baseline, boundary, output):
    baseline,boundary,output=Path(baseline),Path(boundary),Path(output)
    require(not output.exists() and not output.is_symlink(),'Output exists')
    admitted = validate_dataset(boundary,baseline)
    boundary_bytes=(boundary/'geometry.json').read_bytes()
    require(digest(boundary_bytes)==admitted['boundaryId'],'Boundary changed before fitting')
    geometry=strict_json(boundary_bytes)
    rgb,metadata,hashes=load_native(baseline)
    g=metadata['derivation']['id1Geometry']
    prior=[[p['x'],p['y']] for p in g['sourceCorners']]
    model,diagnostics=fit_boundary(geometry,prior)
    transforms=derive_transform(model['corners'],geometry)
    edge=transforms['sourceToRectified']
    size=(transforms['width'],transforms['height'])
    # One direct resampling of retained upright RGB. No rectified input reuse.
    image=cv2.warpPerspective(rgb,warp_matrix(edge),size,flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
    contour={'type':'Polygon','coordinates':[project(edge,ring).tolist() for ring in geometry['coordinates']]}
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    encoded=io.BytesIO();Image.fromarray(image).save(encoded,format='PNG',icc_profile=icc)
    residual_bytes=io.BytesIO();np.savez_compressed(residual_bytes,**diagnostics)
    files={'rectified.png':encoded.getvalue(),'contour.json':json_bytes(contour),
           'residuals.npz':residual_bytes.getvalue()}
    # Evaluate support selection, without choosing the visually nicest result.
    sensitivity=[]
    for margin in [.05,.15]:
        alternative,_=fit_boundary(geometry,prior,margin)
        sensitivity.append({'cornerFraction':margin,'corners':alternative['corners'],
            'cornerDisplacementPixels':np.linalg.norm(np.array(alternative['corners'])-model['corners'],axis=1).tolist()})
    matrix_fields={k:v.reshape(-1).tolist() for k,v in transforms.items() if isinstance(v,np.ndarray)}
    matrix_fields['sourceToRectifiedPixelCenters']=warp_matrix(edge).reshape(-1).tolist()
    mapped=project(transforms['sourceToCardMillimeters'],model['corners'])
    intended=np.array([[0,0],[85.6,0],[85.6,53.98],[0,53.98]])
    error=float(np.max(np.linalg.norm(mapped-intended,axis=1)))
    require(error<1e-3,'Plane corner mapping failed')
    require(np.all(np.array(contour['coordinates'][0])>=0) and
            np.all(np.array(contour['coordinates'][0])<=size),'Observed contour clipped')
    verify_unchanged(baseline,hashes)
    require(validate_dataset(boundary,baseline)==admitted,'Boundary dataset changed during processing')
    manifest={'schemaVersion':1,'type':'id_cadastral_rectification','boundaryId':admitted['boundaryId'],
        'sourceHashes':hashes,'boundaryManifestSHA256':digest((boundary/'manifest.json').read_bytes()),
        'method':'all_edge_soft_l1_plane','parameters':{'cornerFraction':.1,'loss':'soft_l1','fScale':'max_half_pixel_mad',
        'interpolation':'opencv_inter_linear','pixelsPerMillimeter':50,'paddingPixels':2},
        'output':{'width':size[0],'height':size[1],'pixelsPerMillimeter':50,
                  'originCardMillimeters':transforms['originCardMillimeters'],'nominalCardMillimeters':NOMINAL.tolist()},
        'transforms':matrix_fields,'plane':model,'sensitivity':sensitivity,
        'artifacts':{name:{'path':path,'sha256':digest(files[path])} for name,path in
                      [('image','rectified.png'),('contour','contour.json'),('residuals','residuals.npz')]},
        'implementation':{'opencv':cv2.__version__,'scipy':scipy.__version__,
            'scriptSHA256':digest(Path(__file__).read_bytes())},
        'verification':{'sourceHashesUnchanged':True,'planeCornerMaxErrorMillimeters':error,
                        'observedContourPreserved':True,'nativeInputPixels':int(rgb.shape[0]*rgb.shape[1])},
        'assessment':{'status':'unevaluated','productionIntegration':False}}
    files['manifest.json']=json_bytes(manifest)
    publish_directory(output,files)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('boundary',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args()
    result=rectify(a.baseline,a.boundary,a.output)
    print(json_bytes({'output':result['output'],'plane':result['plane'],'sensitivity':result['sensitivity']}).decode())
