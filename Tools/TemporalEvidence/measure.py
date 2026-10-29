"""Native-pixel descriptive measurements and explicitly bracketed sensor alignment."""
import base64
from bisect import bisect_left
from fractions import Fraction
import math
import plistlib
import numpy as np
from PIL import Image
from contract import finite

MAX_SENSOR_DISTANCE_SECONDS = 0.025  # Display join bound, not a handling classifier.
GAP_SECONDS = 0.05  # Report every interval above 50 ms, never discard its frames.


def time_key(timestamp):
    return timestamp['clock'], timestamp['epoch'], Fraction(timestamp['value'], timestamp['timescale'])


def alignment(run):
    anchors = [event['clockCorrelation'] for event in run['events'] if event.get('clockCorrelation')]
    # A restart/reset inside a journal cannot borrow an anchor from another epoch.
    resets = [event for event in run['events'] if event['kind'] in
              ('clock_epoch_started', 'clock_changed', 'motion_issue', 'frame_issue')]
    sessions = [e for e in run['events'] if e['kind'] == 'session_started']
    reference_frames = {s.get('referenceFrame') for s in run['motion']}
    if len(anchors) != 1 or resets or len(sessions) != 1 or reference_frames != {'xArbitraryZVertical_rotation_radians_per_second_acceleration_g'}:
        return None
    c = anchors[0]
    if c.get('method') != 'CMClockGetHostTimeClock_brackets_ProcessInfo_systemUptime':
        return None
    try:
        before, after, boot = (finite(c[k]) for k in ('hostBeforeSeconds', 'hostAfterSeconds', 'bootTimeSeconds'))
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if before < 0 or boot < 0 or after < before or after - before > MAX_SENSOR_DISTANCE_SECONDS * 2:
        return None
    offset = before + (after - before) / 2 - boot
    times = [s['bootTimeSeconds'] + offset for s in run['motion']]
    if not math.isfinite(offset) or any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        return None
    return dict(times=times, samples=run['motion'], offset=offset, uncertainty=(after-before)/2)


def phone_at(host, context):
    absent = {'status': 'unavailable'}
    if host is None or not context or not context['times']:
        return absent
    times = context['times']
    if host < times[0] or host > times[-1]:
        return absent
    right = bisect_left(times, host)
    left = max(0, right - 1)
    if times[right] - times[left] > MAX_SENSOR_DISTANCE_SECONDS * 2:
        return absent
    i = min((left, right), key=lambda j: abs(times[j] - host))
    delta = times[i] - host
    if abs(delta) + context['uncertainty'] > MAX_SENSOR_DISTANCE_SECONDS:
        return absent
    sample = context['samples'][i]
    rate = math.degrees(math.hypot(*(sample['rotationRate'][axis] for axis in 'xyz')))
    if not math.isfinite(rate):
        return absent
    return dict(status='aligned', gyroDegreesPerSecond=rate, sampleHostTimeSeconds=times[i],
                alignmentDeltaSeconds=delta, clockUncertaintySeconds=context['uncertainty'],
                sourceMotionRecordID=sample['recordID'], sampleBootTimeSeconds=sample['bootTimeSeconds'])


def raster(frame, raw):
    w, h = frame['width'], frame['height']
    a = np.frombuffer(raw, np.uint8)
    y = a[:w*h].reshape(h, w)
    # Display conversion only; all measurements use original native luma samples.
    attachments = frame.get('colorAttachmentsPlist')
    matrix = None
    if attachments:
        matrix = plistlib.loads(base64.b64decode(attachments, validate=True)).get('CVImageBufferYCbCrMatrix')
    if matrix == 'ITU_R_601_4':
        uv = a[w*h:].reshape(h//2, w//2, 2).repeat(2, 0).repeat(2, 1).astype(np.float32) - 128
        yy = y.astype(np.float32)
        rgb = np.stack([yy + 1.402 * uv[:, :, 1],
                        yy - .344136 * uv[:, :, 0] - .714136 * uv[:, :, 1],
                        yy + 1.772 * uv[:, :, 0]], 2).clip(0, 255).astype(np.uint8)
        return y, Image.fromarray(rgb), 'native_rgb'
    return y, Image.fromarray(y), 'native_luma'


def metrics(y, previous):
    result = {'meanLuma': float(y.mean()), 'stdLuma': float(y.std()),
              'minimumLuma': int(y.min()), 'maximumLuma': int(y.max()), 'pixelCount': int(y.size)}
    if previous is not None and previous.shape == y.shape:
        result['meanAbsoluteLumaChange'] = float(np.abs(y.astype(np.int16) - previous.astype(np.int16)).mean())
    return result
