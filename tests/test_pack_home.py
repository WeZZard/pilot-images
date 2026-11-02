"""host/pack-home.zsh builds a pack's home.tgz from its home/ folder; no VM, SSH or Tart."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'host/pack-home.zsh'


class PackHomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.pack = self.home / '.config/vm-credentials/lane'
        self.pack.mkdir(parents=True)
        token = self.home / '.agent/sign-in'
        token.parent.mkdir()
        token.write_text('token-1')

    def run_script(self, *args):
        return subprocess.run(['zsh', str(SCRIPT), 'lane', *args], env=dict(os.environ, HOME=str(self.home)),
                              capture_output=True, text=True)

    def members(self):
        with tarfile.open(self.pack / 'home.tgz') as archive:
            return {m.name: archive.extractfile(m).read().decode() for m in archive.getmembers() if m.isfile()}

    def test_named_files_and_kept_files_both_travel(self):
        settings = self.pack / 'home/.tool/settings.yml'
        settings.parent.mkdir(parents=True)
        settings.write_text('gateway: example')
        result = self.run_script('.agent/sign-in')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.members(), {'.agent/sign-in': 'token-1', '.tool/settings.yml': 'gateway: example'})
        self.assertEqual((self.pack / 'home.tgz').stat().st_mode & 0o777, 0o600)
        self.assertNotIn('token-1', result.stdout + result.stderr)

    def test_a_named_file_is_refreshed_from_the_home_folder(self):
        self.run_script('.agent/sign-in')
        (self.home / '.agent/sign-in').write_text('token-2')
        self.assertEqual(self.run_script('.agent/sign-in').returncode, 0)
        self.assertEqual(self.members(), {'.agent/sign-in': 'token-2'})
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.members(), {'.agent/sign-in': 'token-2'})

    def test_paths_outside_the_home_folder_are_refused(self):
        for path in ('/etc/hosts', '../outside', '.agent/../../outside', '.agent/missing'):
            self.assertNotEqual(self.run_script(path).returncode, 0, path)
        self.assertFalse((self.pack / 'home.tgz').exists())

    def test_an_empty_home_folder_is_refused(self):
        self.assertNotEqual(self.run_script().returncode, 0)


if __name__ == '__main__':
    unittest.main()
