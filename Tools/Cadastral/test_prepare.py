import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from prepare import assemble, plan
from run_contract import load_run, inventory_for


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.base=self.root/'base';self.base.mkdir()
        (self.base/'browser-viewer').mkdir()
        for name in ('front-original.heic','front-rectified.png','front-geometry.json','browser-viewer/original.png'):
            (self.base/name).write_bytes(name.encode())
        self.boundary=self.root/'boundary';self.boundary.mkdir();(self.boundary/'manifest.json').write_text('{}')
        self.output=self.root/'analysis'
        self.env=dict.fromkeys(('geometry','edges','apple'),Path('/usr/bin/true'))
        self.calls=[]

    def runner(self,fail=None):
        specs={tuple(s['command']):s for s in plan(self.base,self.boundary,self.output,self.env,None)}
        def run(command,**kwargs):
            spec=specs[tuple(command)];name=spec['name'];self.calls.append(name)
            if name==fail:
                kwargs['stdout'].write(b'Demonstrated failure\n');return subprocess.CompletedProcess(command,2)
            out=self.output/name;out.mkdir();(out/spec['entry']).write_text('{}')
            return subprocess.CompletedProcess(command,0)
        return run

    def test_failed_branch_does_not_hide_independent_results(self):
        report=assemble(self.base,self.boundary,self.output,self.env,runner=self.runner('edges'))
        self.assertEqual(report['stages']['edges']['state'],'failed')
        self.assertEqual(report['stages']['topology']['state'],'blocked')
        self.assertEqual(report['stages']['measurement-models']['state'],'available')
        self.assertEqual(report['stages']['region-report']['state'],'available')
        self.assertNotIn('topology',self.calls)
        self.assertFalse(report['allRequestedStagesAvailable'])
        admitted,packages,_=load_run(self.output/'run.json')
        self.assertNotIn('edges',packages)
        self.assertIn('measurements',packages)
        with self.assertRaisesRegex(ValueError,'omitted'):
            inventory_for(self.output/'run.json',self.base,self.boundary,{})

    def test_existing_run_is_not_overwritten_and_resume_does_not_rerun_available(self):
        assemble(self.base,self.boundary,self.output,self.env,runner=self.runner())
        count=len(self.calls)
        with self.assertRaises(FileExistsError):assemble(self.base,self.boundary,self.output,self.env,runner=self.runner())
        resumed=assemble(self.base,self.boundary,self.output,self.env,runner=self.runner(),resume=True)
        self.assertEqual(len(self.calls),count)
        self.assertTrue((self.output/resumed['previousReceipt']).is_file())
        (self.output/'edges/manifest.json').write_text('changed')
        with self.assertRaisesRegex(ValueError,'entry changed'):
            assemble(self.base,self.boundary,self.output,self.env,runner=self.runner(),resume=True)

    def test_source_change_and_unfinished_run_rejected(self):
        assemble(self.base,self.boundary,self.output,self.env,runner=self.runner())
        path=self.output/'run.json';run=json.loads(path.read_text());run['executionFinished']=False;path.write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError,'unfinished'):load_run(path)
        run['executionFinished']=True;path.write_text(json.dumps(run));(self.base/'front-original.heic').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source changed'):load_run(path)

    def test_every_model_stage_is_named_even_when_assets_absent(self):
        report=assemble(self.base,self.boundary,self.output,self.env,runner=self.runner())
        for name in ('materials','scores','separation'):
            self.assertEqual(report['capabilities'][name]['state'],'requires-input')
        specs=plan(self.base,self.boundary,self.output,self.env,Path('/model'))
        self.assertEqual({s['name'] for s in specs},{'rectification','edges','topology','measurements','measurement-models','perimeter','assembly','path-assessment','working-area','regions','region-report','materials','scores','separation'})

if __name__=='__main__':unittest.main()
