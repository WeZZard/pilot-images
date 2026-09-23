import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'applications'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cups = load('cups_service', 'cups-snap/service.py')
mesa = load('mesa_service', 'mesa-runtime/service.py')
RUNNING = dict(LoadState='loaded', ActiveState='active', SubState='running',
               MainPID='104674', Result='success', UnitFileState='enabled')
DISABLED = dict(LoadState='loaded', ActiveState='inactive', SubState='dead',
                MainPID='0', Result='success', UnitFileState='disabled')
CONNECTIONS = '''Interface Plug Slot Notes
content[gpu-2404] firefox:gpu-2404 mesa-2404:gpu-2404 -
content mesa-2404:kernel-gpu-2404 - -
'''


class CupsTests(unittest.TestCase):
    def test_running(self):
        self.assertEqual(cups.evaluate('scheduler is running\n', RUNNING)['status'], 'pass')

    def test_false_text_despite_exit_zero(self):
        with patch.object(cups.subprocess, 'check_output', side_effect=[
                'scheduler is not running\n', '\n'.join(f'{k}={v}' for k, v in RUNNING.items())]), patch('builtins.print') as output:
            self.assertEqual(cups.main(), 1)
        self.assertEqual(json.loads(output.call_args.args[0])['status'], 'fail')

    def test_pid_zero(self):
        self.assertEqual(cups.evaluate('scheduler is running', dict(RUNNING, MainPID='0'))['status'], 'fail')

    def test_failed_unit_and_stale_scheduler(self):
        for state in (DISABLED, dict(RUNNING, Result='exit-code'), dict(RUNNING, MainPID='bad'), dict(RUNNING, LoadState='not-found')):
            self.assertEqual(cups.evaluate('scheduler is running', state)['status'], 'fail')

    def test_command_error_is_json_failure(self):
        with patch.object(cups.subprocess, 'check_output', side_effect=subprocess.TimeoutExpired('lpstat', 8)), patch('builtins.print') as output:
            self.assertEqual(cups.main(), 1)
        self.assertEqual(json.loads(output.call_args.args[0])['status'], 'fail')


class MesaTests(unittest.TestCase):
    def evaluate(self, connections=CONNECTIONS, state=DISABLED):
        return mesa.evaluate(connections, state, mesa.CONNECT, mesa.DISCONNECT)

    def test_disconnected_monitor_is_only_subcheck_not_applicable(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['subchecks'][-1]['status'], 'not-applicable')
        self.assertIn('no daemon launch is claimed', result['subchecks'][-1]['reason'])
        self.assertTrue(all(c['status'] == 'pass' for c in result['subchecks'][:-1]))

    def test_connected_dead_monitor_fails(self):
        connected = CONNECTIONS.replace('kernel-gpu-2404 - -', 'kernel-gpu-2404 kernel:gpu -')
        self.assertEqual(self.evaluate(connected)['status'], 'fail')
        self.assertEqual(self.evaluate(connected, RUNNING)['subchecks'][-1]['status'], 'pass')
        self.assertEqual(self.evaluate(connected, dict(RUNNING, MainPID='0'))['status'], 'fail')

    def test_disconnected_failed_or_running_monitor_is_not_excused(self):
        for state in (RUNNING, dict(DISABLED, Result='exit-code'), dict(DISABLED, UnitFileState='enabled'), dict(DISABLED, LoadState='not-found')):
            self.assertEqual(self.evaluate(state=state)['status'], 'fail')

    def test_changed_policy_is_not_excused(self):
        with self.assertRaises(ValueError):
            mesa.evaluate(CONNECTIONS, DISABLED, mesa.CONNECT, mesa.DISCONNECT.replace('--disable', ''))

    def test_missing_or_ambiguous_interface_fails(self):
        for text in (CONNECTIONS.replace('mesa-2404:gpu-2404', '-'), CONNECTIONS.replace('content mesa-', 'missing mesa-'), CONNECTIONS + 'content mesa-2404:kernel-gpu-2404 - -\n'):
            with self.assertRaises(ValueError):
                self.evaluate(text)

    def test_manifest_embeds_exact_runtime_source(self):
        manifest = json.loads((ROOT / 'mesa-runtime/manifest.json').read_text())
        args = manifest['platforms']['linux']['launch']['args']
        self.assertEqual(args[:2], ['-I', '-c'])
        source = (ROOT / 'mesa-runtime/runtime-info.py').read_text()
        self.assertIn(repr(source), args[2])
        compile(args[2], 'mesa-manifest', 'exec')
        self.assertEqual(manifest['inventoryIds'], ['snap:mesa-2404'])


if __name__ == '__main__':
    unittest.main()
