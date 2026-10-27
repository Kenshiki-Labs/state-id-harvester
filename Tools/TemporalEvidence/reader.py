"""Verify exported native journal chains before interpreting their observations."""
from collections import defaultdict
from pathlib import Path
from fractions import Fraction
from contract import digest, finite, identifier, integer, read_regular, require, strict_json, timestamp

NORMAL_EVENTS = set('session_started session_stopped geometry still_capture still_retained front turnover back cta camera_session_bound clock_epoch_started document_capture_started turnover_started back_capture_started front_still_retained back_still_retained turnover_requested capture_review back_requested back_capture_armed document_capture_completed configuration_changed retake_requested'.split())
KINDS = {'journeyRecording' + suffix for suffix in ('Start', 'Frame', 'Motion', 'Event', 'Seal')}


class Export:
    def __init__(self, root):
        self.root = Path(root)
        require(not self.root.is_symlink(), 'Export symlink')
        self.index_bytes = read_regular(self.root / 'index.json')
        self.index = strict_json(self.index_bytes)
        version = self.index.get('schemaVersion', 1)
        require(type(version) is int and version in (1, 2), 'Unsupported export version')
        self.records = {}
        self.groups = defaultdict(list)
        for entry in self.index['records']:
            rid = identifier(entry['recordID'])
            require(rid not in self.records, 'Duplicate record ID')
            manifest_bytes = read_regular(self.root / rid / 'manifest.json')
            require(digest(manifest_bytes) == entry['manifestSHA256'], 'Manifest hash mismatch')
            manifest = strict_json(manifest_bytes)
            require(isinstance(manifest, dict), 'Manifest object required')
            self.records[rid] = {'id': rid, 'manifest': manifest, 'entry': entry}
            self.payload(rid)  # Verify even non-journal records; release their bytes immediately.
            kind = manifest.get('recordKind', '')
            if kind.startswith('journeyRecording'):
                require(kind in KINDS, 'Unsupported journal kind')
                self.groups[identifier(manifest['recordingID'])].append(self.records[rid])
        declared = self.index.get('journeyRecordings', {})
        require(set(declared) == set(self.groups), 'Export journal inventory mismatch')
        self.runs = [self.verify_run(rid, rows) for rid, rows in sorted(self.groups.items())]
        for run in self.runs:
            require(declared[run['recordingID']] == run['status'], 'Export status mismatch')

    def payload(self, rid):
        record = self.records[rid]
        raw = read_regular(self.root / rid / 'original.bin')
        require(digest(raw) == record['entry']['originalSHA256'], 'Payload hash mismatch')
        return raw

    def verify_run(self, rid, rows):
        for row in rows:
            m = row['manifest']
            integer(m['ordinal'])
            require(type(m['schemaVersion']) is int and m['schemaVersion'] == 1, 'Unsupported journal version')
            identifier(m['workflowID'])
        rows = sorted(rows, key=lambda row: row['manifest']['ordinal'])
        workflow = rows[0]['manifest']['workflowID']
        frames, motion, events, seal = [], [], [], None
        previous = None
        previous_frame = previous_motion = None
        still_count = 0
        for ordinal, row in enumerate(rows):
            m = row['manifest']; raw = self.payload(row['id'])
            require(seal is None and m['ordinal'] == ordinal, 'Journal ordinal gap/duplicate or data after seal')
            require(m['workflowID'] == workflow, 'Cross-workflow journal')
            require(m.get('previousID') == (previous['id'] if previous else None), 'Broken previous ID')
            require(m.get('previousSHA256') == (previous['manifest']['payloadSHA256'] if previous else None), 'Broken previous hash')
            require(m['payloadSHA256'] == digest(raw), 'Journal payload hash mismatch')
            kind = m['recordKind']
            if ordinal == 0:
                require(kind == 'journeyRecordingStart' and row['id'] == rid, 'Missing journal start')
                start = strict_json(raw)
                require(type(start['schemaVersion']) is int and start['schemaVersion'] == 1, 'Unsupported start version')
                finite(start['startedAt'])
                finite(start['maximumDuration'])
                require(start['maximumDuration'] > 0, 'Invalid duration limit')
                integer(start['maximumDiskBytes'], 1)
                integer(start['maximumPendingBytes'], 1)
            elif kind == 'journeyRecordingFrame':
                frame = dict(m['frame'], recordID=row['id'])
                validate_frame(frame, raw)
                stamp = frame['timestamp']
                current = (frame['sequenceNumber'], (stamp['epoch'], Fraction(stamp['value'], stamp['timescale'])))
                if previous_frame:
                    require(current[0] > previous_frame[0] and current[1][0] == previous_frame[1][0]
                            and current[1][1] > previous_frame[1][1], 'Frame chronology failure')
                previous_frame = current
                frames.append(frame)
            elif kind == 'journeyRecordingMotion':
                samples = strict_json(raw)
                require(isinstance(samples, list) and len(samples) <= 100, 'Invalid motion batch')
                for sample in samples:
                    t = finite(sample['bootTimeSeconds'])
                    require(previous_motion is None or t > previous_motion, 'Motion chronology failure')
                    for field, axes in [('rotationRate', 'xyz'), ('gravity', 'xyz'), ('userAcceleration', 'xyz'), ('attitude', 'xyzw')]:
                        for axis in axes:
                            finite(sample[field][axis])
                    previous_motion = t
                    motion.append(dict(sample, recordID=row['id'], journalOrdinal=ordinal))
            elif kind == 'journeyRecordingEvent':
                event = strict_json(raw)
                if event.get('geometry') is not None:
                    validate_geometry(event['geometry'], event.get('timestamp'))
                if event.get('hostTimeSeconds') is not None:
                    finite(event['hostTimeSeconds'])
                if event['kind'] in ('session_started', 'clock_epoch_started', 'clock_changed'):
                    previous_frame = previous_motion = None
                if event['kind'] == 'frame_issue' and event.get('detail') == 'frame_clock_discontinuity':
                    previous_frame = None
                if event['kind'] == 'motion_issue' and event.get('detail') == 'motion_clock_discontinuity':
                    previous_motion = None
                if event['kind'] == 'still_retained':
                    self.verify_still(event['binding'], rid, workflow)
                    still_count += 1
                events.append(dict(event, recordID=row['id'], journalOrdinal=ordinal))
            elif kind == 'journeyRecordingSeal':
                seal = strict_json(raw)
            else:
                raise ValueError('Unexpected journal start/kind')
            previous = row
        issues = sum(event['kind'] not in NORMAL_EVENTS for event in events)
        if seal:
            for field, value in [('frameCount', len(frames)), ('motionSampleCount', len(motion)), ('issueCount', issues), ('retainedStillCount', still_count)]:
                require(integer(seal[field]) == value, 'Seal count mismatch: ' + field)
            for field in ('refusedFrames', 'refusedMotionSamples'):
                integer(seal[field])
            for field in ('coalescedGapEvents', 'platformDropCallbacks'):
                if seal.get(field) is not None:
                    integer(seal[field])
            if seal.get('firstLossTimestamp') is not None:
                timestamp(seal['firstLossTimestamp'])
            if seal.get('firstLossHostTimeSeconds') is not None:
                finite(seal['firstLossHostTimeSeconds'])
            if seal.get('firstLossReason') is not None:
                require(isinstance(seal['firstLossReason'], str) and bool(seal['firstLossReason']),
                        'Invalid first loss reason')
            require(seal['status'] in ('complete', 'partial'), 'Unknown seal status')
            if seal['status'] == 'complete':
                require(seal['reason'] == 'completed' and not issues and frames and motion and still_count
                        and not seal['refusedFrames'] and not seal['refusedMotionSamples']
                        and all(seal.get(k) is None for k in ('firstLossReason', 'firstLossTimestamp', 'firstLossHostTimeSeconds'))
                        and not seal.get('coalescedGapEvents') and not seal.get('platformDropCallbacks'), 'False complete seal')
        return dict(recordingID=rid, workflowID=workflow, frames=frames, motion=motion, events=events,
                    status=seal['status'] if seal else 'interrupted', reason=seal['reason'] if seal else 'unsealed',
                    frameCount=len(frames), motionSampleCount=len(motion), issueCount=issues,
                    refusedFrames=seal['refusedFrames'] if seal else None,
                    refusedMotionSamples=seal['refusedMotionSamples'] if seal else None,
                    **{k: seal.get(k) if seal else None for k in ('firstLossTimestamp',
                       'firstLossHostTimeSeconds', 'firstLossReason', 'coalescedGapEvents', 'platformDropCallbacks')})

    def verify_still(self, binding, rid, workflow):
        sid = identifier(binding['attemptID'])
        require(sid in self.records, 'Missing linked still')
        row = self.records[sid]; m = row['manifest']; ref = m['journeyRecording']
        require(m['captureID'] == sid and m['workflowID'] == workflow and ref['workflowID'] == workflow
                and ref['recordingID'] == rid, 'Cross-linked still')
        require(ref['startSHA256'] == self.records[rid]['manifest']['payloadSHA256'], 'Still start hash mismatch')
        require(binding['stillSHA256'] == row['entry']['originalSHA256'] == m['fidelity']['sha256'], 'Still hash mismatch')
        require(m['captureTimestamp'] == binding['stillTimestamp'] and ({'License front': 'front', 'License back': 'back', 'US passport card front': 'front', 'US passport card back': 'back', 'Passport page': 'front', 'Other document': 'front'}.get(m['profile']) == binding['side']), 'Still binding mismatch')
        require(m['sessionID']['rawValue'] == binding['sessionID'], 'Still session mismatch')


