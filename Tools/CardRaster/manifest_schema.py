"""Version 2 manifest: typed metadata rather than explanatory prose."""
from copy import deepcopy


def structure_manifest(source):
    if source['schemaVersion'] != 1:
        raise ValueError('Expected manifest version 1')
    result = deepcopy(source)
    result['schemaVersion'] = 2
    result['operation'] = 'png_to_geotiff'
    result['processing'] = {'resampled': False, 'colorConverted': False, 'compressionLossless': True}
    cs = result['coordinateSystem']
    cs['type'] = 'local_engineering'
    cs['units'] = 'mm'
    cs['origin'] = {'reference': 'card_top_left_edge', 'x': 0, 'y': 0}
    cs.pop('gisToCard')
    cs['gisToCardAffine'] = [1, 0, 0, 0, -1, 0]
    cs['affineCoefficientOrder'] = ['a', 'b', 'c', 'd', 'e', 'f']
    cs.pop('cardPixelCenterFormula')
    cs['pixelCenterOffset'] = {'column': 0.5, 'row': 0.5}
    cs['pixelIndexBase'] = 0
    g = result['retainedGeometry']['derivation']['id1Geometry']
    g['coordinateConvention'] = {'origin': 'top_left_edge', 'xDirection': 'right',
                                 'yDirection': 'down', 'firstPixelCenter': [0.5, 0.5]}
    g['distortionStatus'] = 'uncalibrated'
    g['rasterEncoding'] = {'colorSpace': 'sRGB', 'channels': 'RGBA', 'bitsPerChannel': 8,
                           'resampling': 'bilinear', 'resamplingPasses': 1}
    result.pop('limitations')
    result['measurement'] = {'scaleBasis': 'nominal_id1', 'lensCalibration': 'uncalibrated'}
    return result
