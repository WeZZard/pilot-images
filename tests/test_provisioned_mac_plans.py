"""Fixture-only acceptance for deliberately provisioned macOS tool plans.

No application, VM, shell, installer, or inventory command is executed.
"""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / 'applications'
SPEC = importlib.util.spec_from_file_location('provisioned_mac_check', APPS / 'check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

IDS = {
    'gh': ['brew-formula:gh', 'dpkg:gh'],
    'jq': ['brew-formula:jq', 'dpkg:jq'],
    'ffmpeg': ['brew-formula:ffmpeg'],
    'pyenv': ['brew-formula:pyenv'],
    'uv': ['brew-formula:uv'],
    'wget': ['brew-formula:wget', 'dpkg:wget'],
    'pnpm': [],
    'rustup': [],
    'rustc': [],
    'cargo': [],
    'xcode': ['bundle:com.apple.dt.Xcode'],
    'ghostty': ['brew-cask:ghostty', 'bundle:com.mitchellh.ghostty'],
    'nvm': [],
    'pyenv-python': [],
}


def manifest(name):
    return json.loads((APPS / name / 'manifest.json').read_text())


class ProvisionedMacPlanTests(unittest.TestCase):
    def test_manifest_contract_and_mocked_baselines(self):
        for name, ids in IDS.items():
            with self.subTest(name=name):
                data = manifest(name)
                config = data['platforms']['macos']
                self.assertEqual(data['inventoryIds'], ids)
                self.assertEqual(set(data['platforms']), {'macos', 'linux'} if name in ('gh','jq','wget') else {'macos'})
                self.assertEqual(config['architectures'], ['arm64'])
                self.assertFalse(config['optional'])
                self.assertEqual(config['extensions'], [])
                self.assertLessEqual(config['timeoutSeconds'], 20)
                self.assertGreater(config['timeoutSeconds'], 0)
                self.assertEqual(config['launch']['mode'], 'command')
                self.assertTrue((APPS / name / 'PLAN.md').is_file())
                calls = []

                def execute(argv, timeout, **kwargs):
                    calls.append((argv, timeout, kwargs))
                    return {'status': 'pass', 'argv': argv}

                with patch.object(CHECK.shutil, 'which', return_value='/fixture/tool'):
                    result = CHECK.test_application(APPS / name, 'macos', 'arm64', execute=execute)
                self.assertEqual(result['status'], 'pass')
                self.assertEqual([item['check'] for item in result['baseline']],
                                 ['availability', 'version', 'launch'])
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0][0], [config['executable'], *config['version']])
                self.assertEqual(calls[1][0], [config['executable'], *config['launch']['args']])
                self.assertTrue(all(timeout <= 20 for _, timeout, _ in calls))
                self.assertFalse(calls[1][2]['startup'])

    def test_missing_executables_and_failed_commands_do_not_pass(self):
        for name in IDS:
            with self.subTest(name=name):
                def unexpected(*args, **kwargs):
                    self.fail('missing executable must not be launched')

                with patch.object(CHECK.shutil, 'which', return_value=None):
                    result = CHECK.test_application(APPS / name, 'macos', 'arm64', execute=unexpected)
                self.assertEqual(result['status'], 'fail')
                with patch.object(CHECK.shutil, 'which', return_value='/fixture/tool'):
                    result = CHECK.test_application(
                        APPS / name, 'macos', 'arm64',
                        execute=lambda *args, **kwargs: {'status': 'fail'})
                self.assertEqual(result['status'], 'fail')

    def test_nvm_sources_only_its_explicit_dependency(self):
        config = manifest('nvm')['platforms']['macos']
        expected = ['--noprofile', '--norc', '-c', '. "$HOME/.nvm/nvm.sh"; nvm --version']
        self.assertEqual(config['executable'], '/bin/bash')
        self.assertEqual(config['version'], expected)
        self.assertEqual(config['launch']['args'], expected)

    def test_python_is_selected_by_pyenv_and_rejects_system_fallback(self):
        config = manifest('pyenv-python')['platforms']['macos']
        self.assertEqual(config['executable'], 'pyenv')
        self.assertEqual(config['version'], ['exec', 'python', '-I', '-S', '--version'])
        args = config['launch']['args']
        self.assertEqual(args[:5], ['exec', 'python', '-I', '-S', '-c'])
        # Execute only the inline assertion against synthetic interpreter paths;
        # this is not an interpreter/application launch or a host inventory read.
        code = compile(args[5], '<pyenv-python-fixture>', 'exec')
        with patch.dict('os.environ', {'PYENV_ROOT': '/fixture/pyenv'}), \
                patch.object(Path, 'resolve', lambda self: self), \
                patch('builtins.print') as output:
            with patch('sys.executable', '/fixture/pyenv/versions/3.14.6/bin/python'):
                exec(code, {})
            output.assert_called_once_with('pyenv-python baseline')
            with patch('sys.executable', '/usr/bin/python3'):
                with self.assertRaisesRegex(AssertionError, 'not a pyenv-installed interpreter'):
                    exec(code, {})

    def test_corepack_cannot_fetch_or_pin(self):
        config = manifest('pnpm')['platforms']['macos']
        expected = ['COREPACK_ENABLE_NETWORK=0', 'COREPACK_ENABLE_PROJECT_SPEC=0',
                    'COREPACK_ENABLE_AUTO_PIN=0', 'pnpm', '--version']
        self.assertEqual(config['executable'], '/usr/bin/env')
        self.assertEqual(config['version'], expected)
        self.assertEqual(config['launch']['args'], expected)

    def test_both_rust_toolchains_are_checked_without_installation(self):
        for name in ('rustc', 'cargo'):
            config = manifest(name)['platforms']['macos']
            self.assertEqual(config['executable'], 'rustup')
            self.assertEqual(config['version'], ['run', 'stable', name, '--version'])
            self.assertEqual(config['launch']['args'], ['run', 'nightly', name, '--version'])

    def test_gui_bundles_do_not_open_windows_or_shells(self):
        for name, executable, argument in (
            ('ghostty', '/Applications/Ghostty.app/Contents/MacOS/ghostty', '--version'),
            ('xcode', '/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild', '-version'),
        ):
            config = manifest(name)['platforms']['macos']
            self.assertEqual(config['executable'], executable)
            self.assertEqual(config['version'], [argument])
            self.assertEqual(config['launch'], {'mode': 'command', 'args': [argument]})


if __name__ == '__main__':
    unittest.main()