def validate_frame(frame, raw):
    width, height = integer(frame['width'], 1), integer(frame['height'], 1)
    integer(frame['sequenceNumber']); timestamp(frame['timestamp'])
    if frame.get('geometry') is not None:
        validate_geometry(frame['geometry'], frame['timestamp'])
    camera = frame.get('camera')
    if camera is not None:
        for key in ('rotationDegrees', 'iso', 'exposureDurationSeconds', 'zoomFactor', 'lensPosition', 'readbackHostTimeSeconds'):
            if camera.get(key) is not None:
                finite(camera[key])
    if frame.get('hostTimeSeconds') is not None:
        finite(frame['hostTimeSeconds'])
    require(frame['sha256'] == digest(raw), 'Frame hash mismatch')
    require(frame['pixelFormat'] == 875704422 and width % 2 == 0 and height % 2 == 0,
            'Only native full-range bi-planar 420f supported')
    planes = frame['planes']; require(len(planes) == 2, 'Invalid NV12 plane count')
    offset = 0
    for plane, w, h in zip(planes, (width, width // 2), (height, height // 2)):
        for field in ('width', 'height', 'packedBytesPerRow', 'offset', 'byteCount'):
            integer(plane[field])
        require(plane['width'] == w and plane['height'] == h and plane['packedBytesPerRow'] == width,
                'Invalid native plane dimensions')
        require(integer(plane['sourceBytesPerRow'], width) >= width and plane['offset'] == offset
                and plane['byteCount'] == width * h, 'Invalid plane layout')
        offset += plane['byteCount']
    require(offset == len(raw), 'Native payload length mismatch')


def validate_geometry(geometry, source_timestamp):
    observed = geometry['observationTimestamp']
    timestamp(observed)
    if source_timestamp is not None:
        timestamp(source_timestamp)
        require(observed['epoch'] == source_timestamp['epoch']
                and Fraction(observed['value'], observed['timescale'])
                == Fraction(source_timestamp['value'], source_timestamp['timescale']),
                'Geometry source timestamp mismatch')
    require(geometry['coordinateSpace'] == 'normalized_delivered_video_buffer_top_left',
            'Unsupported geometry coordinates')
    if geometry.get('confidence') is not None:
        finite(geometry['confidence'])
    quad = geometry.get('quadrilateral')
    if quad is not None:
        for corner in ('topLeft', 'topRight', 'bottomLeft', 'bottomRight'):
            finite(quad[corner]['x']); finite(quad[corner]['y'])
