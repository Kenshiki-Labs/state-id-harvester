"""Bind a prepared run to the exact image and admitted viewer packages."""
import hashlib
import os
from pathlib import Path
import stat
import sys
from contextlib import contextmanager
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'CardBoundary'))
from json_contract import strict_json, require

STAGES=('rectification','edges','topology','measurements','measurement-models','perimeter','assembly','path-assessment','working-area','materials','scores','separation','regions','region-report')
ENTRIES={'measurement-models':'models.json','separation':'assessment.json','region-report':'report.html'}


@contextmanager
def open_regular(path):
    path=Path(path)
    require(not path.is_symlink(),'Expected regular artifact: '+str(path))
    # Nonblocking open lets fstat reject a FIFO before it can wait for a writer.
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode),'Expected regular artifact: '+str(path))
        yield stream


def read_regular(path):
    with open_regular(path) as stream:return stream.read()


def sha(path):
    h=hashlib.sha256()
    with open_regular(path) as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def load_run(path):
    path=Path(path).absolute()
    require(not path.is_symlink(),'Run manifest symlink')
    raw=read_regular(path);run=strict_json(raw)
    require(run.get('schemaVersion')==1 and run.get('type')=='cadastral_analysis_run','Unsupported analysis run')
    require(run.get('executionFinished') is True and run.get('sourceUnchanged') is True,'Analysis run is unfinished')
    base=Path(run['baseline']);boundary=Path(run['boundary'])
    require(sha(boundary/'manifest.json')==run['boundaryManifestSHA256'],'Boundary changed since run')
    names={'front-original.heic','front-rectified.png','front-geometry.json','browser-viewer/original.png'}
    require(set(run['sourceHashes'])==names,'Incomplete source identities')
    for name,h in run['sourceHashes'].items():require(sha(base/name)==h,'Analysis source changed: '+name)
    require(set(run['stages'])<=set(STAGES),'Unknown analysis stage')
    packages={}
    for name,stage in run['stages'].items():
        require(stage['state'] in ('available','failed','blocked','interrupted'),'Unfinished stage')
        require(stage['directory']==name and stage['entry']==ENTRIES.get(name,'manifest.json'),'Unexpected stage artifact')
        if stage['state']=='available':
            directory=path.parent/name
            require(not directory.is_symlink(),'Package symlink')
            require(sha(directory/stage['entry'])==stage['entrySHA256'],'Stage entry changed: '+name)
            require(all(run['stages'].get(d,{}).get('state')=='available' for d in stage['dependencies']),'Missing available-stage dependency')
            packages[name]=directory
    require(read_regular(path)==raw,'Run changed during admission')
    return run,packages,raw


def inventory_for(run_path,baseline,boundary,packages):
    run,available,raw=load_run(run_path)
    require(Path(run['baseline']).resolve()==baseline.resolve() and Path(run['boundary']).resolve()==boundary.resolve(),'Analysis run belongs to another capture')
    for name in STAGES:
        supplied=packages.get(name)
        require((supplied is not None)==(name in available),'Viewer omitted or invented prepared stage: '+name)
        if supplied is not None:require(supplied.resolve()==available[name].resolve(),'Viewer substituted stage: '+name)
    # Commands/logs remain in the downloadable run receipt. The UI consumes a compact inventory.
    stages={name:{k:s[k] for k in ('state','reason','elapsedSeconds','entrySHA256') if k in s} for name,s in run['stages'].items()}
    stages.update(run.get('capabilities',{}))
    for stage in stages.values():
        if 'reason' in stage:stage['reason']=stage['reason'].splitlines()[-1]
    return {'schemaVersion':1,'sourceSHA256':run['sourceHashes']['front-original.heic'],'stages':stages},raw
