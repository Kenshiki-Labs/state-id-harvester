"""Import one explicitly selected SDK photo export, then run existing spatial admission."""
import hashlib
from pathlib import Path
import subprocess
import sys
from uuid import UUID
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'CardBoundary'))
from json_contract import strict_json,require
from prepare import ROOT,save


def ingest(export,capture_id,output,python,runner=subprocess.run):
    export=Path(export);output=Path(output)
    require(not export.is_symlink(),'Export symlink')
    require(not output.exists() and not output.is_symlink(),'Output exists')
    canonical=str(UUID(capture_id)).upper()
    index_path=export/'index.json';require(not index_path.is_symlink(),'Index symlink')
    raw_index=index_path.read_bytes();index=strict_json(raw_index)
    require(index.get('kind')=='sdk_viewer_export' and index.get('schemaVersion')==1,'Unsupported SDK export')
    matches=[c for c in index['captures'] if c['captureID']==canonical]
    require(len(matches)==1,'Capture must identify exactly one exported original')
    entry=matches[0];source=export/canonical;require(not source.is_symlink(),'Capture symlink')
    artifacts={}
    for name,dest,key in [('original.bin','front-original.heic','sourceSHA256'),('rectified.png','front-rectified.png','derivativeSHA256'),('geometry.json','front-geometry.json','geometrySHA256'),('capture-manifest.json','capture-manifest.json','manifestSHA256')]:
        path=source/name;require(path.is_file() and not path.is_symlink(),'Missing verified artifact: '+name)
        data=path.read_bytes();require(hashlib.sha256(data).hexdigest()==entry[key],'Export hash mismatch: '+name)
        artifacts[dest]=data
    manifest=strict_json(artifacts['capture-manifest.json']);geometry=strict_json(artifacts['front-geometry.json'])
    require(manifest['captureID']==canonical and geometry['captureID']==canonical and manifest['profile']==entry['profile'],'Capture identity mismatch')
    require(manifest['fidelity']['uniformTypeIdentifier']=='public.heic','Existing native spatial lane requires HEIC')
    require(manifest['fidelity']['sha256']==entry['sourceSHA256']==geometry['sourceSHA256']==geometry['derivation']['sourceSHA256'],'Source lineage mismatch')
    require(geometry['derivation']['outputSHA256']==entry['derivativeSHA256'],'Derivative lineage mismatch')
    require(index_path.read_bytes()==raw_index,'Export changed during admission')
    output.mkdir(mode=0o700,parents=True)
    for name,data in artifacts.items():
        with (output/name).open('xb') as stream:stream.write(data)
    receipt={'schemaVersion':1,'type':'sdk_capture_spatial_import','capture':entry,
             'exportIndexSHA256':hashlib.sha256(raw_index).hexdigest(),'preparationComplete':False,'stages':[]}
    save(output/'import.json',receipt)
    commands=[['CardRaster/export_geotiff.py',output,output/'geotiff'],
              ['PixelViewer/prepare.py','--baseline',output],
              ['CardBoundary/refine.py',output,output/'contour-native/run'],
              ['CardBoundary/evaluate.py',output,output/'contour-native/run'],
              ['CardBoundary/dataset.py',output,output/'contour-native/run',output/'boundary-v1']]
    for i,args in enumerate(commands):
        command=[str(python),str(ROOT/'Tools'/args[0]),*map(str,args[1:])]
        log=output/('prepare-'+str(i)+'.log')
        with log.open('wb') as stream:result=runner(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
        receipt['stages'].append({'command':command,'exitCode':result.returncode,'log':log.name})
        save(output/'import.json',receipt)
        require(result.returncode==0,'Spatial preparation failed; inspect '+str(log))
    receipt['preparationComplete']=True;save(output/'import.json',receipt)
    return output,output/'boundary-v1'
