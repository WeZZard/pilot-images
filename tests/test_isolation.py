"""A hostile shell reaches nothing real (2026-11-03 decision).

The shell selects an instance (VM_ENVIRONMENT_FILE), points MACHCTL and TART
at recording scripts that also lead PATH, and names the installed service
(MACHINE_SERVICE_URL=http://localhost:6240). The tests pass only if no
recording script ever runs.
"""
import isolation  # first: the tests keep nothing of the shell's environment
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent


class HostileShellTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.heard = self.root / 'heard.log'
        self.recorders = self.root / 'recorders'
        self.recorders.mkdir()
        for name in ('machctl', 'tart'):
            recorder = self.recorders / name
            recorder.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.heard}"\necho "[]"\n')
            recorder.chmod(0o755)
        profile = self.root / 'environment.json'
        profile.write_text(json.dumps(dict(schemaVersion=2, id='hostile', vmServiceUrl='http://127.0.0.1:6240')))
        self.shell = dict(VM_ENVIRONMENT_FILE=str(profile), MACHCTL=str(self.recorders / 'machctl'),
                          TART=str(self.recorders / 'tart'), TART_HOME=str(self.root / 'tart'),
                          MACHINE_SERVICE_URL='http://localhost:6240', HOME=str(self.root),
                          PATH=os.pathsep.join([str(self.recorders), *isolation.SYSTEM_PATH]))

    def heard_nothing(self):
        self.assertEqual(self.heard.read_text() if self.heard.exists() else '', '', 'a real tool was reached')

    def test_importing_isolation_leaves_the_runner_nothing_of_the_shell(self):
        probe = ('import json,os,shutil,sys; sys.path.insert(0,sys.argv[1]); import isolation; '
                 'print(json.dumps(dict(environ=dict(os.environ),machctl=shutil.which("machctl"),tart=shutil.which("tart"))))')
        seen = json.loads(subprocess.run([sys.executable, '-c', probe, str(TESTS)], env=self.shell,
                                         capture_output=True, text=True, check=True).stdout)
        for name in ('VM_ENVIRONMENT_FILE', 'MACHCTL', 'TART', 'TART_HOME', 'MACHINE_SERVICE_URL'):
            self.assertNotIn(name, seen['environ'])
        self.assertNotEqual(seen['environ']['HOME'], str(self.root))
        self.assertNotIn(str(self.recorders), seen['environ']['PATH'].split(os.pathsep))
        self.assertEqual((seen['machctl'], seen['tart']), (None, None))
        self.heard_nothing()

    def test_a_check_clone_run_under_a_hostile_shell_reaches_only_the_test_stubs(self):
        # The lifecycle test that drives the real check-clone.py through machctl
        # acquire/pull/release, run as the shell would run it.
        result = subprocess.run([sys.executable, '-m', 'unittest', '-k', 'test_fresh_clone_failures_release_owned_clone_without_receipt',
                                 'test_inventory_shell'], cwd=TESTS, env=self.shell, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ran 1 test', result.stderr)
        self.heard_nothing()

    def test_check_clone_takes_its_tools_only_from_the_caller(self):
        spec = importlib.util.spec_from_file_location('check_clone', REPO / 'host/check-clone.py')
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(REPO / 'host'))
        self.addCleanup(sys.path.remove, str(REPO / 'host'))
        spec.loader.exec_module(module)
        with patch.dict(os.environ, MACHCTL='/fixture/machctl', TART='/fixture/tart'):
            self.assertEqual((module.tool('machctl'), module.tool('tart')), ('/fixture/machctl', '/fixture/tart'))
        with patch.dict(os.environ, VM_ENVIRONMENT_FILE='/fixture/profile.json'):
            with self.assertRaisesRegex(RuntimeError, 'names MACHCTL'):
                module.tool('machctl')

    def test_a_guest_script_fails_on_a_tool_nobody_stubbed(self):
        env = isolation.guest_environment(self.root / 'sandbox', {'systemctl': 'echo stubbed'}, ('cat',))
        script = 'systemctl; echo x | cat; machctl list; tart list; curl http://localhost:6240/; sudo true; echo done'
        result = subprocess.run(['/bin/bash', '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(result.stdout, 'stubbed\nx\ndone\n')
        for tool in ('machctl', 'tart', 'curl', 'sudo'):
            self.assertIn(f'{tool}: command not found', result.stderr)
        self.assertEqual(sorted(os.listdir(self.root / 'sandbox/sandbox-bin')), ['cat', 'systemctl'])
        self.heard_nothing()


class ConventionTests(unittest.TestCase):
    def test_every_test_module_imports_isolation_first_and_builds_no_environment_from_the_shell(self):
        for path in sorted(TESTS.glob('test_*.py')):
            with self.subTest(module=path.name):
                text = path.read_text()
                first = next(node for node in ast.parse(text).body if isinstance(node, (ast.Import, ast.ImportFrom)))
                self.assertIsInstance(first, ast.Import)
                self.assertEqual([alias.name for alias in first.names], ['isolation'])
                self.assertIsNone(re.search(r"env\s*=\s*(\{\s*\*\*\s*os\.environ|dict\(\s*os\.environ)|os\.environ\['PATH'\]|os\.environ\.items\(\)", text))


if __name__ == '__main__':
    unittest.main()
