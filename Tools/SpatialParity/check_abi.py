#!/usr/bin/env python3
"""Exercise the built private C ABI with synthetic pixels; never reads a capture."""
import ctypes as c
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
framework = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'ThirdParty/CaptureBridge/IdentityEvidenceOpenCVBridge.xcframework/macos-arm64_x86_64/IdentityEvidenceOpenCVBridge.framework/IdentityEvidenceOpenCVBridge'
lib = c.CDLL(str(framework))
class Point(c.Structure):
    _fields_ = [('x', c.c_int32), ('y', c.c_int32)]
handle = c.c_void_p
lib.IEOpenCVAnalyzeCardRGB.argtypes = [c.POINTER(c.c_uint8), c.c_size_t, c.c_int32, c.c_int32, c.c_size_t, c.POINTER(c.c_double), c.POINTER(handle)]
lib.IEOpenCVAnalyzeCardRGB.restype = c.c_int32
for name, element in [('Points', Point), ('Offsets', c.c_uint64), ('Mask', c.c_uint8)]:
    function = getattr(lib, 'IEOpenCVCardAnalysis' + name)
    function.argtypes = [handle, c.POINTER(c.c_size_t)]
    function.restype = c.POINTER(element)
lib.IEOpenCVCardAnalysisRelease.argtypes = [handle]
lib.IEOpenCVCardAnalysisRelease.restype = None
width, height = 96, 80
raw = bytes(channel for y in range(height) for x in range(width)
            for channel in ([210, 190, 160] if 20 <= x < 76 and 18 <= y < 62 else [20, 30, 40]))
pixels = (c.c_uint8 * len(raw)).from_buffer_copy(raw)
prior = (c.c_double * 8)(20, 18, 76, 18, 76, 62, 20, 62)
def invoke(w=width, h=height, stride=width*3, length=len(raw), image=pixels, corners=prior):
    result = handle(0x1)
    status = lib.IEOpenCVAnalyzeCardRGB(image, length, w, h, stride, corners, c.byref(result))
    return status, result
for options, expected in [({'image': None}, 1), ({'corners': None}, 1), ({'w': 0}, 1),
                          ({'w': -1}, 1), ({'h': 4}, 1), ({'length': len(raw)-1}, 1),
                          ({'stride': width*3-1}, 1), ({'stride': c.c_size_t(-1).value}, 1),
                          ({'w': 4032, 'h': 3024, 'stride': 12096}, 1),
                          ({'w': 30000, 'h': 30000, 'stride': 90000}, 2),
                          ({'corners': (c.c_double*8)(float('nan'),18,76,18,76,62,20,62)}, 1)]:
    status, result = invoke(**options)
    assert status == expected and result.value is None, (options, status)
assert lib.IEOpenCVAnalyzeCardRGB(pixels,len(raw),width,height,width*3,prior,None) == 1
for suffix in ['Points', 'Offsets', 'Mask']:
    count = c.c_size_t(999)
    assert not getattr(lib, 'IEOpenCVCardAnalysis'+suffix)(None,c.byref(count)) and count.value == 0
lib.IEOpenCVCardAnalysisRelease(None)
def analyze(_):
    status, result = invoke()
    assert status == 0 and result.value
    try:
        count = c.c_size_t()
        p = lib.IEOpenCVCardAnalysisPoints(result,c.byref(count))
        points = tuple((p[i].x,p[i].y) for i in range(count.value))
        assert len(points) > 0
        assert all(0 <= x < width and 0 <= y < height for x,y in points)
        o = lib.IEOpenCVCardAnalysisOffsets(result,c.byref(count))
        offsets = tuple(o[i] for i in range(count.value))
        assert offsets[0] == 0 and offsets[-1] == len(points)
        assert all(a < b for a,b in zip(offsets,offsets[1:]))
        m = lib.IEOpenCVCardAnalysisMask(result,c.byref(count))
        assert count.value == width*height
        mask = bytes(m[:count.value])
        assert set(mask) == {0,1}
        assert mask[40*width+48] == 1 and mask[0] == 0
        return points, offsets, mask
    finally:
        lib.IEOpenCVCardAnalysisRelease(result)
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(analyze,range(8)))
assert all(result == results[0] for result in results)
assert bytes(pixels) == raw and tuple(prior) == (20,18,76,18,76,62,20,62)
print('PASS built C ABI: malformed inputs, 12MP passes arithmetic preflight, unrepresentable graph refused, output reset, null getters/release, full buffers, immutable inputs, 8 deterministic concurrent analyses')
