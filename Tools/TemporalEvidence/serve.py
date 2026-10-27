#!/usr/bin/env python3
"""Serve a hash-admitted temporal report locally, without directory serving."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit
from contract import require, strict_json

MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 512 * 1024 * 1024
ASSETS = {'/': ('viewer.html', 'text/html; charset=utf-8'),
          '/viewer.js': ('viewer.js', 'text/javascript; charset=utf-8'),
          '/viewer.css': ('viewer.css', 'text/css; charset=utf-8')}


def artifact_parts(name):
    require(isinstance(name, str) and name and '\\' not in name, 'Invalid artifact path')
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in name.split('/')),
            'Invalid artifact path')
    return path.parts


class ReportSnapshot:
    """Keep an opened no-follow directory; hash the exact image bytes returned."""
    def __init__(self, directory):
        self.fd = None
        try:
            absolute = Path(os.path.abspath(directory))
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in absolute.parts[1:]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                self.fd = fd
            except BaseException:
                os.close(fd)
                raise
            manifest = strict_json(self.read('manifest.json', MAX_REPORT_BYTES))
            require(isinstance(manifest, dict) and manifest.get('schema') == 'id_cadastral_temporal_package_v1', 'Unsupported package')
            self.report_bytes = self.read('report.json', MAX_REPORT_BYTES)
            require(hashlib.sha256(self.report_bytes).hexdigest() == manifest.get('reportSHA256'),
                    'Report hash mismatch')
            self.report = strict_json(self.report_bytes)
            require(isinstance(self.report, dict) and self.report.get('schema') == 'id_cadastral_temporal_evidence_v1', 'Unsupported report')
            self.frames = self.report.get('frames')
            self.artifacts = self.report.get('artifacts')
            require(isinstance(self.frames, list) and isinstance(self.artifacts, dict), 'Invalid frame inventory')
            for name, digest in self.artifacts.items():
                artifact_parts(name)
                require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid artifact digest')
                self.verified_artifact(name)
            ids = set()
            for frame in self.frames:
                require(isinstance(frame, dict) and isinstance(frame.get('recordID'), str), 'Invalid frame')
                require(frame['recordID'] not in ids, 'Duplicate frame ID')
                ids.add(frame['recordID'])
                require(frame.get('image') in self.artifacts and frame['image'].endswith('.png'),
                        'Missing frame artifact')
                if 'handOverlayImage' in frame:
                    require(frame['handOverlayImage'] in self.artifacts
                            and frame['handOverlayImage'].endswith('.png')
                            and frame.get('handLandmarks', {}).get('status') == 'completed',
                            'Invalid hand overlay artifact')
                require(frame.get('imagePresentation') in ('native_rgb', 'native_luma'), 'Unsupported presentation')
                require(all(type(frame.get(k)) is int and frame[k] > 0 for k in ('width', 'height')),
                        'Invalid dimensions')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read(self, name, limit):
        parts = artifact_parts(name)
        parent = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'Unsupported artifact size/type')
                raw = stream.read(limit + 1)
                require(len(raw) <= limit, 'Artifact exceeds limit')
                return raw
        finally:
            os.close(parent)

    def verified_artifact(self, name):
        raw = self.read(name, MAX_IMAGE_BYTES)
        require(hashlib.sha256(raw).hexdigest() == self.artifacts[name], 'Artifact hash mismatch: ' + name)
        return raw

    def frame(self, index, hands=False):
        frame = self.frames[index]
        raw = self.verified_artifact(frame['handOverlayImage' if hands else 'image'])
        require(raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Frame is not PNG')
        require(len(raw) >= 24 and int.from_bytes(raw[16:20], 'big') == frame['width']
                and int.from_bytes(raw[20:24], 'big') == frame['height'], 'Frame dimensions mismatch')
        return raw


def handler_for(snapshot):
    assets = {route: ((Path(__file__).parent / filename).read_bytes(), mime)
              for route, (filename, mime) in ASSETS.items()}

    class Handler(BaseHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.send_header('Referrer-Policy', 'no-referrer')
            super().end_headers()

        def do_GET(self):
            # Loopback binding plus exact Host rejection blocks DNS rebinding.
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',
                                                f'localhost:{self.server.server_port}'):
                self.send_error(403)
                return
            url = urlsplit(self.path)
            if url.query or url.fragment or url.scheme or url.netloc:
                self.send_error(404)
                return
            try:
                if url.path in assets:
                    raw, mime = assets[url.path]
                elif url.path == '/api/report':
                    raw, mime = snapshot.report_bytes, 'application/json'
                elif re.fullmatch('/(frame|hand-frame)/(0|[1-9][0-9]*)', url.path):
                    index = int(url.path.rsplit('/', 1)[-1])
                    if index >= len(snapshot.frames):
                        self.send_error(404)
                        return
                    raw, mime = snapshot.frame(index, hands=url.path.startswith('/hand-frame/')), 'image/png'
                else:
                    self.send_error(404)
                    return
            except (OSError, ValueError, KeyError):
                self.send_error(409, 'Evidence changed or could not be verified')
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8781)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be in 1–65535')
    snapshot = ReportSnapshot(args.report)
    try:
        with HTTPServer(('127.0.0.1', args.port), handler_for(snapshot)) as server:
            print(f'http://127.0.0.1:{server.server_port}', flush=True)
            server.serve_forever()
    finally:
        snapshot.close()


if __name__ == '__main__':
    main()
