import json
from pathlib import Path
import tempfile
import subprocess
import sys
import shlex
import unittest
from launch import WORKSPACE, command_for, load_layout, digest, temporal_command


class LaunchTests(unittest.TestCase):
    def test_temporal_requires_explicit_report_and_uses_standard_python(self):
        import sys
        with self.assertRaisesRegex(ValueError, '--report'):
            temporal_command(None, 8781)
        command = temporal_command(Path('/example/report'), 8781)
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith('Tools/TemporalEvidence/serve.py'))
        self.assertEqual(command[2:], ['--report', '/example/report', '--port', '8781'])

    def test_temporal_checks_use_configured_environment_when_baseline_supplied(self):
        with tempfile.TemporaryDirectory() as temp:
            command = [sys.executable, str(Path(__file__).with_name('check.py')),
                       '--group', 'temporal', '--print-only']
            standalone = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(shlex.split(standalone.stdout)[0], sys.executable)
            configured = subprocess.run(command + ['--baseline', temp],
                                        check=True, capture_output=True, text=True)
            self.assertEqual(shlex.split(configured.stdout)[0],
                             str(Path(temp).resolve()/'geotiff-env/bin/python'))

    def separation_fixture(self, base, hash_html=False):
        layout = load_layout(base, Path(__file__).with_name('baseline-layout.json'))
        for key in ('separation', 'scores', 'working-area'):
            layout['packages'][key].mkdir()
        packages = layout['packages']
        (packages['scores'] / 'manifest.json').write_text(json.dumps({
            'schema': 'apple_dms_scores_v1', 'source_sha256': 'a' * 64}))
        (packages['working-area'] / 'manifest.json').write_text(json.dumps({
            'type': 'id_cadastral_interior_working_area',
            'sourceHashes': {'browser-viewer/original.png': 'a' * 64}}))
        report = {'schema': 'license_surface_separation_v1', 'source_sha256': 'a' * 64,
                  'score_manifest_sha256': digest(packages['scores'] / 'manifest.json'),
                  'working_manifest_sha256': digest(packages['working-area'] / 'manifest.json'),
                  'artifacts': {}}
        for name in ('pattern-preview.jpg', 'contrast-preview.jpg',
                     'dominant-interior-pattern.png', 'inside-vs-outside-score.npy', 'index.html'):
            path = packages['separation'] / name
            path.write_bytes(name.encode())
            if name != 'index.html' or hash_html:
                report['artifacts'][name] = digest(path)
        (packages['separation'] / 'assessment.json').write_text(json.dumps(report))
        return layout

    def test_retained_and_html_hashed_reports_admit(self):
        for hash_html in (False, True):
            with self.subTest(hash_html=hash_html), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                layout = self.separation_fixture(base, hash_html)
                self.assertTrue(command_for('separation', base, layout, 8767).endswith('/index.html'))

    def test_report_tamper_rejected(self):
        for name in ('pattern-preview.jpg', 'contrast-preview.jpg', 'inside-vs-outside-score.npy', 'index.html'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                layout = self.separation_fixture(base, True)
                (layout['packages']['separation'] / name).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    command_for('separation', base, layout, 8767)

    def test_configured_lineage_mismatch_rejected(self):
        for component in ('scores', 'working-area'):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                layout = self.separation_fixture(base)
                path = layout['packages'][component] / 'manifest.json'
                data = json.loads(path.read_text()); data['changed'] = True
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'lineage mismatch'):
                    command_for('separation', base, layout, 8767)

    def test_duplicate_report_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            layout = self.separation_fixture(base)
            (layout['packages']['separation'] / 'assessment.json').write_text('{"schema":1,"schema":2}')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                command_for('separation', base, layout, 8767)

    def test_all_workspace_packages_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            layout = load_layout(base, Path(__file__).with_name('baseline-layout.json'))
            python = layout['environments']['geometry']
            python.parent.mkdir(parents=True)
            python.touch()
            for name in WORKSPACE:
                directory = layout['packages'][name]
                directory.mkdir()
                (directory / ('models.json' if name == 'measurement-models' else 'manifest.json')).touch()
            command = command_for('workspace', base, layout, 8767)
            self.assertTrue(all('--' + name in command for name in WORKSPACE))
            (layout['packages']['edges'] / 'manifest.json').unlink()
            with self.assertRaises(FileNotFoundError):
                command_for('workspace', base, layout, 8767)

    def test_both_separation_panels_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            layout = load_layout(base, Path(__file__).with_name('baseline-layout.json'))
            directory = layout['packages']['separation']
            directory.mkdir()
            (directory / 'index.html').touch()
            with self.assertRaises(FileNotFoundError):
                command_for('separation', base, layout, 8767)

    def test_reject_incomplete_or_escaping_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / 'layout.json'
            data = json.loads(Path(__file__).with_name('baseline-layout.json').read_text())
            data['packages']['scores'] = '../outside'
            config.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_layout(base, config)
            del data['packages']['scores']
            config.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_layout(base, config)
