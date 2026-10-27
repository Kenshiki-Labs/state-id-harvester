"""Immutable admission of perimeter evidence packages."""
import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode()


def load_dataset(directory, source_hashes=None, edge_hash=None):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('Symlink package')
    manifest_path = directory / 'manifest.json'
    if manifest_path.is_symlink():
        raise ValueError('Symlink manifest')
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get('type') != 'id_cadastral_perimeter_candidates' or manifest.get('schemaVersion') != 1:
        raise ValueError('Unsupported perimeter package')
    if source_hashes is not None and manifest.get('sourceHashes') != source_hashes:
        raise ValueError('Perimeter source mismatch')
    if edge_hash is not None and manifest.get('edgeManifestSHA256') != edge_hash:
        raise ValueError('Perimeter edge identity mismatch')
    if manifest.get('physicalSelection') != {'status': 'unresolved', 'selectedCandidateIds': []}:
        raise ValueError('Unsupported physical selection')
    expected = {'candidates.json', 'evidence.json', 'relationships.json', 'membership.npz'}
    if set(manifest.get('artifacts', {})) != expected:
        raise ValueError('Unexpected perimeter artifacts')
    files = {'manifest.json': raw}
    for name in expected:
        path = directory / name
        if path.is_symlink():
            raise ValueError('Symlink artifact')
        data = path.read_bytes()
        if manifest['artifacts'][name] != {'sha256': digest(data), 'bytes': len(data)}:
            raise ValueError('Perimeter artifact mismatch: ' + name)
        files[name] = data
    return manifest, files
