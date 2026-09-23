"""Regressions from live readiness checks; no VM or real package manager calls."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('live_checks',ROOT/'applications/check.py')
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)


class LiveRegressionTests(unittest.TestCase):
    def test_metadata_output_has_a_separate_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); executable=root/'dpkg-query'
            executable.write_text('#!'+sys.executable+'\nprint("/fixture/path\\n"*2000)\n');executable.chmod(0o755)
            with patch.dict(os.environ,PATH=str(root)+os.pathsep+os.environ['PATH']):
                result=checks.command(['dpkg-query','-L','fixture'],5)
            self.assertEqual(result['status'],'pass')
            self.assertFalse(result['stdoutTruncated'])
            self.assertGreater(len(result['stdout']),8192)
            normal=checks.command([sys.executable,'-c','print("x"*20000)'],5)
            self.assertTrue(normal['stdoutTruncated'])
            self.assertEqual(len(normal['stdout']),8192)

    def test_application_temporary_root_is_confined_and_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve()
            with patch.dict(os.environ,HOME=str(home)):
                result=checks.command([sys.executable,'-c','import sys;print(sys.argv[1])','{temporary}'],5,temporary_root='~/snap/firefox/common')
                directory=Path(result['stdout'].strip())
                self.assertTrue(directory.is_relative_to(home/'snap/firefox/common'))
                self.assertFalse(directory.exists())
                self.assertEqual(result['temporaryRoot'],'~/snap/firefox/common')
                with self.assertRaisesRegex(ValueError,'inside'):
                    checks.command([sys.executable,'--version'],5,temporary_root='/tmp')

    def test_live_launch_plans_do_not_require_network_or_inaccessible_snap_tmp(self):
        npm=json.loads((ROOT/'applications/npm/manifest.json').read_text())
        pi=json.loads((ROOT/'applications/pi/manifest.json').read_text())
        firefox=json.loads((ROOT/'applications/firefox/manifest.json').read_text())
        for config in npm['platforms'].values(): self.assertEqual(config['launch']['args'],['--version'])
        for config in pi['platforms'].values():
            self.assertEqual(config['launch']['args'],['--version'])
        self.assertEqual(firefox['platforms']['linux']['temporaryRoot'],'~/snap/firefox/common')


if __name__=='__main__': unittest.main()
