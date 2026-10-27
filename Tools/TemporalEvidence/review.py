"""Saved human observations are source-bound annotations, never automatic verdicts."""
from datetime import datetime
from contract import digest, read_regular, require, strict_json

KINDS = {'hand_contact', 'object_lift', 'turnover', 'relative_scene_motion', 'occlusion', 'surface_cue'}


def assess(path, report):
    if path is None:
        return dict(status='unreviewed', method='not_reviewed', observations=[])
    raw = read_regular(path)
    review = strict_json(raw)
    require(review['schema'] == 'id_cadastral_temporal_review_v1', 'Unsupported review schema')
    require(review['sourceIndexSHA256'] == report['source']['indexSHA256'], 'Review source mismatch')
    require(review['method'] == 'visual_review', 'Unsupported review method')
    require(review['reviewerType'] in ('human', 'assistant'), 'Reviewer type required')
    require(isinstance(review['reviewer'], str) and 0 < len(review['reviewer'].strip()) <= 200, 'Reviewer required')
    dt = datetime.fromisoformat(review['reviewedAt'].replace('Z', '+00:00'))
    require(dt.tzinfo is not None, 'Review time must include timezone')
    require(review['status'] in ('observed', 'not_observed', 'indeterminate'), 'Invalid review outcome')
    frames = {frame['recordID']: (i, frame) for i, frame in enumerate(report['frames'])}
    observations = review['observations']
    require(isinstance(observations, list) and len(observations) > 0, 'Review evidence required')
    positive = False
    for item in observations:
        require(item['kind'] in KINDS and item['outcome'] in ('observed', 'not_observed', 'indeterminate'), 'Invalid observation')
        a, first = frames[item['startFrameID']]; b, last = frames[item['endFrameID']]
        require(a <= b and first['recordingID'] == last['recordingID'] == item['recordingID'], 'Cross-segment/reversed review')
        require(first['sourceSHA256'] == item['startFrameSHA256'] and last['sourceSHA256'] == item['endFrameSHA256'], 'Review frame hash mismatch')
        require(isinstance(item['note'], str) and 0 < len(item['note'].strip()) <= 4000, 'Observation explanation required')
        if item['outcome'] == 'observed' and item['kind'] in ('object_lift', 'turnover', 'relative_scene_motion'):
            require(a < b, 'Motion finding requires multiple frames')
            selected = {f['recordID'] for f in report['frames'][a:b+1]}
            require(not any(gap['beforeFrameID'] in selected and gap['afterFrameID'] in selected
                            for gap in report.get('coverage', {}).get('gaps', [])),
                    'Motion finding crosses a coverage gap; use separate observations')
            positive = True
    require(review['status'] != 'observed' or positive, 'Handling observed requires observed temporal evidence')
    return dict(status=review['status'], method=review['method'], reviewer=review['reviewer'],
                reviewerType=review['reviewerType'], reviewedAt=review['reviewedAt'], observations=observations, reviewInputSHA256=digest(raw))
