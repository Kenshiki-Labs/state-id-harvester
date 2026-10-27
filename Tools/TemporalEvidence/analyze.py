#!/usr/bin/env python3
"""Build an immutable native temporal evidence package from an explicit export."""
import argparse
import json
from pathlib import Path
import os
import platform
import shutil
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from publication import PublicationDurabilityError, rename_no_replace
import numpy as np
import PIL
from contract import digest, json_bytes, read_regular, require
from reader import Export
from measure import GAP_SECONDS, MAX_SENSOR_DISTANCE_SECONDS, alignment, metrics, phone_at, raster, time_key
from review import assess
from hands import read_hands, for_frame, overlay


def build(export, output, review_path=None):
    frames, recordings, gaps, all_events, all_motion, artifacts = [], [], [], [], [], {}
    hand_report = read_hands(export)
    # Start dates order segments for display only; no inferred continuous clock.
    runs = sorted(export.runs, key=lambda r: (r['workflowID'],
                  json.loads(export.payload(r['recordingID']))['startedAt'], r['recordingID']))
    for run in runs:
        previous = previous_y = None
        start = run['frames'][0].get('hostTimeSeconds') if run['frames'] else None
        geometry = {}
        for event in run['events']:
            if event.get('geometry'):
                key = time_key(event['geometry']['observationTimestamp'])
                geometry.setdefault(key, []).append(event['geometry'])
        reset_geometry = sum(e['kind'] == 'session_started' for e in run['events']) > 1 or any(
            e['kind'] in ('clock_epoch_started', 'clock_changed') for e in run['events'])
        if reset_geometry:
            geometry = {}  # Raw events remain available; no cross-session geometry join.
        context = alignment(run)
        if frames and run['frames']:
            first = run['frames'][0]
            gap = dict(beforeFrameID=frames[-1]['recordID'], afterFrameID=first['recordID'],
                       reason='separate_recording_segments', clockContinuity='unestablished')
            if first.get('hostTimeSeconds') is not None and frames[-1].get('hostTimeSeconds') is not None:
                gap['hostTimeDeltaSeconds'] = first['hostTimeSeconds'] - frames[-1]['hostTimeSeconds']
            gaps.append(gap)
        for frame in run['frames']:
            raw = export.payload(frame['recordID'])  # Reverify the exact bytes consumed.
            y, image, presentation = raster(frame, raw)
            host = frame.get('hostTimeSeconds')
            interval = host - previous['hostTimeSeconds'] if previous and host is not None and previous.get('hostTimeSeconds') is not None else None
            discontinuity = (previous is not None and (interval is None or interval <= 0 or interval > GAP_SECONDS
                             or time_key(frame['timestamp'])[:2] != time_key(previous['timestamp'])[:2]))
            if discontinuity:
                gap = dict(beforeFrameID=previous['recordID'], afterFrameID=frame['recordID'], reason='frame_interval_or_clock_gap')
                if interval is not None:
                    gap['hostTimeDeltaSeconds'] = interval
                gaps.append(gap)
            name = 'frames/' + frame['recordID'] + '.png'
            image.save(output / name)
            artifacts[name] = digest(read_regular(output / name))
            value = dict(recordID=frame['recordID'], recordingID=run['recordingID'],
                         sequenceNumber=frame['sequenceNumber'], hostTimeSeconds=host,
                         relativeTimeSeconds=host-start if host is not None and start is not None else None,
                         timestamp=frame['timestamp'], width=frame['width'], height=frame['height'],
                         sourceSHA256=frame['sha256'], image=name, imagePresentation=presentation,
                         metrics=metrics(y, previous_y if not discontinuity else None),
                         phoneMotion=phone_at(host, context), camera=frame.get('camera'),
                         geometry=frame.get('geometry') or (geometry[time_key(frame['timestamp'])][0]
                         if len(geometry.get(time_key(frame['timestamp']), [])) == 1 else None))
            hand = for_frame(hand_report, frame['recordID'])
            value['handLandmarks'] = dict(status=hand['status'], resultIDs=[r['recordID'] for r in hand['results']])
            if hand['status'] == 'completed':
                overlay_name = 'frames/' + frame['recordID'] + '-hands.png'
                overlay(image, hand['results'][0]).save(output / overlay_name)
                artifacts[overlay_name] = digest(read_regular(output / overlay_name))
                value['handOverlayImage'] = overlay_name
            if interval is not None:
                value['intervalSeconds'] = interval
            frames.append(value)
            previous, previous_y = frame, y.copy()
        recordings.append({k: v for k, v in run.items() if k not in ('frames', 'motion', 'events')})
        all_events.extend(dict(e, recordingID=run['recordingID']) for e in run['events'])
        all_motion.extend(dict(m, recordingID=run['recordingID']) for m in run['motion'])
        print('Processed', run['frameCount'], 'native frames;', run['status'], flush=True)
    coverage = 'unavailable' if not frames else 'partial'
    # A seal describes a segment, never an inferred complete document journey.
    report = dict(schema='id_cadastral_temporal_evidence_v1',
        method=dict(id='native_temporal_observation_v1', pixelSampling='every_native_luma_sample',
                    frameSampling='every_retained_frame', imageDifference='unregistered_absolute_luma_difference',
                    sensorJoin='nearest_bracketed_sample_no_interpolation',
                    maximumSensorDistanceSeconds=MAX_SENSOR_DISTANCE_SECONDS, frameGapThresholdSeconds=GAP_SECONDS,
                    numpyVersion=np.__version__, pillowVersion=PIL.__version__, pythonVersion=platform.python_version()),
        source=dict(indexSHA256=digest(export.index_bytes),
                    selectionScope=export.index.get('selectionScope', 'selected_still_segments'),
                    recordHashes=[r['entry'] for r in export.records.values()]),
        coverage=dict(recordCount=len(export.records), frameCount=len(frames), motionSampleCount=len(all_motion),
                      recordingCount=len(recordings), status=coverage, gaps=gaps,
                      journeyContinuity='unestablished',
                      alignedFrameCount=sum(f['phoneMotion']['status'] == 'aligned' for f in frames)),
        recordings=recordings, frames=frames, events=all_events, motion=all_motion, artifacts=artifacts)
    hand_report['coverage'] = dict(
        sourceFrameCount=len(frames),
        analyzedFrameCount=sum(f['handLandmarks']['status'] in ('completed', 'noHands') for f in frames),
        gaps=[dict(sourceFrameID=f['recordID'], reason=f['handLandmarks']['status'])
              for f in frames if f['handLandmarks']['status'] not in ('completed', 'noHands')])
    report['handLandmarks'] = hand_report
    report['assessment'] = assess(review_path, report)
    if review_path:
        raw = read_regular(review_path)
        require(digest(raw) == report['assessment']['reviewInputSHA256'], 'Review changed during analysis')
        (output / 'review.json').write_bytes(raw)
        artifacts['review.json'] = digest(raw)
    # Pin code as well as parameters so historical outputs are reproducible.
    report['method']['implementationSHA256'] = {name: digest(read_regular(Path(__file__).with_name(name)))
                                              for name in ('analyze.py', 'reader.py', 'measure.py', 'review.py', 'contract.py', 'hands.py', 'hand_coordinates.py')}
    raw = json_bytes(report)
    (output / 'report.json').write_bytes(raw)
    (output / 'manifest.json').write_bytes(json_bytes(dict(schema='id_cadastral_temporal_package_v1', reportSHA256=digest(raw))))
    return report


def publish(source, target, review_path=None):
    target = Path(target)
    require(not target.exists() and not target.is_symlink(), 'Output already exists; choose a new package path')
    target.parent.mkdir(parents=True, exist_ok=True)
    export = Export(source)
    stage = Path(tempfile.mkdtemp(prefix='.' + target.name + '-', dir=target.parent))
    try:
        (stage / 'frames').mkdir()
        report = build(export, stage, review_path)
        # Reuse the existing no-replace kernel adapter, with a streaming stage
        # because retaining all native PNG bytes in one dictionary is unbounded.
        for path in stage.rglob('*'):
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(stage_fd)
            finally:
                os.close(stage_fd)
            rename_no_replace(parent_fd, stage.name, target.name)
            try:
                os.fsync(parent_fd)
            except OSError as error:
                raise PublicationDurabilityError(
                    f'Complete dataset published at {target}; directory durability unconfirmed') from error
        finally:
            os.close(parent_fd)
        return report
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    try:
        report = publish(args.export, args.output, args.review)
        print('Published', report['coverage']['frameCount'], 'frames; handling:', report['assessment']['status'])
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
