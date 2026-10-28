"""Adversarial native timing and metadata contracts (synthetic, no identity data)."""
import unittest
from contract import digest, json_bytes
from reader import Export, validate_frame, validate_geometry
from measure import alignment, phone_at, time_key


def stamp(value=1, scale=1, epoch=0):
    return dict(value=value, timescale=scale, epoch=epoch, flags=1,
                clock='captureSessionSynchronizationClock')


def frame(value=1):
    raw = bytes(6)
    return dict(width=2, height=2, sequenceNumber=value, timestamp=stamp(value),
                sha256=digest(raw), pixelFormat=875704422,
                planes=[dict(width=2, height=2, offset=0, byteCount=4,
                             sourceBytesPerRow=2, packedBytesPerRow=2),
                        dict(width=1, height=1, offset=4, byteCount=2,
                             sourceBytesPerRow=2, packedBytesPerRow=2)]), raw


def motion(t):
    return dict(bootTimeSeconds=t, recordID='sensor', referenceFrame='xArbitraryZVertical_rotation_radians_per_second_acceleration_g',
                rotationRate=dict(x=1, y=0, z=0))


def run():
    return dict(events=[dict(kind='session_started', clockCorrelation=dict(
        method='CMClockGetHostTimeClock_brackets_ProcessInfo_systemUptime',
        hostBeforeSeconds=10, hostAfterSeconds=10.002, bootTimeSeconds=10.001))],
        motion=[motion(10), motion(10.01), motion(10.02)])


class NativeContracts(unittest.TestCase):
    def test_rational_geometry_equal_times_and_wrong_epoch(self):
        geometry = dict(observationTimestamp=stamp(2, 2),
                        coordinateSpace='normalized_delivered_video_buffer_top_left')
        validate_geometry(geometry, stamp())
        self.assertEqual(time_key(stamp(2, 2)), time_key(stamp()))
        with self.assertRaises(ValueError):
            validate_geometry(geometry, stamp(epoch=1))

    def test_embedded_geometry_cannot_override_other_frame(self):
        value, raw = frame()
        value['geometry'] = dict(observationTimestamp=stamp(2),
                                coordinateSpace='normalized_delivered_video_buffer_top_left')
        with self.assertRaises(ValueError):
            validate_frame(value, raw)

    def test_boolean_plane_dimension_and_nonfinite_readback_rejected(self):
        value, raw = frame()
        value['planes'][1]['width'] = True
        with self.assertRaises(ValueError):
            validate_frame(value, raw)
        value, raw = frame()
        value['camera'] = dict(readbackHostTimeSeconds=float('nan'))
        with self.assertRaises(ValueError):
            validate_frame(value, raw)

    def test_exact_large_rational_frame_chronology(self):
        rid = '00000000-0000-0000-0000-000000000001'
        workflow = '00000000-0000-0000-0000-000000000002'
        payloads = {rid: json_bytes(dict(schemaVersion=1, startedAt=0,
            maximumDuration=120, maximumDiskBytes=1000, maximumPendingBytes=100))}
        rows = []
        for ordinal in range(3):
            record_id = rid if ordinal == 0 else 'frame' + str(ordinal)
            metadata = dict(schemaVersion=1, workflowID=workflow, ordinal=ordinal,
                recordKind='journeyRecordingStart' if ordinal == 0 else 'journeyRecordingFrame')
            if ordinal:
                native, raw = frame(2**60 + ordinal)
                metadata['frame'] = native
                payloads[record_id] = raw
                metadata.update(previousID=rows[-1]['id'],
                                previousSHA256=rows[-1]['manifest']['payloadSHA256'])
            metadata['payloadSHA256'] = digest(payloads[record_id])
            rows.append(dict(id=record_id, manifest=metadata))
        export = Export.__new__(Export)
        export.payload = lambda key: payloads[key]
        result = export.verify_run(rid, rows)
        self.assertEqual(result['frameCount'], 2)

    def test_no_alignment_across_unanchored_restart_or_reference_change(self):
        value = run()
        self.assertIsNotNone(alignment(value))
        value['events'].append(dict(kind='session_started'))
        self.assertIsNone(alignment(value))
        value = run()
        value['motion'][1]['referenceFrame'] = 'magneticNorthZVertical'
        self.assertIsNone(alignment(value))

    def test_bad_or_missing_anchor_is_unavailable(self):
        for replacement in (None, float('nan'), 9):
            value = run()
            value['events'][0]['clockCorrelation']['hostAfterSeconds'] = replacement
            self.assertIsNone(alignment(value))
        value = run()
        del value['events'][0]['clockCorrelation']['bootTimeSeconds']
        self.assertIsNone(alignment(value))

    def test_sensor_endpoints_and_gap_not_extrapolated(self):
        context = alignment(run())
        self.assertEqual(phone_at(10.01, context)['status'], 'aligned')
        self.assertEqual(phone_at(9.999, context)['status'], 'unavailable')
        self.assertEqual(phone_at(10.021, context)['status'], 'unavailable')
        value = run()
        value['motion'] = [motion(10), motion(11)]
        self.assertEqual(phone_at(10.001, alignment(value))['status'], 'unavailable')

    def test_extreme_finite_gyro_does_not_publish_nonfinite(self):
        value = run()
        value['motion'][1]['rotationRate']['x'] = 1e308
        self.assertEqual(phone_at(10.01, alignment(value))['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
