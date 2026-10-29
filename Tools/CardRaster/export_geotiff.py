#!/usr/bin/env python3
"""Losslessly package one retained ID-1 raster in local card coordinates."""
from manifest_schema import structure_manifest
import argparse
import base64
import re
import hashlib
import json
import math
import platform
import tempfile
import sys
from pathlib import Path
import numpy as np
import rasterio
from rasterio import Affine
from rasterio.crs import CRS
from rasterio.enums import ColorInterp
from PIL import Image, ImageCms, __version__ as pillow_version
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from CardBoundary.publication import publish_directory

WKT = 'LOCAL_CS["Nominal ID-1 GIS plane; x right; y up",LOCAL_DATUM["Nominal card origin",32767],UNIT["millimetre",0.001],AXIS["Card x",EAST],AXIS["GIS y",NORTH]]'
CHANNELS = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def verify(path, pixels, transform):
    # Disable auxiliary metadata: spatial information must live in the TIFF.
    with rasterio.Env(GDAL_PAM_ENABLED='NO'):
        with rasterio.open(path) as ds:
            require(ds.count == 4 and ds.dtypes == ('uint8',)*4, 'Channel/type mismatch')
            actual = ds.read()
            changed = int(np.count_nonzero(actual != pixels))
            require(changed == 0, f'{changed} channel values changed')
            require(ds.transform == transform, 'Affine transform mismatch')
            require(ds.crs is not None and 'LOCAL_CS' in ds.crs.to_wkt(), 'Missing local CRS')
            units = re.search(r'UNIT\["[^"]+",([0-9.eE+-]+)', ds.crs.to_wkt())
            require(units is not None and math.isclose(float(units[1]), .001), 'Units are not millimeters')
            require('NORTH' in ds.crs.to_wkt(), 'Expected GIS y-up axis')
            require(ds.tags(ns='COLOR_PROFILE').get('SOURCE_ICC_PROFILE') is not None, 'Missing ICC profile')
            require(ds.colorinterp == CHANNELS, 'RGBA interpretation mismatch')
            require(ds.is_tiled and ds.block_shapes == [(512,512)]*4, 'Tile layout mismatch')
            require(ds.compression.value == 'DEFLATE', 'Compression mismatch')
            require(ds.nodata is None, 'Unexpected nodata value')
            require(ds.tags()['AREA_OR_POINT'] == 'Area', 'Pixel convention mismatch')
            return {'allChannelValuesEqual': True, 'channelValuesCompared': int(pixels.size),
                    'pixelsCompared': int(pixels.shape[1]*pixels.shape[2]),
                    'crsReadBackWKT': ds.crs.to_wkt(),
                    'unitsToMeters': float(units[1]),
                    'gdalGeoTransform': list(ds.transform.to_gdal()),
                    'firstPixelCenterGISMillimeters': list(ds.xy(0,0)),
                    'lastPixelCenterGISMillimeters': list(ds.xy(ds.height-1,ds.width-1)),
                    'internalGeoreferencingOnly': True}

