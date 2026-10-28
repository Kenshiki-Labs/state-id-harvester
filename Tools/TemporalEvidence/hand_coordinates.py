"""MediaPipe upright normalized observations mapped to native source pixel edges.

The inverse of the eight EXIF orientation operations (the same operations used by
Pillow ImageOps.exif_transpose). No crop, rectification or resized input is assumed.
The retained provider coordinates, including off-image landmarks, are unchanged.
"""
from contract import finite, integer, require


def source_transform(width, height, orientation):
    integer(width, 1)
    integer(height, 1)
    require(type(orientation) is int and 1 <= orientation <= 8, 'Unsupported hand source orientation')
    matrices = {
        1: [width, 0, 0, 0, height, 0],
        2: [-width, 0, width, 0, height, 0],
        3: [-width, 0, width, 0, -height, height],
        4: [width, 0, 0, 0, -height, height],
        5: [0, width, 0, height, 0, 0],
        6: [0, width, 0, -height, 0, height],
        7: [0, -width, width, -height, 0, height],
        8: [0, -width, width, height, 0, 0],
    }
    return dict(fromSpace='upright_normalized_top_left', toSpace='native_pixel_edges_top_left',
                affine=matrices[orientation], sourceWidth=width, sourceHeight=height,
                exifOrientation=orientation,
                uprightWidth=height if orientation >= 5 else width,
                uprightHeight=width if orientation >= 5 else height)


def source_point(point, transform):
    x, y = finite(point['x']), finite(point['y'])
    a, b, c, d, e, f = transform['affine']
    return [finite(a*x + b*y + c), finite(d*x + e*y + f)]
