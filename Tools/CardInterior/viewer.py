"""Optional verified working-area routes for the existing PixelViewer."""
import hashlib
import json
from pathlib import Path


def snapshot(directory, source_hashes, boundary_id, registration_hash):
    names={'source-labels.png','working-mask.png','working-geometry.json','bottom-observations.json',
           'rectified-interior.png','source-overlay.png','rectified-overlay.png','interior.tif'}
    directory=Path(directory)
    if directory.is_symlink() or (directory/'manifest.json').is_symlink():raise ValueError('Working-area symlink')
    raw=(directory/'manifest.json').read_bytes();m=json.loads(raw)
    if (m.get('type')!='id_cadastral_interior_working_area' or m.get('schemaVersion')!=1 or
        m.get('sourceHashes')!=source_hashes or m.get('boundaryId')!=boundary_id or
        m.get('registrationManifestSHA256')!=registration_hash or set(m.get('artifacts',{}))!=names):
        raise ValueError('Working-area lineage mismatch')
    routes={'/working/manifest.json':(raw,'application/json')}
    for n in names:
        p=directory/n
        if p.is_symlink():raise ValueError('Working-area artifact symlink')
        data=p.read_bytes()
        if m['artifacts'][n]!={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}:
            raise ValueError('Working-area artifact mismatch')
        routes['/working/'+n]=(data,'application/json' if n.endswith('.json') else 'image/tiff' if n.endswith('.tif') else 'image/png')
    return routes