def export(baseline, destination):
    require(not destination.exists() and not destination.is_symlink(), 'Output already exists; choose a new directory')
    paths = {name: baseline / name for name in
             ('front-original.heic','front-rectified.png','front-geometry.json')}
    hashes = {name: sha(path) for name,path in paths.items()}
    metadata = json.loads(paths['front-geometry.json'].read_text())
    d = metadata['derivation']; g = d['id1Geometry']
    require(hashes['front-original.heic'] == d['sourceSHA256'], 'Original hash mismatch')
    require(hashes['front-rectified.png'] == d['outputSHA256'], 'Rectified hash mismatch')
    require(d['operation'] == 'id1Normalization', 'Expected ID-1 normalized input')
    with Image.open(paths['front-rectified.png']) as image:
        require(image.mode == 'RGBA', 'Expected RGBA; conversion is not permitted')
        require(image.info.get('srgb') is not None, 'Expected declared sRGB PNG')
        pixels = np.moveaxis(np.array(image),2,0)
    _, height, width = pixels.shape
    require((width,height) == (d['outputPixelWidth'],d['outputPixelHeight']), 'Dimensions mismatch')
    scale = 1/g['outputPixelsPerMillimeter']
    require(scale > 0 and math.isfinite(scale), 'Invalid pixel scale')
    require(math.isclose(width*scale,g['nominalWidthMillimeters']) and
            math.isclose(height*scale,g['nominalHeightMillimeters']), 'Nominal extent mismatch')
    transform = Affine(scale,0,0,0,-scale,0)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.card-raster-',dir=destination.parent) as tmp:
        staged = Path(tmp)/'package'; staged.mkdir()
        target = staged/'front-card.tif'
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        with rasterio.Env(GDAL_PAM_ENABLED='NO'):
            with rasterio.open(target,'w',driver='GTiff',width=width,height=height,
                               count=4,dtype='uint8',crs=CRS.from_wkt(WKT),transform=transform,
                               tiled=True,blockxsize=512,blockysize=512,compress='DEFLATE',
                               predictor=2,interleave='pixel',photometric='RGB',alpha='YES',
                               SOURCE_ICC_PROFILE=base64.b64encode(icc).decode('ascii')) as ds:
                ds.write(pixels)
                ds.colorinterp = CHANNELS
                for i,label in enumerate(('Red','Green','Blue','Alpha'),1):
                    ds.set_band_description(i,label)
                ds.update_tags(AREA_OR_POINT='Area',COLOR_SPACE='sRGB',
                               COORDINATE_CONVENTION=g['coordinateConvention'],
                               CARD_AXIS_X='right',CARD_AXIS_Y='down',CARD_UNITS='millimetres',
                               GIS_AXIS_Y='up',GIS_TO_CARD='card_x = gis_x; card_y = -gis_y',
                               SCALE_STATUS='nominal ID-1; not independent physical measurement',
                               DISTORTION_STATUS=g['distortionStatus'],
                               SOURCE_PNG_SHA256=hashes['front-rectified.png'],
                               ORIGINAL_HEIC_SHA256=hashes['front-original.heic'])
        result = verify(target,pixels,transform)
        with rasterio.open(target) as ds:
            require(base64.b64decode(ds.tags(ns='COLOR_PROFILE')['SOURCE_ICC_PROFILE']) == icc, 'ICC bytes changed')
        result['sRGBProfilePreserved'] = True
        # Independent TIFF decoder confirms every channel sample too.
        with Image.open(target) as check:
            require(check.info.get('icc_profile') == icc, 'Independent TIFF ICC check failed')
            require(np.array_equal(np.moveaxis(np.array(check),2,0),pixels),
                    'Independent Pillow TIFF decode differs')
        result['independentPillowPixelEquality'] = True
        # Negative control: a changed pixel must fail the verifier.
        altered = pixels.copy(); altered[0,0,0] ^= 1
        try:
            verify(target,altered,transform)
        except ValueError as error:
            require(str(error) == '1 channel values changed', 'Unexpected negative-control error')
            result['changedPixelNegativeControlRejected'] = True
        else:
            raise ValueError('Verifier accepted changed pixel')
        require(hashes == {name:sha(path) for name,path in paths.items()}, 'Inputs changed during export')
        manifest = {'schemaVersion':1, 'operation':'Lossless PNG sample repackaging into tiled GeoTIFF',
                    'inputFiles':{name:{'sha256':hashes[name],'bytes':paths[name].stat().st_size} for name in paths},
                    'output':{'file':target.name,'sha256':sha(target),'bytes':target.stat().st_size,
                              'width':width,'height':height,'bands':['red','green','blue','alpha'],
                              'dtype':'uint8','colorSpace':'sRGB','compression':'DEFLATE','tileSize':[512,512]},
                    'coordinateSystem':{'type':'local engineering; no Earth location or EPSG code',
                                        'requestedWKT':WKT,'units':'millimetres','xDirection':'right',
                                        'yDirection':'up','origin':'top-left card edge',
                                        'gisToCard':'card_x = gis_x; card_y = -gis_y',
                                        'cardYDirection':'down',
                                        'cardPixelCenterFormula':'((column + 0.5) / pixelsPerMillimeter, (row + 0.5) / pixelsPerMillimeter)',
                                        'pixelsPerMillimeter':g['outputPixelsPerMillimeter']},
                    'retainedGeometry':metadata,
                    'limitations':['Nominal ID-1 dimensions; not independent size validation',g['distortionStatus'],
                                   'Preserves already resampled PNG; no new resampling or color conversion',
                                   'GIS y is negative below the top edge; card y is its negation',
                                   'GDAL reads the local unit name as unknown; stored meter factor 0.001 defines millimeters'],
                    'tools':{'python':platform.python_version(),'rasterio':rasterio.__version__,
                             'gdal':rasterio.__gdal_version__,'numpy':np.__version__,'pillow':pillow_version,
                             'exportScriptSHA256':sha(Path(__file__))},'verification':result}
        manifest = structure_manifest(manifest)
        manifest['tools']['manifestSchemaSHA256'] = sha(Path(__file__).with_name('manifest_schema.py'))
        (staged/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        publish_directory(destination, {p.name: p.read_bytes() for p in staged.iterdir()})
    print(json.dumps({'output':str(destination),'bytes':manifest['output']['bytes'],'verification':result},indent=2))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    export(args.baseline.resolve(),args.destination.absolute())
