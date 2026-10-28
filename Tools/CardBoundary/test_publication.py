"""OS-level publication races, crash lock release, and interruption behavior."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from publication import PublicationDurabilityError, publish_directory, rename_no_replace


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'dataset'
        self.lock = self.root / '.dataset.publish.lock'

    def spawn(self, script, *args):
        child = subprocess.Popen([sys.executable, '-u', '-c', script, str(self.out), *args],
                                 cwd=Path(__file__).parent, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        self.addCleanup(cleanup)
        return child

    def test_concurrent_publishers_have_exactly_one_winner(self):
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            script = '''
import sys
from publication import publish_directory
print('ready', flush=True)
try:
    publish_directory(sys.argv[1], {'a': sys.argv[2].encode(), 'b': sys.argv[2].encode()})
except FileExistsError:
    sys.exit(17)
'''
            a = self.spawn(script, 'first')
            b = self.spawn(script, 'second')
            self.assertEqual(a.stdout.readline().strip(), 'ready')
            self.assertEqual(b.stdout.readline().strip(), 'ready')
            self.assertFalse(self.out.exists())
        finally:
            os.close(fd)
        a.communicate(timeout=15)
        b.communicate(timeout=15)
        self.assertEqual(sorted([a.returncode, b.returncode]), [0, 17])
        self.assertEqual((self.out / 'a').read_bytes(), (self.out / 'b').read_bytes())
        self.assertIn((self.out / 'a').read_bytes(), [b'first', b'second'])

    def test_killed_staging_writer_releases_lock_and_never_exposes_partial_output(self):
        script = '''
import sys
import publication
def pause(*args):
    print('staged', flush=True)
    sys.stdin.read()
publication.rename_no_replace = pause
publication.publish_directory(sys.argv[1], {'a': b'old'})
'''
        child = self.spawn(script)
        self.assertEqual(child.stdout.readline().strip(), 'staged')
        self.assertFalse(self.out.exists())
        inode = self.lock.stat().st_ino
        child.kill()
        child.communicate(timeout=10)
        # A fresh subprocess exercises actual OS lock release after SIGKILL.
        recovery = self.spawn("from publication import publish_directory; import sys; "
                              "publish_directory(sys.argv[1], {'a': b'recovered'})")
        _, stderr = recovery.communicate(timeout=15)
        self.assertEqual(recovery.returncode, 0, stderr)
        self.assertEqual((self.out / 'a').read_bytes(), b'recovered')
        self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(len(list(self.root.glob('.dataset.staging-*'))), 1)

    def test_destination_created_during_publish_is_not_replaced(self):
        def competing_writer(parent_fd, source, destination):
            self.out.mkdir()
            rename_no_replace(parent_fd, source, destination)
        with patch('publication.rename_no_replace', side_effect=competing_writer):
            with self.assertRaises(FileExistsError):
                publish_directory(self.out, {'a': b'ours'})
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(list(self.root.glob('.dataset.staging-*')), [])

    def test_broken_destination_symlink_is_preserved(self):
        self.out.symlink_to(self.root / 'missing')
        with self.assertRaises(FileExistsError):
            publish_directory(self.out, {'a': b'ours'})
        self.assertTrue(self.out.is_symlink())

    def test_lock_symlink_is_rejected(self):
        target = self.root / 'target'
        target.write_bytes(b'preserve')
        self.lock.symlink_to(target)
        with self.assertRaises(OSError):
            publish_directory(self.out, {'a': b'ours'})
        self.assertEqual(target.read_bytes(), b'preserve')
        self.assertFalse(self.out.exists())

    def test_interruption_cleans_staging_and_releases_persistent_lock(self):
        with patch('publication.rename_no_replace', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                publish_directory(self.out, {'a': b'ours'})
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob('.dataset.staging-*')), [])
        inode = self.lock.stat().st_ino
        publish_directory(self.out, {'a': b'next'})
        self.assertEqual(self.lock.stat().st_ino, inode)

    def test_interruption_immediately_after_kernel_rename_preserves_output(self):
        def interrupted_rename(parent_fd, source, destination):
            rename_no_replace(parent_fd, source, destination)
            raise KeyboardInterrupt
        with patch('publication.rename_no_replace', side_effect=interrupted_rename):
            with self.assertRaises(KeyboardInterrupt):
                publish_directory(self.out, {'a': b'complete'})
        self.assertEqual((self.out / 'a').read_bytes(), b'complete')
        self.assertEqual(list(self.root.glob('.dataset.staging-*')), [])

    def test_prepublication_sync_failure_does_not_publish(self):
        actual_sync = os.fsync
        calls = 0
        def failing_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('file sync failed')
            actual_sync(fd)
        with patch('publication.os.fsync', side_effect=failing_sync):
            with self.assertRaisesRegex(OSError, 'file sync failed'):
                publish_directory(self.out, {'a': b'ours'})
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob('.dataset.staging-*')), [])

    def test_postpublication_sync_failure_preserves_complete_output(self):
        actual_sync = os.fsync
        calls = 0
        def failing_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('directory sync failed')
            actual_sync(fd)
        with patch('publication.os.fsync', side_effect=failing_sync):
            with self.assertRaises(PublicationDurabilityError):
                publish_directory(self.out, {'a': b'ours'})
        self.assertEqual((self.out / 'a').read_bytes(), b'ours')
        with self.assertRaises(FileExistsError):
            publish_directory(self.out, {'a': b'retry'})


if __name__ == '__main__':
    unittest.main()
