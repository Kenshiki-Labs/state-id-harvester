"""Read source-bound hand derivatives. Landmarks are not handling classifications."""
import math
import re
from PIL import ImageDraw
from contract import digest, finite, identifier, integer, require, strict_json, json_bytes
from hand_coordinates import source_point, source_transform

FRAME_KIND = 'handLandmarkFrame'
SUMMARY_KIND = 'handLandmarkSummary'
EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
         (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
         (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]


def observation(value, source):
    require(isinstance(value, dict), 'Missing hand observation')
    stamp = source['timestamp']
    expected_time = math.floor(float(stamp['value']) / float(stamp['timescale']) * 1000)
    require(integer(value['timestampMilliseconds']) == expected_time, 'Hand timestamp mismatch')
    require(value['coordinateSpace'] == 'upright_normalized_top_left', 'Unsupported hand coordinate space')
    require(value['orientation'] == 1 and type(value['orientation']) is int,
            'Unsupported hand analysis orientation')
    for key, source_key in [('sourceWidth', 'width'), ('sourceHeight', 'height')]:
        require(integer(value[key], 1) == source[source_key], 'Hand analysis dimensions mismatch')
    require(isinstance(value['hands'], list), 'Invalid hands')
    for hand in value['hands']:
        for key in ('normalizedLandmarks', 'worldLandmarks'):
            points = hand[key]
            require(isinstance(points, list) and len(points) == 21, 'Expected 21 hand landmarks')
            for point in points:
                for axis in ('x', 'y', 'z'):
                    finite(point[axis])
                for confidence in ('visibility', 'presence'):
                    if point.get(confidence) is not None:
                        require(0 <= finite(point[confidence]) <= 1, 'Invalid hand confidence')
        require(isinstance(hand['handedness'], list), 'Invalid handedness')
        for category in hand['handedness']:
            require(type(category['index']) is int, 'Invalid handedness index')
            require(0 <= finite(category['score']) <= 1, 'Invalid handedness score')
            for key in ('categoryName', 'displayName'):
                require(category.get(key) is None or isinstance(category[key], str), 'Invalid handedness label')


def frame_result(export, record):
    raw = export.payload(record['id'])
    value = strict_json(raw)
    link = record['manifest']
    require(type(link.get('schemaVersion')) is int and link['schemaVersion'] == 1, 'Unsupported hand manifest schema')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1,
            'Unsupported hand derivative schema')
    source_id = identifier(value['sourceFrameID'])
    source = export.records.get(source_id)
    require(source is not None and source['manifest'].get('recordKind') == 'journeyRecordingFrame',
            'Missing hand source frame')
    metadata = source['manifest']['frame']
    require(json_bytes(value['sourceMetadata']) == json_bytes(metadata), 'Hand source metadata mismatch')
    require(value['sourceSHA256'] == source['entry']['originalSHA256'] == metadata['sha256'],
            'Hand source hash mismatch')
    require(value['workflowID'] == source['manifest']['workflowID']
            and value['recordingID'] == source['manifest']['recordingID'], 'Hand source workflow mismatch')
    require(isinstance(value['configuration'], str) and value['configuration'], 'Missing hand configuration')
    for key in ('workflowID', 'sourceFrameID', 'sourceSHA256', 'configuration'):
        require(link[key] == value[key], 'Hand manifest binding mismatch: ' + key)
    require(link['payloadSHA256'] == digest(raw), 'Hand derivative payload hash mismatch')
    transform = value['sourceToAnalysis']
    require(all(type(transform.get(k)) is int for k in ('width', 'height', 'orientation')), 'Invalid hand transform dimensions')
    require(transform == dict(kind='identity_full_scene', width=metadata['width'], height=metadata['height'],
                              orientation=1), 'Unsupported hand input transform')
    status = value['status']
    require(status in ('completed', 'noHands', 'error'), 'Unsupported hand result status')
    if status == 'error':
        require(value.get('observation') is None and isinstance(value.get('failure'), str)
                and value['failure'], 'Invalid failed hand observation')
    else:
        observation(value['observation'], metadata)
        require(bool(value['observation']['hands']) == (status == 'completed'), 'Hand status/result mismatch')
        require(value.get('failure') is None, 'Successful hand observation has failure')
    return dict(value, recordID=record['id'], payloadSHA256=digest(raw),
                overlayTransform=source_transform(metadata['width'], metadata['height'], 1))


