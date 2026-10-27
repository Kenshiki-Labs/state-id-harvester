#!/usr/bin/env python3
"""Launch retained inspections without rebuilding or selecting analysis results."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/CardBoundary'))
from json_contract import strict_json, require
WORKSPACE = ('boundary', 'rectification', 'edges', 'topology', 'measurements',
             'measurement-models', 'perimeter', 'assembly', 'path-assessment', 'working-area')


def digest(path):
    require(path.is_file() and not path.is_symlink(), 'Expected regular artifact: ' + str(path))
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def admit_separation(packages):
    directory = packages['separation']
    require(not directory.is_symlink(), 'Report directory symlink')
    def read(path):
        require(not path.is_symlink(), 'Manifest symlink')
        raw = path.read_bytes()
        return strict_json(raw), hashlib.sha256(raw).hexdigest()
    report, _ = read(directory / 'assessment.json')
    scores, score_hash = read(packages['scores'] / 'manifest.json')
    working, working_hash = read(packages['working-area'] / 'manifest.json')
    require(report.get('schema') == 'license_surface_separation_v1', 'Unsupported separation schema')
    require(scores.get('schema') == 'apple_dms_scores_v1', 'Unsupported score schema')
    require(working.get('type') == 'id_cadastral_interior_working_area', 'Unsupported working schema')
    require(report.get('score_manifest_sha256') == score_hash, 'Separation score lineage mismatch')
    require(report.get('working_manifest_sha256') == working_hash, 'Separation working lineage mismatch')
    source = report.get('source_sha256')
    require(isinstance(source, str) and len(source) == 64 and
            source == scores.get('source_sha256') == working.get('sourceHashes', {}).get('browser-viewer/original.png'),
            'Separation source lineage mismatch')
    required = {'pattern-preview.jpg', 'contrast-preview.jpg',
                'dominant-interior-pattern.png', 'inside-vs-outside-score.npy'}
    artifacts = report.get('artifacts')
    require(isinstance(artifacts, dict) and set(artifacts) in (required, required | {'index.html'}),
            'Separation artifacts incomplete or unsupported')
    for name, expected in artifacts.items():
        require(digest(directory / name) == expected, 'Separation artifact hash mismatch: ' + name)
    # Earlier retained reports predate HTML hashing. Their four evidence rasters
    # must still verify; HTML is a presentation file, not authenticated evidence.
    digest(directory / 'index.html')
    return directory / 'index.html'


def load_layout(baseline, config):
    layout = strict_json(config.read_bytes())
    if layout.get('schemaVersion') != 1:
        raise ValueError('Unsupported layout schema')
    if set(layout['packages']) != set(WORKSPACE) | {'scores', 'separation'}:
        raise ValueError('Layout must name every retained package explicitly')
    if set(layout['environments']) != {'geometry', 'edges', 'apple'}:
        raise ValueError('Layout must name geometry, edges and apple environments')
    baseline = baseline.resolve(strict=True)
    resolved = {}
    for group in ('packages', 'environments'):
        resolved[group] = {}
        for name, relative in layout[group].items():
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Layout paths must be relative to baseline')
            # Virtual-environment Python may be a symlink to the host interpreter.
            resolved[group][name] = baseline / path
    return resolved


def command_for(component, baseline, layout, port):
    packages, environments = layout['packages'], layout['environments']
    if component == 'separation':
        report = admit_separation(packages)
        return report.resolve().as_uri()
    environment = environments['geometry' if component == 'workspace' else 'apple']
    if not environment.is_file():
        raise FileNotFoundError(environment)
    if component == 'scores':
        if not (packages['scores'] / 'manifest.json').is_file():
            raise FileNotFoundError(packages['scores'] / 'manifest.json')
        return [str(environment), str(ROOT / 'Tools/AppleMaterials/serve_scores.py'),
                '--dataset', str(packages['scores']), '--port', str(port)]
    command = [str(environment), str(ROOT / 'Tools/PixelViewer/serve.py'),
               '--baseline', str(baseline.resolve()), '--port', str(port)]
    for name in WORKSPACE:
        if not (packages[name] / 'manifest.json').is_file() and name != 'measurement-models':
            raise FileNotFoundError(packages[name] / 'manifest.json')
        if name == 'measurement-models' and not (packages[name] / 'models.json').is_file():
            raise FileNotFoundError(packages[name] / 'models.json')
        command.extend(['--' + name, str(packages[name])])
    return command


def temporal_command(report, port):
    if report is None:
        raise ValueError('Temporal viewing requires --report DIRECTORY')
    # The server owns full report/image admission before announcing readiness.
    return [sys.executable, str(ROOT / 'Tools/TemporalEvidence/serve.py'),
            '--report', str(report.absolute()), '--port', str(port)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--run',type=Path,help='Prepared analysis run; every available stage is included')
    parser.add_argument('--portraits',type=Path,help='Verified retained portrait-region package')
    parser.add_argument('--report', type=Path, help='Explicit retained temporal report directory')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('baseline-layout.json'))
    parser.add_argument('--component', choices=['workspace', 'scores', 'separation', 'temporal'], required=True)
    parser.add_argument('--port', type=int)
    parser.add_argument('--print-only', action='store_true', help='Inspect the exact command without starting anything')
    args = parser.parse_args()
    port = args.port if args.port is not None else {'workspace': 8767, 'temporal': 8781}.get(args.component, 8780)
    if not 1 <= port <= 65535:
        parser.error('Port must be in 1–65535')
    try:
        if args.run is not None:
            if args.component!='workspace' or args.baseline is None or args.report is not None:
                raise ValueError('--run requires --component workspace and --baseline')
            from run_contract import load_run
            run,packages,_=load_run(args.run)
            if args.baseline.resolve()!=Path(run['baseline']).resolve():raise ValueError('Run baseline mismatch')
            result=[sys.executable,str(ROOT/'Tools/PixelViewer/serve.py'),'--baseline',str(args.baseline.absolute()),
                    '--boundary',str(Path(run['boundary']).absolute()),'--analysis-run',str(args.run.absolute()),'--port',str(port)]
            for name,directory in packages.items():result.extend(['--'+name,str(directory)])
        elif args.component == 'temporal':
            result = temporal_command(args.report, port)
        else:
            if args.baseline is None:
                raise ValueError('This component requires --baseline DIRECTORY')
            if args.report is not None:
                raise ValueError('--report is only supported by the temporal component')
            result = command_for(args.component, args.baseline, load_layout(args.baseline, args.config), port)
        if args.portraits is not None:
            if args.component!='workspace':raise ValueError('--portraits requires workspace')
            result.extend(['--portraits',str(args.portraits.absolute())])
        if isinstance(result, str):
            print(result, flush=True)
            if not args.print_only and not webbrowser.open(result):
                raise RuntimeError('Open the printed report URL in your browser')
        else:
            print(shlex.join(result), flush=True)
            if not args.print_only:
                # Replace the launcher so Ctrl-C and process supervision address
                # the actual server; no orphan child listener is left behind.
                os.execv(result[0], result)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
