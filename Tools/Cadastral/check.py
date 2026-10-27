#!/usr/bin/env python3
"""Run the retained host checks in their separate dependency environments."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys
from launch import ROOT, load_layout

SUITES = {
    'geometry': ('CardBoundary', 'CardRaster', 'CardRectification', 'CardMeasurements',
                 'CardTopology', 'PerimeterCandidates', 'CardInterior', 'PixelViewer',
                 'RegionSegmentation', 'PortraitRegion', 'Cadastral'),
    'edges': ('CardEdges',),
    'apple': ('AppleMaterials',),
    'temporal': ('TemporalEvidence',),
}
JS = ('test-boundary-dataset.cjs', 'test-edges.cjs', 'test-rectification.cjs', 'test-topology.cjs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('baseline-layout.json'))
    parser.add_argument('--group', choices=['all', *SUITES], default='all')
    parser.add_argument('--print-only', action='store_true')
    args = parser.parse_args()
    if args.group != 'temporal' and args.baseline is None:
        parser.error('--baseline is required for spatial checks')
    environments = (load_layout(args.baseline, args.config)['environments']
                    if args.baseline is not None else {})
    environments['temporal'] = environments.get('geometry', sys.executable)
    commands = []
    for group, directories in SUITES.items():
        if args.group not in ('all', group):
            continue
        for directory in directories:
            commands.append([str(environments[group]), '-m', 'unittest', 'discover',
                             '-s', str(ROOT / 'Tools' / directory), '-p', 'test_*.py'])
    if args.group in ('all', 'geometry'):
        commands.append(['node', '--test', *[str(ROOT / 'Tools/PixelViewer' / name) for name in JS]])
    for command in commands:
        print(shlex.join(command), flush=True)
        if not args.print_only:
            result = subprocess.run(command, cwd=ROOT)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
