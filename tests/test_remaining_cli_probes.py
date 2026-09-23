"""Exact CLI regressions from the isolated Ubuntu application-check-6 failures.

The version/query arguments below produced identifying output and exit 0 on
2026-09-16. These tests check policy, not current guest health. They never launch
real commands. Service and hardware readiness must still use actual exit status.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('remaining_native', ROOT / 'applications/native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

VERSION_COMMANDS = (
    'adduser aptdcon bluetoothctl boltctl cloud-init cpp cpp-13 dhcpcd efibootmgr '
    'gamemoded gjs grub-probe gst-inspect-1.0 iptables-nft ntfs-3g iscsiadm '
    'pybabel-python3 chardet jsonschema rpcgen scanimage sbverify '
    'speech-dispatcher sudo tracker3 xdg-dbus-proxy xdg-open amixer '
    'file2brl mimetype ubuntu-advantage sg_inq mtdinfo markdown-it jsonpointer '
    'jsonpatch twist3 tart-guest-agent'
).split()
EXACT_ARGUMENTS = {name: ['--version'] for name in VERSION_COMMANDS}
EXACT_ARGUMENTS.update({
    'anacron': ['-V'], 'apg': ['-v'], 'lsof': ['-v'],
    'powerprofilesctl': ['version'], 'xauth': ['-V'],
    'xfs_repair': ['-V'], 'gnome-keyring': ['version'], 'mscompress': ['-V'],
    'pastebinit': ['-v'], 'netplan': ['info'],
})


class RemainingCLIProbeTests(unittest.TestCase):
    def test_exact_reviewed_argv(self):
        for name, args in EXACT_ARGUMENTS.items():
            with self.subTest(name=name):
                self.assertEqual(native.safe_arguments(name), args)

    def test_no_family_or_generic_help_fallback(self):
        for name in EXACT_ARGUMENTS:
            with self.subTest(name=name):
                self.assertIsNone(native.safe_arguments(name + '-unreviewed'))
        self.assertIsNone(native.safe_arguments('unknown-public-interface'))
        self.assertIsNone(native.safe_arguments('cpp-999'))

    def test_failed_or_ambiguous_probes_are_not_approved(self):
        # These failed, returned no identifying output, or performed extra
        # initialization. An exit-zero usage error is not a version result.
        for name in ('dmsetup', 'vmtoolsd', 'colormgr', 'networkd-dispatcher',
                     'pppd', 'netaddr', 'brltty', 'lshw', 'trace-cmd',
                     'ubuntu-report', 'spice-vdagent', 'pidof'):
            with self.subTest(name=name):
                self.assertIsNone(native.safe_arguments(name))
        self.assertEqual(native.safe_arguments('mscompress'), ['-V'])
        # Existing policy keeps lsb_release unreviewed; its --version is empty.
        self.assertIsNone(native.safe_arguments('lsb_release'))

    def test_unknown_named_interface_still_wins_over_reviewed_helper(self):
        entries = ['/usr/bin/unreviewed', '/usr/bin/sudo']
        self.assertEqual(native.select_entry_points('unreviewed', entries, {}),
                         ['/usr/bin/unreviewed'])

    def test_public_gui_priority_is_unchanged(self):
        metadata = {
            'guiLaunchEntries': [{'argv': ['/usr/bin/gui'], 'desktop': '/gui.desktop'}],
            'desktopLaunchMetadata': [{'public': True, 'terminal': False}],
        }
        self.assertEqual(native.select_entry_points(
            'sudo', ['/usr/bin/sudo', '/usr/bin/gui'], metadata), ['/usr/bin/gui'])

    def test_baseline_keeps_bounded_execution_and_propagates_failure(self):
        for name, args in EXACT_ARGUMENTS.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                executable = Path(tmp) / name
                executable.write_text('fixture')
                executable.chmod(0o755)
                entry = str(executable)

                def observer(*unused):
                    return dict(version='fixture', files=[entry], entries=[entry],
                                metadata=entry)

                for status in ('pass', 'fail'):
                    calls = []

                    def execute(argv, timeout):
                        calls.append((argv, timeout))
                        return dict(status=status, argv=argv,
                                    exitCode=0 if status == 'pass' else 1)

                    result = native.baseline(
                        {'id': 'dpkg:' + name, 'version': 'fixture'}, {'dpkg'},
                        execute, observer=observer)
                    self.assertEqual(calls, [([entry, *args], 10)])
                    self.assertEqual(result['status'], status)
                    availability = result['baseline'][0]
                    self.assertEqual(availability['entryPoints'], [entry])
                    self.assertEqual(availability['availableEntryPoints'], [entry])
                    self.assertEqual(availability['untestedEntryPoints'], [])


if __name__ == '__main__':
    unittest.main()