def read_hands(export):
    results = [frame_result(export, r) for r in export.records.values()
               if r['manifest'].get('recordKind') == FRAME_KIND]
    by_id = {r['recordID']: r for r in results}
    summaries = []
    for record in export.records.values():
        if record['manifest'].get('recordKind') != SUMMARY_KIND:
            continue
        raw = export.payload(record['id'])
        value = strict_json(raw)
        require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1,
                'Unsupported hand summary schema')
        require(type(record['manifest'].get('schemaVersion')) is int and record['manifest']['schemaVersion'] == 1,
                'Unsupported hand summary manifest schema')
        require(value['summaryID'] == record['id'], 'Hand summary identity mismatch')
        for key in ('workflowID', 'configuration'):
            require(value[key] == record['manifest'][key], 'Hand summary binding mismatch')
        require(record['manifest']['payloadSHA256'] == digest(raw), 'Hand summary payload hash mismatch')
        ids = value['frameResultIDs']
        require(isinstance(ids, list) and len(ids) == len(set(ids)), 'Duplicate hand summary result')
        selected = []
        for rid in ids:
            require(rid in by_id, 'Missing hand summary result')
            result = by_id[rid]
            require(all(result[k] == value[k] for k in ('workflowID', 'configuration')),
                    'Cross-workflow/configuration hand summary')
            selected.append(result)
        require(len({r['sourceFrameID'] for r in selected}) == len(selected), 'Repeated hand source in summary')
        require(integer(value['detectedFrameCount']) == sum(r['status'] == 'completed' for r in selected),
                'Hand detected count mismatch')
        require(integer(value['failedFrameCount']) == sum(r['status'] == 'error' for r in selected),
                'Hand failed count mismatch')
        require(integer(value['analyzedFrameCount']) == sum(r['status'] != 'error' for r in selected),
                'Hand analyzed count mismatch')
        require(isinstance(value['captureIDs'], list) and len(value['captureIDs']) == len(set(value['captureIDs'])),
                'Invalid hand capture inventory')
        runs = {r['recordingID']: r for r in export.runs if r['workflowID'] == value['workflowID']}
        segment_ids = set()
        for segment in value['segments']:
            rid = identifier(segment['recordingID'])
            require(rid not in segment_ids and rid in runs, 'Invalid hand segment inventory')
            segment_ids.add(rid)
            require(integer(segment['frameCount']) <= runs[rid]['frameCount'], 'Hand segment frame count mismatch')
            require(segment['status'] in ('complete', 'partial', 'interrupted'), 'Invalid hand segment status')
        require(all(r['recordingID'] in segment_ids for r in selected), 'Hand result missing segment')
        for gap in value['gaps']:
            require(gap['recordingID'] in segment_ids, 'Hand gap missing segment')
            integer(gap['ordinal'])
            require(isinstance(gap['reason'], str) and gap['reason'], 'Invalid hand gap reason')
        finite(value['recordedAt'])
        inventory = value['sourceInventorySHA256']
        require(isinstance(inventory, str) and re.fullmatch('[0-9a-f]{64}', inventory), 'Invalid hand inventory hash')
        entries = sorted((r for rid in runs for r in export.groups[rid]),
                         key=lambda r: (r['manifest']['recordingID'].upper(), r['manifest']['ordinal']))
        lines = [f"{r['manifest']['recordingID'].upper()}|{r['id'].upper()}|{r['manifest']['ordinal']}|{r['manifest']['payloadSHA256']}"
                 for r in entries]
        current = digest('\n'.join(lines).encode()) == inventory
        if current:
            require(segment_ids == set(runs), 'Current hand summary omits segment')
            require(all(s['frameCount'] == runs[s['recordingID']]['frameCount']
                        and s['status'] == runs[s['recordingID']]['status'] for s in value['segments']),
                    'Current hand summary segment mismatch')
            require({r['sourceFrameID'] for r in selected} == {f['recordID'] for run in runs.values() for f in run['frames']},
                    'Current hand summary omits source frames')
        for capture in value['captureIDs']:
            source = export.records.get(identifier(capture))
            require(source is not None and source['manifest'].get('captureID') == capture
                    and source['manifest'].get('workflowID', capture) == value['workflowID'],
                    'Hand summary capture binding mismatch')
        summaries.append(dict(value, recordID=record['id'], payloadSHA256=digest(raw),
                              sourceInventoryStatus='current' if current else 'stale'))
    # Replays retain old derivatives. Choose a complete published run per configuration,
    # preferring the current source inventory; never splice results from retries.
    selected = {}
    for summary in summaries:
        key = (summary['workflowID'], summary['configuration'])
        rank = (summary['sourceInventoryStatus'] == 'current', summary['recordedAt'], summary['recordID'])
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, summary)
    selected_ids = {rid for _, summary in selected.values() for rid in summary['frameResultIDs']}
    summarized_keys = set(selected)
    for result in results:
        key = (result['workflowID'], result['configuration'])
        result['selectedForOverlay'] = key not in summarized_keys or result['recordID'] in selected_ids
    return dict(schema='source_bound_hand_landmarks_v1', results=results, summaries=summaries,
                interpretation='landmarks_only', crossFrameHandIdentity='unestablished')


def for_frame(report, frame_id):
    values = [r for r in report['results'] if r['sourceFrameID'] == frame_id and r.get('selectedForOverlay', True)]
    status = 'unavailable' if not values else ('ambiguous' if len(values) > 1 else values[0]['status'])
    return dict(status=status, results=values)


def overlay(image, result):
    """Separate native-size presentation derivative; original raster is untouched."""
    output = image.convert('RGB')
    draw = ImageDraw.Draw(output)
    stroke = max(1, min(image.size) // 400)
    for hand in result['observation']['hands']:
        points = [source_point(p, result['overlayTransform']) for p in hand['normalizedLandmarks']]
        for a, b in EDGES:
            draw.line([tuple(points[a]), tuple(points[b])], fill='#26f2ac', width=stroke)
        for x, y in points:
            draw.ellipse((x-stroke, y-stroke, x+stroke, y+stroke), fill='#ffcc55')
    return output
