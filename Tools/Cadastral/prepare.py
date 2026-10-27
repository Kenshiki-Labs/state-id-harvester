#!/usr/bin/env python3
"""Assemble existing native analysis tools into one explicit, retained run.

No image algorithm lives here. Each stage retains its own validated package;
failures block only dependent stages. A failed stage never becomes an empty success.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from run_contract import load_run, read_regular, sha as digest

ROOT = Path(__file__).resolve().parents[2]


def plan(base, boundary, output, environments, upstream):
    """Dependency order, fixed tool entrypoints, and explicit package destinations."""
    def stage(name, tool, args, dependencies=(), environment='geometry', entry='manifest.json'):
        return dict(name=name, dependencies=list(dependencies), directory=name, entry=entry,
                    command=[str(environments[environment]), str(ROOT/'Tools'/tool), *map(str,args)])
    p = lambda name: output/name
    result = [
        stage('rectification','CardRectification/rectify.py',[base,boundary,p('rectification')]),
        stage('edges','CardEdges/detect.py',[base,p('edges')],environment='edges'),
        stage('topology','CardTopology/audit.py',[p('edges'),p('topology')],['edges']),
        stage('measurements','CardMeasurements/measure.py',[base,boundary,p('rectification'),p('measurements')],['rectification']),
        stage('measurement-models','CardMeasurements/models.py',[p('measurements'),p('rectification'),p('measurement-models')],['measurements'],entry='models.json'),
        stage('perimeter','PerimeterCandidates/run.py',[base,p('edges'),p('perimeter')],['edges']),
        stage('assembly','PerimeterCandidates/assemble.py',[p('edges'),p('perimeter'),p('assembly')],['perimeter']),
        stage('path-assessment','PerimeterCandidates/path_assessment_run.py',[p('edges'),p('perimeter'),p('assembly'),p('path-assessment')],['assembly']),
        stage('working-area','CardInterior/prepare.py',['--baseline',base,'--boundary',boundary,'--candidates',p('perimeter'),'--registration',p('rectification'),'--output',p('working-area')],['perimeter','rectification']),
    ]
    result += [
        stage('regions','RegionSegmentation/experiment.py',[base,p('regions'),'--full-scene-diagnostics']),
        stage('region-report','RegionSegmentation/report.py',[p('regions'),p('region-report')],['regions'],entry='report.html'),
    ]
    if upstream is not None:
        result += [
            stage('materials','AppleMaterials/run.py',['--image',base/'browser-viewer/original.png','--upstream',upstream,'--output',p('materials'),'--device','cpu'],environment='apple'),
            stage('scores','AppleMaterials/extract_scores.py',['--baseline',p('materials'),'--upstream',upstream,'--output',p('scores')],['materials'],environment='apple'),
            stage('separation','AppleMaterials/assess_separation.py',['--scores',p('scores'),'--materials',p('materials'),'--working',p('working-area'),'--output',p('separation')],['scores','working-area'],environment='apple',entry='assessment.json'),
        ]
    return result


def save(path, document):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         prefix='.run-', suffix='.pending',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document,stream,indent=2,allow_nan=False);stream.write('\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def assemble(base, boundary, output, environments, upstream=None, runner=subprocess.run, resume=False):
    base=base.resolve(strict=True);boundary=boundary.resolve(strict=True);output=output.absolute()
    previous=None
    if resume:
        previous,_,old_raw=load_run(output/'run.json')
    elif output.exists() or output.is_symlink(): raise FileExistsError(output)
    for executable in environments.values():
        if not executable.is_file(): raise FileNotFoundError(executable)
    sources={name:digest(base/name) for name in ('front-original.heic','front-rectified.png','front-geometry.json','browser-viewer/original.png')}
    if previous is None:output.mkdir(mode=0o700,parents=True)
    stages=plan(base,boundary,output,environments,upstream)
    report=dict(schemaVersion=1,type='cadastral_analysis_run',baseline=str(base),
                boundary=str(boundary),boundaryManifestSHA256=digest(boundary/'manifest.json'),
                sourceHashes=sources,orchestratorSHA256=digest(Path(__file__)),
                stages={s['name']:{**s,'state':'pending'} for s in stages},
                capabilities={
                    'temporal':{'state':'requires-input','reason':'The exact linked recording frames have not been exported into a temporal report. The two-photo export contains no temporal-frame evidence.'}})
    if upstream is None:
        for name in ('materials','scores','separation'):
            report['capabilities'][name]={'state':'requires-input','reason':'Supply the repository-pinned Apple model assets with --upstream.'}
    if previous is not None:
        if previous['sourceHashes']!=sources or previous['baseline']!=str(base) or previous['boundary']!=str(boundary):raise ValueError('Resume input mismatch')
        for name,old in previous['stages'].items():
            if name not in report['stages'] or old['command']!=report['stages'][name]['command']:raise ValueError('Resume stage changed: '+name)
            report['stages'][name]=old
        old_hash=hashlib.sha256(old_raw).hexdigest()
        receipt=output/('receipt-'+old_hash+'.json')
        try:
            with receipt.open('xb') as stream:
                stream.write(old_raw);stream.flush();os.fsync(stream.fileno())
        except FileExistsError:
            if read_regular(receipt)!=old_raw:raise ValueError('Prior receipt mismatch')
        report['previousReceipt']=receipt.name
        report['previousReceiptSHA256']=old_hash
    report_path=output/'run.json';save(report_path,report)
    for spec in stages:
        name=spec['name'];record=report['stages'][name]
        if record['state']!='pending':continue
        missing=[d for d in spec['dependencies'] if report['stages'][d]['state']!='available']
        if missing:
            record.update(state='blocked',reason='Required stages unavailable: '+', '.join(missing));save(report_path,report);continue
        log=output/(name+'.log');record.update(state='running',log=log.name);save(report_path,report)
        print(name+': running',flush=True);started=time.monotonic()
        try:
            with log.open('xb') as stream:
                completed=runner(spec['command'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
            record['exitCode']=completed.returncode
            if completed.returncode != 0:
                raise RuntimeError(log.read_text(errors='replace')[-1800:].strip() or 'Stage exited without a diagnostic')
            entry=output/spec['directory']/spec['entry']
            record.update(state='available',entrySHA256=digest(entry))
        except (OSError,RuntimeError,ValueError) as error:
            record.update(state='failed',reason=str(error).splitlines()[-1])
        except BaseException:
            record.update(state='interrupted',reason='Run interrupted; use a new output directory.');save(report_path,report);raise
        record['elapsedSeconds']=time.monotonic()-started
        save(report_path,report);print(name+': '+record['state'],flush=True)
    if any(digest(base/n)!=h for n,h in sources.items()):
        report['sourceUnchanged']=False;save(report_path,report);raise ValueError('Source changed during analysis')
    report['sourceUnchanged']=True;report['executionFinished']=True
    report['allRequestedStagesAvailable']=all(s['state']=='available' for s in report['stages'].values())
    save(report_path,report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','geometry-python','edges-python','apple-python'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--boundary',type=Path)
    p.add_argument('--export',type=Path,help='SDK two-photo export; select one exact capture ID')
    p.add_argument('--capture-id')
    p.add_argument('--upstream',type=Path)
    p.add_argument('--resume',action='store_true',help='Add newly supported stages to a finished run; retain original outputs and receipt')
    a=p.parse_args()
    if a.export is not None:
        if a.baseline is not None or a.boundary is not None or a.resume or not a.capture_id:
            p.error('--export requires --capture-id and a new output, without --baseline/--boundary/--resume')
        from ingest import ingest
        if a.output.exists():raise FileExistsError(a.output)
        a.baseline,a.boundary=ingest(a.export,a.capture_id,a.output.parent/(a.output.name+'-capture'),a.geometry_python)
    elif a.baseline is None or a.boundary is None or a.capture_id is not None:
        p.error('Supply --baseline and --boundary, or --export and --capture-id')
    report=assemble(a.baseline,a.boundary,a.output,dict(geometry=a.geometry_python,edges=a.edges_python,apple=a.apple_python),a.upstream,resume=a.resume)
    print('Retained run: '+str(a.output/'run.json'),flush=True)
    return 0 if report['allRequestedStagesAvailable'] else 2

if __name__=='__main__':raise SystemExit(main())
