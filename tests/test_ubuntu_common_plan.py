import importlib.util
import io
import json
from pathlib import Path
import ssl
import subprocess
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'applications/ubuntu-common'
spec = importlib.util.spec_from_file_location('ubuntu_common_tools', PLAN / 'tools.py')
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)
OUTPUTS = (
    b'curl 8.5.0 (aarch64-unknown-linux-gnu)\n',
    b'git version 2.43.0\n',
    b'gpg (GnuPG) 2.4.4\n',
    b'Description:\tUbuntu 24.04.1 LTS\n',
    b'net-tools 2.10\n',
    b'Usage:\n  dconf COMMAND [ARGS...]\n',
    b'xdpyinfo 1.3.4\n',
    b'fontconfig version 2.15.0\n',
    b'UnZip 6.00 of 20 April 2009, by Debian.\n',
)
PEM = b'-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n'


class UbuntuCommonTests(unittest.TestCase):
    def run_command(self, index, data, returncode=0, stderr=False):
        def run(argv, **kwargs):
            self.assertEqual(argv, list(tools.COMMANDS[index][1]))
            self.assertFalse(kwargs['shell'])
            self.assertFalse(kwargs['check'])
            self.assertEqual(kwargs['timeout'], 8)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(kwargs['env']['LC_ALL'], 'C')
            kwargs['stderr' if stderr else 'stdout'].write(data)
            return subprocess.CompletedProcess(argv, returncode)
        with patch.object(tools.subprocess, 'run', side_effect=run) as mocked:
            result = tools.check_command(*tools.COMMANDS[index])
            mocked.assert_called_once()
        return result

    def test_dconf_uses_supported_help_subcommand(self):
        index=next(i for i,c in enumerate(tools.COMMANDS) if c[0]=='dpkg:dconf-cli')
        self.assertEqual(tools.COMMANDS[index][1],('/usr/bin/dconf','help'))
        self.assertEqual(self.run_command(index,OUTPUTS[index],returncode=2)['status'],'fail')
        self.assertEqual(self.run_command(index,OUTPUTS[index])['status'],'pass')

    def test_exact_mapping_and_required_extension(self):
        manifest = json.loads((PLAN / 'manifest.json').read_text())
        expected = {'dpkg:' + name for name in (
            'curl', 'git', 'gnupg', 'lsb-release', 'net-tools', 'dconf-cli',
            'x11-utils', 'fontconfig', 'unzip', 'ca-certificates')}
        self.assertEqual(set(manifest['inventoryIds']), expected)
        self.assertEqual(len(manifest['inventoryIds']), len(expected))
        self.assertEqual({entry[0] for entry in tools.COMMANDS}, expected - {'dpkg:ca-certificates'})
        config = manifest['platforms']['linux']
        self.assertEqual(config['extensions'], ['tools.py'])
        self.assertFalse(config['optional'])
        self.assertEqual(config['executable'], '/usr/bin/python3')
        for args in (config['version'], config['launch']['args']):
            self.assertEqual(args[:2], ['-I', '-c'])
            compile(args[2], 'manifest', 'exec')

    def test_each_command_individually_identified_on_either_stream(self):
        for index, output in enumerate(OUTPUTS):
            for stderr in (False, True):
                with self.subTest(index=index, stderr=stderr):
                    self.assertEqual(self.run_command(index, output, stderr=stderr)['status'], 'pass')

    def test_each_command_requires_zero_and_identification(self):
        for index, output in enumerate(OUTPUTS):
            with self.subTest(index=index):
                self.assertEqual(self.run_command(index, output, returncode=1)['status'], 'fail')
                for invalid in (b'', b'unknown option --version\n', b'unrelated program 1.0\n'):
                    self.assertEqual(self.run_command(index, invalid)['status'], 'fail')

    def test_bounded_output_fails_closed(self):
        result = self.run_command(0, OUTPUTS[0] + b'x' * tools.LIMIT)
        self.assertEqual(result['status'], 'fail')
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['stdout']), tools.LIMIT)

    def test_missing_and_timeout_fail_for_every_command(self):
        for command in tools.COMMANDS:
            for error in (FileNotFoundError('missing'), subprocess.TimeoutExpired(command[1], 8)):
                with self.subTest(command=command[0], error=type(error).__name__):
                    with patch.object(tools.subprocess, 'run', side_effect=error):
                        result = tools.check_command(*command)
                    self.assertEqual(result['status'], 'fail')
                    self.assertIn('error', result)

    def certificate_result(self, data=PEM, certs=None, error=None):
        context = Mock()
        context.get_ca_certs.return_value = [{}] if certs is None else certs
        context.load_verify_locations.side_effect = error
        with patch.object(Path, 'open', return_value=io.BytesIO(data)) as opened, \
                patch.object(tools.ssl, 'SSLContext', return_value=context):
            result = tools.check_certificates()
        opened.assert_called_once_with('rb')
        return result, context

    def test_public_bundle_parsed_and_nonempty(self):
        self.assertEqual(str(tools.CA_BUNDLE), '/etc/ssl/certs/ca-certificates.crt')
        result, context = self.certificate_result()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['caCount'], 1)
        context.load_verify_locations.assert_called_once_with(cadata=PEM.decode('ascii'))

    def test_invalid_bundle_fails_without_contents_in_report(self):
        for data in (b'', b'not a certificate', PEM + b'PRIVATE KEY secret', b'x' * (tools.CA_LIMIT + 1)):
            with self.subTest(size=len(data)):
                result, context = self.certificate_result(data)
                self.assertEqual(result['status'], 'fail')
                self.assertNotIn('secret', json.dumps(result))
                context.load_verify_locations.assert_not_called()
        self.assertEqual(self.certificate_result(certs=[])[0]['status'], 'fail')
        self.assertEqual(self.certificate_result(error=ssl.SSLError('bad PEM'))[0]['status'], 'fail')
        with patch.object(Path, 'open', side_effect=FileNotFoundError('missing')):
            self.assertEqual(tools.check_certificates()['status'], 'fail')

    def test_main_runs_all_checks_and_any_failure_fails_aggregate(self):
        for fail in (False, True):
            with patch.object(tools, 'check_command', side_effect=[
                    {'status': 'fail' if fail and i == 0 else 'pass'} for i in range(9)]) as command, \
                    patch.object(tools, 'check_certificates', return_value={'status': 'pass'}) as cert, \
                    patch('builtins.print') as output:
                self.assertEqual(tools.main(), int(fail))
            self.assertEqual(command.call_count, 9)
            cert.assert_called_once()
            report = json.loads(output.call_args.args[0])
            self.assertEqual(len(report['checks']), 10)
            self.assertEqual(report['status'], 'fail' if fail else 'pass')
        with patch.object(tools, 'check_command', return_value={'status': 'pass'}), \
                patch.object(tools, 'check_certificates', return_value={'status': 'fail'}), \
                patch('builtins.print'):
            self.assertEqual(tools.main(), 1)


if __name__ == '__main__':
    unittest.main()
