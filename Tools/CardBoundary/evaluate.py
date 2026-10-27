"""Native-raster integrity checks, independent of visual assessment."""
import argparse
import hashlib
import json
from json_contract import strict_json
import os
from pathlib import Path
import tempfile

from dataset import verify_boundary
from native_input import verify_unchanged


def digest(data):
    return hashlib.sha256(data).hexdigest()


def evaluate(base, directory, review=None):
    base, directory = Path(base), Path(directory)
    candidate, candidate_bytes, mask_bytes = verify_boundary(base, directory)
    result = {'schemaVersion': 2, 'candidateSHA256': digest(candidate_bytes),
              'disposition': 'pending_review',
              'checks': {'nativeFullFrame': True, 'allSourceHashesUnchanged': True,
                         'sourceRGBSHA256': candidate['fidelity']['sourceRGBSHA256'],
                         'polygonMaskRoundTrip': True,
                         'sourcePixels': candidate['fidelity']['sourcePixelsAdmitted']},
              'geometryModified': False, 'rectificationRegenerated': False,
              'measurements': candidate['diagnostics']}
    review_bytes = None
    if review is not None:
        review = Path(review)
        review_bytes = review.read_bytes()
        assessment = strict_json(review_bytes)
        if assessment['candidateSHA256'] != result['candidateSHA256']:
            raise ValueError('Visual review refers to another candidate')
        if assessment['disposition'] not in ['not_promoted', 'promoted']:
            raise ValueError('Invalid review disposition')
        result['disposition'] = assessment['disposition']
        result['visualReview'] = assessment
        result['visualReviewSHA256'] = digest(review_bytes)
    payload = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode('utf-8')
    descriptor, name = tempfile.mkstemp(prefix='.evaluation-', suffix='.tmp', dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Repeated evaluation is supported, but replacement publishes a complete
        # report bound to the exact candidate, mask, review and source snapshots.
        verify_unchanged(base, candidate['sourceHashes'])
        if ((directory / 'candidate.json').read_bytes() != candidate_bytes or
                (directory / 'candidate-mask.png').read_bytes() != mask_bytes):
            raise ValueError('Candidate changed during evaluation')
        if review is not None and review.read_bytes() != review_bytes:
            raise ValueError('Visual review changed during evaluation')
        os.replace(temporary, directory / 'evaluation.json')
    finally:
        temporary.unlink(missing_ok=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate_directory', type=Path)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.baseline, args.candidate_directory, args.review)['checks'], indent=2))
