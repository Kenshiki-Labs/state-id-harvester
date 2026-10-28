"""Original-image object layer using GEOS geometry and GDAL rasterization."""
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio import Affine
import shapely
from shapely.geometry import Polygon, box, mapping
from PIL import Image


def build_objects(metadata, output):
    g = metadata['derivation']['id1Geometry']
    width, height = g['sourcePixelWidth'], g['sourcePixelHeight']
    scene = box(0, 0, width, height)
    card = Polygon([(p['x'], p['y']) for p in g['sourceCorners']])
    if not card.is_valid or card.area <= 0 or not scene.covers(card):
        raise ValueError('Invalid or out-of-scene card boundary')
    exterior = scene.difference(card)
    if exterior.geom_type != 'Polygon':
        raise ValueError('Surroundings must be a single polygon')
    if not exterior.is_valid or card.intersection(exterior).area != 0 or not card.union(exterior).equals(scene):
        raise ValueError('Objects do not partition the scene')
    mask = rasterize([(mapping(card), 1)], out_shape=(height, width),
                     transform=Affine.identity(), fill=2, dtype='uint8', all_touched=False)
    counts = np.bincount(mask.ravel(), minlength=3)
    if counts[0] or counts[1] == 0 or counts[2] == 0 or counts.sum() != width*height:
        raise ValueError('Invalid object mask coverage')
    mask_path = output/'objects-mask.png'
    Image.fromarray(mask).save(mask_path)
    with Image.open(mask_path) as reread:
        if not np.array_equal(mask, np.array(reread)):
            raise ValueError('Mask encoding changed labels')
    objects = []
    for label, name, geometry in [(1, 'card', card), (2, 'surroundings', exterior)]:
        objects.append({'id':name,'label':label,'parentId':'scene','boundaryStatus':'proposed',
                        'geometry':mapping(geometry),'areaSquarePixels':geometry.area,
                        'pixelCount':int(counts[label]),'bounds':list(geometry.bounds),
                        'adjacentIds':['surroundings' if label==1 else 'card']})
    result = {'schemaVersion':1,'coordinateSystem':{'type':'image_pixels','origin':'top_left_edge',
               'xDirection':'right','yDirection':'down','width':width,'height':height},
              'sourceSHA256':metadata['derivation']['sourceSHA256'],
              'sourceCorners':g['sourceCorners'], 'objects':objects,
              'mask':{'file':'objects-mask.png','sha256':hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                      'rule':'gdal_polygon_rasterization','allTouched':False,'labels':{'1':'card','2':'surroundings'}},
              'tools':{'shapely':shapely.__version__,'geos':shapely.geos_version_string,
                       'rasterio':rasterio.__version__,'gdal':rasterio.__gdal_version__},
              'verification':{'scenePartition':True,'maskCoveragePixels':width*height,'maskRoundTrip':True}}
    (output/'objects.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
