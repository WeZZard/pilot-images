"""Exact, read-only Ubuntu CLI plans; these fixtures do not contact a VM."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APPLICATIONS = ROOT / 'applications'
spec = importlib.util.spec_from_file_location('cli_override_runner', APPLICATIONS / 'check.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

# The exact argv are reviewed, not a generic help/version fallback.
EXPECTED = {
    'htop': ('dpkg:htop', 'htop', ['--version'], ['--help']),
    'info': ('dpkg:info', 'info', ['--version'], ['--help']),
    'python312': ('dpkg:python3.12', 'python3.12', ['-I', '-S', '--version'],
                  ['-I', '-S', '-c', 'import sys; print(sys.version)']),
    'vim-terminal': ('dpkg:vim-common', 'vim', ['--version'],
                     ['-u', 'NONE', '-i', 'NONE', '-n', '-N', '-e', '-s', '-c', 'qall!']),
    'p11-kit': ('dpkg:p11-kit', 'p11-kit', None, ['list-modules']),
    'paperconf': ('dpkg:libpaper-utils', 'paperconf', None, ['-d']),
    'debian-distro-info': ('dpkg:distro-info', 'debian-distro-info', None, ['--stable']),
    'udisksctl': ('dpkg:udisks2', 'udisksctl', None, ['status']),
    'mokutil': ('dpkg:mokutil', 'mokutil', None, ['--sb-state']),
}


class CliApplicationOverrides(unittest.TestCase):
    def test_exact_inventory_mapping_and_no_exemptions(self):
        # Optional archived overrides are tested in isolation, not included in
        # the image acceptance selection for unchanged OS packages.
        selection = dict(schemaVersion=1,image='ubuntu2404',plans=list(EXPECTED),sources=['dpkg','snap'],dependencies={})
        inventory_ids = [entry[0] for entry in EXPECTED.values()]
        inventory_ids += ['snap:cups', 'snap:mesa-2404', 'dpkg:vim-runtime']
        inventory = {'applications': [{'id': value} for value in inventory_ids]}
        mapping = runner.expected_plan_inventory_ids(APPLICATIONS, selection, inventory)
        self.assertLess(len(EXPECTED), 10)
        self.assertEqual(selection['dependencies'], {})
        for app, (inventory_id, *_rest) in EXPECTED.items():
            self.assertEqual(mapping[app], ['dpkg:vim', inventory_id] if app == 'vim-terminal' else [inventory_id])
            self.assertEqual(sum(inventory_id in ids for ids in mapping.values()), 1)
        for inventory_id in ('dpkg:vim-runtime','snap:cups','snap:mesa-2404'):
            self.assertEqual(mapping['native:'+inventory_id],[inventory_id])

    def test_bounded_reviewed_commands(self):
        for app, (inventory_id, executable, version, launch) in EXPECTED.items():
            with self.subTest(app=app):
                manifest = runner.load(APPLICATIONS / app / 'manifest.json')
                self.assertEqual(manifest['id'], app)
                self.assertEqual(manifest['inventoryIds'], ['dpkg:vim', inventory_id] if app == 'vim-terminal' else [inventory_id])
                self.assertEqual(set(manifest['platforms']), {'linux'})
                config = manifest['platforms']['linux']
                self.assertEqual(config, {
                    'architectures': ['arm64', 'x86_64'], 'executable': executable,
                    'version': version, 'launch': {'mode': 'command', 'args': launch},
                    'timeoutSeconds': 10, 'extensions': [], 'optional': False,
                })
                self.assertTrue((APPLICATIONS / app / 'PLAN.md').is_file())

    def test_runner_uses_exact_commands_and_requires_zero_exit(self):
        for app, (_inventory_id, executable, version, launch) in EXPECTED.items():
            for exit_code in (0, 1):
                with self.subTest(app=app, exit_code=exit_code):
                    calls = []

                    def execute(argv, timeout, **kwargs):
                        calls.append((argv, timeout, kwargs))
                        return {'status': 'pass' if exit_code == 0 else 'fail',
                                'argv': argv, 'exitCode': exit_code, 'detail': 'exited',
                                'stdout': '', 'stderr': '',
                                'stdoutTruncated': False, 'stderrTruncated': False}

                    with patch.object(runner.shutil, 'which', return_value='/usr/bin/probe'):
                        result = runner.test_application(APPLICATIONS / app, 'linux', 'arm64', execute)
                    expected = [] if version is None else [([executable, *version], 10, {})]
                    expected.append(([executable, *launch], 10, {'startup': False}))
                    self.assertEqual(calls, expected)
                    self.assertEqual(result['status'], 'pass' if exit_code == 0 else 'fail')

    def test_missing_executable_fails_without_launch(self):
        for app in EXPECTED:
            with self.subTest(app=app), patch.object(runner.shutil, 'which', return_value=None):
                def forbidden(*args, **kwargs):
                    self.fail('Missing executable must not be launched')
                result = runner.test_application(APPLICATIONS / app, 'linux', 'arm64', forbidden)
                self.assertEqual(result['status'], 'fail')


if __name__ == '__main__':
    unittest.main()
