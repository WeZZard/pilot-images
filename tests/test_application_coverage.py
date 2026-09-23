"""Native-source baseline fixtures. No package managers, GUI, network or VMs."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('coverage_checks', REPO / 'applications/check.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
native = checks.native_module(REPO / 'applications')


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.apps = self.root / 'applications'
        self.apps.mkdir()
        for filename in ('check.py', 'native.py'):
            shutil.copy(REPO / 'applications' / filename, self.apps / filename)
        self.selection = dict(schemaVersion=1, image='fixture', plans=[], dependencies={}, sources=['dpkg'])
        self.record = dict(id='dpkg:fixture', version='1.0')
        self.inventory = dict(os='linux', architecture='arm64', applications=[self.record])
        self.calls = []

    def file(self, name, executable=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture only; must never be executed\n')
        path.chmod(0o755 if executable else 0o644)
        return str(path)

    def execute(self, argv, timeout, startup=False):
        self.calls.append(argv)
        return dict(status='pass', argv=argv, stdout='', stderr='', detail='running at startup observation' if startup else 'exited')

    def report(self, metadata):
        return checks.run(self.apps, self.selection, self.inventory, 'fixture', self.execute,
                          observe_native=lambda *args: metadata)

    def metadata(self, files, **kwargs):
        return dict(version='1.0', metadata='fixture owned-file metadata', files=files, **kwargs)

    def test_application_inspects_and_launches_known_safe_entry(self):
        executable = self.file('bin/node', True)
        report = self.report(self.metadata([executable]))
        self.assertEqual(report['unclassified'], [])
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(self.calls, [[executable, '--version']])
        checks.validate_baseline_report(report['applications'][0])
        self.assertEqual(checks.expected_application_ids(self.apps, self.selection, self.inventory), ['native:dpkg:fixture'])
        checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_resource_only_package_has_file_evidence_not_fake_launch(self):
        resource = self.file('share/resource.dat')
        result = self.report(self.metadata([resource]))['applications'][0]
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(self.calls, [])
        self.assertEqual(result['baseline'][2]['status'], 'not-applicable')
        self.assertEqual(result['baseline'][2]['evidence']['inspectedFiles'], [resource])
        checks.validate_baseline_report(result)
        result['baseline'][2]['evidence'] = {}
        with self.assertRaises(ValueError):
            checks.validate_baseline_report(result)

    def test_package_baseline_uses_public_entrypoints_not_executable_examples(self):
        node = self.file('usr/bin/node', True)
        example = self.file('usr/share/doc/demo/examples/script', True)
        helper = self.file('usr/libexec/demo/helper', True)
        report = self.report(self.metadata([node, example, helper, str(self.root/'usr/share/doc/demo/missing')]))
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(self.calls, [[node, '--version']])
        self.assertEqual(report['applications'][0]['baseline'][0]['entryPoints'], [node])
        checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_package_launch_smoke_is_not_exhaustive_subcommand_testing(self):
        known = self.file('usr/bin/getfacl', True)
        additional = self.file('usr/bin/chacl', True)
        report = self.report(self.metadata([additional, known]))
        self.assertEqual(report['status'], 'pass')
        available = report['applications'][0]['baseline'][0]
        self.assertEqual(available['availableEntryPoints'], sorted([additional, known]))
        self.assertEqual(available['entryPoints'], [known])
        checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_unknown_named_interface_cannot_be_hidden_by_known_auxiliary(self):
        primary = self.file('usr/bin/fixture', True)
        auxiliary = self.file('usr/bin/getfacl', True)
        report = self.report(self.metadata([primary, auxiliary]))
        self.assertEqual(report['status'], 'fail')
        self.assertFalse(self.calls)

    def test_availability_does_not_read_private_package_configuration(self):
        resource = self.file('etc/private-config')
        with patch.object(Path, 'open', side_effect=AssertionError('baseline must not read configuration contents')):
            result = native.baseline(self.record, ['dpkg'], self.execute, observer=lambda *args: self.metadata([resource]))
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(self.calls)

    def test_executable_shared_library_is_not_treated_as_cli(self):
        path = Path(self.file('lib/libfixture.so.1', True))
        header = bytearray(64)
        header[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', header, 16, 3)
        struct.pack_into('<HH', header, 54, 56, 0)
        path.write_bytes(header)
        result = self.report(self.metadata([str(path)]))['applications'][0]
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['baseline'][2]['status'], 'not-applicable')
        self.assertFalse(self.calls)

    def test_broken_executable_has_coverage_but_fails_readiness(self):
        executable = self.file('bin/node', False)
        result = self.report(self.metadata([executable]))
        self.assertEqual(result['unclassified'], [])
        self.assertEqual(result['status'], 'fail')
        self.assertFalse(self.calls)
        checks.validate_baseline_report(result['applications'][0])

    def test_missing_file_and_version_drift_fail(self):
        for metadata in (self.metadata(['/missing-fixture']),
                         {**self.metadata([self.file('share/resource')]), 'version': '2.0'}):
            result = self.report(metadata)
            self.assertEqual(result['status'], 'fail')
            self.assertEqual(result['unclassified'], [])
            checks.validate_baseline_report(result['applications'][0])

    def test_unknown_command_is_never_run_as_version_or_help(self):
        result = self.report(self.metadata([self.file('bin/update-database', True)]))
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['unclassified'], [])
        self.assertEqual(self.calls, [])
        self.assertIn('isolated application manifest', result['applications'][0]['baseline'][2]['invocations'][0]['detail'])

    def test_reviewed_cli_options_are_exact_and_validator_compatible(self):
        reviewed = {
            'appstreamcli': ['--version'], 'cryptsetup': ['--version'],
            'btrfs': ['--version'], 'apt-ftparchive': ['--version'],
            'desktop-file-validate': ['--version'], 'fc-list': ['--version'],
            'glib-compile-schemas': ['--version'], 'notify-send': ['--version'],
            'aarch64-linux-gnu-cpp-13': ['--version'], 'grub-install': ['--version'],
            'dig': ['-v'], 'host': ['-V'], 'e2fsck': ['-V'],
            'gdb': ['-nx', '--version'], 'hdparm': ['-V'], 'ip': ['-Version'],
            'ping': ['-V'], 'tracepath': ['-V'], 'mawk': ['-W', 'version'],
            'ssh': ['-V'], 'pdfinfo': ['-v'], 'socat': ['-V'], 'tmux': ['-V'],
            'xxd': ['-v'], 'mksquashfs': ['-version'], 'iostat': ['-V'],
            'dumpimage': ['-V'], 'enchant-2': ['-v'], 'tic': ['-V'],
            'update-mime-database': ['-v'], 'pygmentize': ['-V'], 'lvm': ['version'],
        }
        for name, args in reviewed.items():
            with self.subTest(name=name):
                executable = self.file('usr/bin/' + name, True)
                self.calls.clear()
                report = self.report(self.metadata([executable]))
                self.assertEqual(native.safe_arguments(name), args)
                self.assertEqual(report['status'], 'pass')
                self.assertEqual(self.calls, [[executable, *args]])
                checks.validate_results(self.apps, self.selection, self.inventory, report)
                changed = copy.deepcopy(report)
                changed['applications'][0]['baseline'][2]['invocations'][0]['argv'] = [executable]
                with self.assertRaises(ValueError):
                    checks.validate_results(self.apps, self.selection, self.inventory, changed)

    def test_reviewed_daemon_interfaces_exit_instead_of_starting_services(self):
        reviewed = {
            'avahi-daemon': ['--version'], 'dbus-daemon': ['--version'],
            'dnsmasq': ['--version'], 'dirmngr': ['--version'],
            'pipewire': ['--version'], 'pipewire-pulse': ['--version'],
            'wireplumber': ['--version'], 'usbmuxd': ['--version'],
            'sssd': ['--version'], 'sshd': ['-V'],
            'rsyslogd': ['-v'], 'wpa_supplicant': ['-v'],
        }
        for name, args in reviewed.items():
            with self.subTest(name=name):
                executable = self.file('usr/sbin/' + name, True)
                observed = []
                def execute(argv, timeout, startup=False):
                    observed.append((argv, timeout, startup))
                    return self.execute(argv, timeout, startup)
                result = native.baseline(self.record, ['dpkg'], execute,
                                         observer=lambda *unused: self.metadata([executable]))
                self.assertEqual(result['status'], 'pass')
                self.assertEqual(observed, [([executable, *args], 10, False)])
                checks.validate_baseline_report(result)

    def test_version_probe_failure_is_not_waived_for_reviewed_commands(self):
        executable = self.file('usr/sbin/sshd', True)
        def execute(argv, timeout, startup=False):
            return dict(status='fail', argv=argv, stdout='', stderr='probe failed', detail='exited')
        result = native.baseline(self.record, ['dpkg'], execute,
                                 observer=lambda *unused: self.metadata([executable]))
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['baseline'][2]['status'], 'fail')
        checks.validate_baseline_report(result)

    def test_probe_rejections_and_unsafe_commands_remain_unreviewed(self):
        # These rejected or ambiguous probes must not become generic fallbacks.
        for name in ('mokutil', 'p11-kit', 'paperconf', 'vmtoolsd', 'udisksctl',
                     'debian-distro-info', 'grub-file', 'lshw', 'lsb_release',
                     'update-initramfs', 'unattended-upgrade', 'mkfs.fixture',
                     'private-sshd-helper', 'aarch64-linux-gnu-cpp-999'):
            with self.subTest(name=name):
                self.assertIsNone(native.safe_arguments(name))
                self.calls.clear()
                result = self.report(self.metadata([self.file('usr/bin/' + name, True)]))
                self.assertEqual(result['status'], 'fail')
                self.assertFalse(self.calls)

    def test_new_suite_probe_preserves_all_available_entrypoint_evidence(self):
        self.record['id'] = 'dpkg:util-linux'
        reviewed = self.file('usr/bin/lsblk', True)
        unsafe = self.file('usr/sbin/mkfs', True)
        report = self.report(self.metadata([unsafe, reviewed]))
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(self.calls, [[reviewed, '--version']])
        available = report['applications'][0]['baseline'][0]
        self.assertEqual(available['availableEntryPoints'], sorted([reviewed, unsafe]))
        self.assertEqual(available['entryPoints'], [reviewed])
        self.assertIn('not exhaustive', available['launchScope'])
        checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_unknown_source_fails_and_remains_unclassified(self):
        self.record['id'] = 'unknown:fixture'
        result = self.report(self.metadata([self.file('share/resource')]))
        self.assertEqual(result['unclassified'], ['unknown:fixture'])
        self.assertEqual(result['status'], 'fail')
        checks.validate_baseline_report(result['applications'][0])
        self.selection['sources'] = ['unknown']
        with self.assertRaisesRegex(ValueError, 'unsupported native source'):
            self.report({})

    def add_manifest(self, name, inventory_ids):
        directory = self.apps / name
        directory.mkdir()
        manifest = dict(schemaVersion=1, id=name, inventoryIds=inventory_ids, platforms={
            'linux': dict(architectures=['arm64'], executable='/fixture/tool', version=['--version'],
                          launch=dict(mode='command', args=['--version']), timeoutSeconds=2,
                          extensions=[], optional=False)})
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        self.selection['plans'].append(name)
        return directory, manifest

    def test_explicit_override_and_extension_isolation(self):
        directory, manifest = self.add_manifest('demo', ['dpkg:fixture'])
        resource = self.file('share/resource')
        self.inventory['applications'].append(dict(id='dpkg:resource', version='1.0'))
        with patch.object(checks.shutil, 'which', return_value='/fixture/tool'):
            before = self.report(self.metadata([resource]))
            manifest['platforms']['linux']['extensions'] = ['extra.py']
            (directory / 'extra.py').write_text('raise SystemExit(1)\n')
            (directory / 'manifest.json').write_text(json.dumps(manifest))
            after = self.report(self.metadata([resource]))
        self.assertEqual(before['applications'][1], after['applications'][1])
        self.assertEqual(len(after['applications']), 2)
        self.assertEqual(after['applications'][0]['extensions'][0]['check'], 'extra.py')
        self.assertNotEqual(before['planSha256'], after['planSha256'])
        self.assertEqual(checks.expected_plan_ids(self.apps, self.selection, self.inventory), ['demo', 'native:dpkg:resource'])

    def test_native_source_hash_and_legacy_exact_mapping(self):
        self.add_manifest('demo', ['demo'])
        before = checks.plan_digest(self.apps, self.selection)
        with (self.apps / 'native.py').open('a') as stream:
            stream.write('\n# fixture change\n')
        self.assertNotEqual(before, checks.plan_digest(self.apps, self.selection))
        del self.selection['sources']
        before = checks.plan_digest(self.apps, self.selection)
        with (self.apps / 'native.py').open('a') as stream:
            stream.write('\n# another fixture change\n')
        self.assertEqual(before, checks.plan_digest(self.apps, self.selection))
        with patch.object(checks.shutil, 'which', return_value='/fixture/tool'):
            result = self.report({})
        self.assertEqual(result['unclassified'], ['dpkg:fixture'])
        self.assertEqual(checks.expected_plan_ids(self.apps, self.selection, self.inventory), ['demo'])

    def test_native_report_validator_rejects_fabricated_success(self):
        result = self.report(self.metadata([self.file('bin/node', True)]))['applications'][0]
        for field in ('invocations',):
            changed = copy.deepcopy(result)
            changed['baseline'][2].pop(field)
            with self.assertRaises(ValueError):
                checks.validate_baseline_report(changed)
        changed = copy.deepcopy(result)
        changed['baseline'][1]['observed'] = 'wrong'
        with self.assertRaises(ValueError):
            checks.validate_baseline_report(changed)

    def test_dpkg_command_boundary_observes_status_version_and_owned_files(self):
        path = self.file('share/data')
        answers = ['installed\t1.0', path + '\n']
        def execute(argv, timeout):
            self.calls.append(argv)
            return dict(status='pass', stdout=answers.pop(0))
        metadata = native.installed_metadata('dpkg', 'fixture', execute, ())
        self.assertEqual(metadata['files'], [path])
        self.assertEqual(metadata['version'], '1.0')
        self.assertEqual(self.calls[-1], ['dpkg-query', '-L', 'fixture'])

    def test_dpkg_actual_diversion_notices_do_not_become_paths(self):
        raw = ('/.\n/bin\npackage diverts others to: /bin.usr-is-merged\n'
               '/lib\ndiverted by base-files to: /lib.usr-is-merged\n'
               '/sbin\ndiverted by base-files to: /sbin.usr-is-merged\n'
               '/usr/bin/tool\nlocally diverted to: /usr/bin/tool.local\n')
        self.assertEqual(native.dpkg_owned_files(raw), ['/.', '/bin', '/lib', '/sbin', '/usr/bin/tool'])
        for malformed in ('diverted by base-files to: /lib.usr-is-merged\n',
                          '/lib\nrandom notice\n', '/lib\ndiverted by base-files to: relative\n'):
            with self.assertRaises(ValueError):
                native.dpkg_owned_files(malformed)

    def test_diversion_notice_does_not_hide_missing_original_executable(self):
        original = str(self.root / 'bin/missing')
        diverted = self.file('bin/diverted', True)
        answers = ['installed\t1.0', original + '\ndiverted by fixture to: ' + diverted + '\n']
        metadata = native.installed_metadata('dpkg', 'fixture', lambda *args: dict(status='pass', stdout=answers.pop(0)), ())
        self.assertEqual(metadata['files'], [original])
        result = self.report(metadata)
        self.assertEqual(result['status'], 'fail')
        self.assertIn('missing or broken symlink', result['applications'][0]['baseline'][0]['detail'])
        self.assertFalse(self.calls)

    def test_resource_sample_is_explicitly_not_full_package_integrity(self):
        files = [self.file('share/data-%03d' % index) for index in range(100)]
        result = self.report(self.metadata(files))
        app = result['applications'][0]
        available, _, launch = app['baseline']
        self.assertEqual(len(available['inspectedFiles']), 32)
        self.assertEqual(available['declaredFileCount'], 100)
        self.assertEqual(available['inspectedFileCount'], 32)
        self.assertIn('not package integrity', available['inspectionScope'])
        self.assertEqual(available['inspectedFilesSha256'], hashlib.sha256(json.dumps(files[:32], separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest())
        for field in ('inspectedFiles', 'inspectedFileCount', 'inspectedFilesSha256'):
            self.assertEqual(launch['evidence'][field], available[field])
        checks.validate_results(self.apps, self.selection, self.inventory, result)
        Path(files[-1]).unlink()
        self.assertEqual(self.report(self.metadata(files))['status'], 'pass')

    def test_file_sample_retains_declared_launch_and_desktop_metadata(self):
        files = [self.file('share/data-%03d' % index) for index in range(40)]
        executable = self.file('bin/Demo', True)
        desktop = Path(self.file('share/applications/demo.desktop'))
        desktop.write_text('[Desktop Entry]\nType=Application\nExec=Demo %U\n')
        with patch.object(native.shutil, 'which', return_value=executable):
            report = self.report(self.metadata(files + [executable, str(desktop)]))
        available = report['applications'][0]['baseline'][0]
        self.assertIn(executable, available['inspectedFiles'])
        self.assertIn(str(desktop), available['inspectedFiles'])
        self.assertEqual(available['declaredFileCount'], 42)
        self.assertEqual(available['inspectedFileCount'], 34)
        checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_brew_formula_and_cask_read_installed_not_available_version(self):
        for source, group, key, installed in [('brew-formula', 'formulae', 'name', [{'version': '1.0'}]),
                                             ('brew-cask', 'casks', 'token', '1.0')]:
            answers = [json.dumps({group: [{key: 'fixture', 'installed': installed, 'version': '2.0'}]}), self.file('share/brew')]
            metadata = native.installed_metadata(source, 'fixture', lambda *args: dict(status='pass', stdout=answers.pop(0)), ())
            self.assertEqual(metadata['version'], '1.0')

    def test_npm_bin_metadata_and_resource_only(self):
        root = self.root / 'node_modules'
        package = root / '@fixture/demo'
        package.mkdir(parents=True)
        metadata = package / 'package.json'
        metadata.write_text(json.dumps(dict(name='@fixture/demo', version='1.0')))
        observer = lambda *args: dict(status='pass', stdout=str(root))
        result = native.installed_metadata('npm', '@fixture/demo', observer, ())
        self.assertEqual(result['entries'], [])
        metadata.write_text(json.dumps(dict(name='@fixture/demo', version='1.0', bin={'demo': 'cli.js'})))
        result = native.installed_metadata('npm', '@fixture/demo', observer, ())
        self.assertEqual(result['entries'], [str(package / 'cli.js')])
        metadata.write_text(json.dumps(dict(name='@fixture/demo', version='1.0', bin='../outside')))
        with self.assertRaises(ValueError):
            native.installed_metadata('npm', '@fixture/demo', observer, ())

    def test_bundle_resolves_declared_executable_and_uses_shared_startup_baseline(self):
        import plistlib
        root = self.root / 'Applications'
        app = root / 'Fixture.app'
        executable = self.file('Applications/Fixture.app/Contents/MacOS/Fixture', True)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(CFBundleIdentifier='org.fixture.app', CFBundleExecutable='Fixture', CFBundleVersion='1.0')))
        result = native.baseline(dict(id='bundle:org.fixture.app', version='1.0'), ['bundle'], self.execute, roots=[root])
        self.assertEqual(result['baseline'][0]['entryPoints'], [executable])
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(self.calls, [[executable]])
        checks.validate_baseline_report(result)
        selection = dict(self.selection, sources=['bundle'])
        inventory = dict(self.inventory, os='macos', applications=[dict(id='bundle:org.fixture.app', version='1.0')])
        report = dict(schemaVersion=1, image='fixture', buildId='fixture', os='macos', architecture='arm64', planSha256=checks.plan_digest(self.apps, selection), sources=['bundle'], dependencies={}, applications=[result], unclassified=[], status='pass')
        checks.validate_results(self.apps, selection, inventory, report)
        result['baseline'][2]['invocations'][0]['argv'].append('--unexpected')
        with self.assertRaises(ValueError):
            checks.validate_results(self.apps, selection, inventory, report)

    def test_desktop_application_uses_shared_launch_without_shell_interpolation(self):
        executable = self.file('bin/Demo', True)
        desktop = Path(self.file('share/applications/demo.desktop'))
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Demo\nExec=Demo --new-window %U\n')
        with patch.object(native.shutil, 'which', return_value=executable):
            report = self.report(self.metadata([str(desktop), executable]))
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(self.calls, [[executable, '--new-window']])
        checks.validate_results(self.apps, self.selection, self.inventory, report)
        report = json.loads(json.dumps(report))
        report['applications'][0]['baseline'][2]['invocations'][0]['argv'].append('unrequested')
        with self.assertRaises(ValueError):
            checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_distinct_desktop_argv_are_independent_launch_entries(self):
        executable = self.file('bin/Demo', True)
        files = [executable]
        for name, command in [('main', 'Demo --new-window %U'), ('settings', 'Demo --settings'),
                              ('alias', 'Demo --new-window %U')]:
            desktop = Path(self.file('share/applications/' + name + '.desktop'))
            desktop.write_text('[Desktop Entry]\nType=Application\nExec=' + command + '\n')
            files.append(str(desktop))
        with patch.object(native.shutil, 'which', return_value=executable):
            result = native.baseline(self.record, ['dpkg'], self.execute, observer=lambda *args: self.metadata(files))
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(self.calls, [[executable, '--new-window'], [executable, '--settings']])
        available = result['baseline'][0]
        self.assertEqual(available['entryPoints'], [executable, executable])
        self.assertEqual(len(available['guiLaunchEntries']), 3)
        self.assertEqual(available['guiCommands'], {})
        checks.validate_baseline_report(result)
        report=dict(schemaVersion=1,image='fixture',buildId='fixture',os='linux',architecture='arm64',planSha256=checks.plan_digest(self.apps,self.selection),sources=self.selection['sources'],dependencies={},applications=[result],unclassified=[],status='pass')
        checks.validate_results(self.apps,self.selection,self.inventory,report)
        partial=json.loads(json.dumps(report))
        partial['applications'][0]['baseline'][0]['entryPoints'].pop()
        partial['applications'][0]['baseline'][2]['invocations'].pop()
        with self.assertRaises(ValueError):
            checks.validate_results(self.apps,self.selection,self.inventory,partial)

    def test_one_failed_desktop_variant_fails_the_package(self):
        executable = self.file('bin/Demo', True)
        files = [executable]
        for index in range(2):
            desktop = Path(self.file('share/applications/demo-%d.desktop' % index))
            desktop.write_text('[Desktop Entry]\nType=Application\nExec=Demo --mode=%d\n' % index)
            files.append(str(desktop))
        def execute(argv, timeout, startup=False):
            result = self.execute(argv, timeout, startup)
            if argv[-1] == '--mode=1':
                result['status'] = 'fail'
            return result
        with patch.object(native.shutil, 'which', return_value=executable):
            result = native.baseline(self.record, ['dpkg'], execute, observer=lambda *args: self.metadata(files))
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(len(result['baseline'][2]['invocations']), 2)
        self.assertEqual(len(self.calls), 2)

    def test_public_gui_is_selected_over_unrelated_cli_auxiliary(self):
        self.record['id'] = 'dpkg:gnome-calculator'
        executable = self.file('usr/bin/gnome-calculator', True)
        auxiliary = self.file('usr/bin/gcalccmd', True)
        desktop = Path(self.file('usr/share/applications/org.gnome.Calculator.desktop'))
        desktop.write_text('[Desktop Entry]\nType=Application\nExec=gnome-calculator\nTerminal=false\n')
        with patch.object(native.shutil, 'which', return_value=executable):
            result = native.baseline(self.record, ['dpkg'], self.execute,
                observer=lambda *args: self.metadata([auxiliary, executable, str(desktop)]))
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(self.calls, [[executable]])
        available = result['baseline'][0]
        self.assertEqual(available['availableEntryPoints'], sorted([auxiliary, executable]))
        self.assertEqual(available['entryPoints'], [executable])
        self.assertEqual(available['untestedEntryPoints'], [auxiliary])
        self.assertEqual(native.select_entry_points('gnome-calculator', available['availableEntryPoints'], available), [executable])
        self.assertTrue(available['desktopLaunchMetadata'][0]['public'])
        checks.validate_baseline_report(result)
        report = dict(schemaVersion=1, image='fixture', buildId='fixture', os='linux', architecture='arm64', planSha256=checks.plan_digest(self.apps, self.selection), sources=self.selection['sources'], dependencies={}, applications=[result], unclassified=[], status='pass')
        checks.validate_results(self.apps, self.selection, self.inventory, report)
        for field, value in [('untestedEntryPoints', []), ('desktopLaunchMetadata', [])]:
            changed = json.loads(json.dumps(report))
            changed['applications'][0]['baseline'][0][field] = value
            with self.assertRaises(ValueError):
                checks.validate_results(self.apps, self.selection, self.inventory, changed)

    def test_terminal_shortcut_uses_only_reviewed_cli_probe(self):
        self.record['id'] = 'dpkg:python3.12'
        executable = self.file('usr/bin/python3.12', True)
        desktop = Path(self.file('usr/share/applications/python3.12.desktop'))
        desktop.write_text('[Desktop Entry]\nType=Application\nExec=/usr/bin/python3.12\nTerminal=true\nNoDisplay=true\n')
        with patch.object(native.shutil, 'which', return_value=executable):
            report = self.report(self.metadata([str(desktop)]))
        result = report['applications'][0]
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(self.calls, [[executable, '-I', '-S', '--version']])
        self.assertEqual(result['baseline'][2]['invocations'][0]['detail'], 'exited')
        available = result['baseline'][0]
        self.assertEqual(available['guiLaunchEntries'], [])
        self.assertEqual(available['terminalLaunchEntries'][0]['argv'], self.calls[0])
        self.assertEqual(available['desktopLaunchMetadata'][0]['declaredArgv'], [executable])
        checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_unsupported_terminal_commands_and_wrappers_are_not_started(self):
        desktop = Path(self.file('share/applications/terminal.desktop'))
        for command in ('htop', 'unknown-tool', 'python3.12 script.py', 'bash', 'sudo python3.12', 'env python3.12'):
            with self.subTest(command=command):
                executable = self.file('bin/' + command.split()[0], True)
                desktop.write_text('[Desktop Entry]\nType=Application\nTerminal=true\nExec=' + command + '\n')
                with patch.object(native.shutil, 'which', return_value=executable):
                    result = self.report(self.metadata([str(desktop)]))
                self.assertEqual(result['status'], 'fail')
                self.assertFalse(self.calls)

    def test_document_handler_requires_input_and_never_launches_partial_argv(self):
        desktop = Path(self.file('share/applications/apport-gtk.desktop'))
        desktop.write_text('[Desktop Entry]\nType=Application\nNoDisplay=true\nMimeType=text/x-apport;\nExec=/usr/share/apport/apport-gtk -c %f\n')
        result = self.report(self.metadata([str(desktop)]))
        self.assertEqual(result['status'], 'fail')
        self.assertIn('input requires', result['applications'][0]['baseline'][0]['detail'])
        self.assertFalse(self.calls)

    def test_hidden_gui_does_not_justify_omitting_unreviewed_helpers(self):
        executable = self.file('bin/Demo', True)
        helper = self.file('bin/unknown-helper', True)
        desktop = Path(self.file('share/applications/demo.desktop'))
        desktop.write_text('[Desktop Entry]\nType=Application\nNoDisplay=true\nExec=Demo\n')
        with patch.object(native.shutil, 'which', return_value=executable):
            result = native.baseline(self.record, ['dpkg'], self.execute,
                observer=lambda *args: self.metadata([str(desktop), executable, helper]))
        self.assertEqual(result['status'], 'fail')
        self.assertIn(helper, result['baseline'][0]['entryPoints'])
        self.assertEqual(result['baseline'][0]['untestedEntryPoints'], [])

    def test_desktop_shell_and_privilege_wrappers_require_explicit_plan(self):
        desktop = Path(self.file('share/applications/wrapper.desktop'))
        for command in ('sh -c "touch /tmp/no"', 'sudo tool', 'pkexec tool', 'env tool'):
            desktop.write_text('[Desktop Entry]\nType=Application\nExec=' + command + '\n')
            report = self.report(self.metadata([str(desktop)]))
            self.assertEqual(report['status'], 'fail')
        self.assertFalse(self.calls)

    def test_validator_rejects_missing_coverage_skips_and_parameter_drift(self):
        report = self.report(self.metadata([self.file('bin/node', True)]))
        checks.validate_results(self.apps, self.selection, self.inventory, report)
        changes = []
        missing = copy.deepcopy(report)
        missing['applications'] = []
        changes.append(missing)
        skipped = copy.deepcopy(report)
        skipped['applications'][0]['status'] = 'not-applicable'
        changes.append(skipped)
        unsafe = copy.deepcopy(report)
        unsafe['applications'][0]['baseline'][2]['invocations'][0]['argv'].append('--unsafe')
        changes.append(unsafe)
        stale = copy.deepcopy(report)
        stale['planSha256'] = '0' * 64
        changes.append(stale)
        sources = copy.deepcopy(report)
        sources['sources'] = []
        changes.append(sources)
        for changed in changes:
            with self.assertRaises(ValueError):
                checks.validate_results(self.apps, self.selection, self.inventory, changed)

    def test_validator_accepts_failed_report_without_confusing_coverage(self):
        report = self.report(self.metadata([self.file('bin/maintenance', True)]))
        checks.validate_results(self.apps, self.selection, self.inventory, report)
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['unclassified'], [])
        report['status'] = 'pass'
        with self.assertRaises(ValueError):
            checks.validate_results(self.apps, self.selection, self.inventory, report)

    def test_snap_metadata_distinguishes_apps_from_runtime_resources(self):
        root = self.root / 'snap/fixture/1'
        (root / 'meta').mkdir(parents=True)
        (root.parent / 'current').symlink_to('1')
        metadata_path = root / 'meta/snap.yaml'
        (root / 'runtime').write_text('fixture data')
        metadata_path.write_text('name: fixture\nversion: 1.0\ntype: base\n')
        real_path = Path
        def fixture_path(value):
            return self.root / 'snap' if value == '/snap' else real_path(value)
        execute = lambda *args: dict(status='pass', stdout='Name Version Rev Tracking Publisher Notes\nfixture 1.0 1 stable fixture -\n')
        with patch.object(native, 'Path', side_effect=fixture_path):
            resource = native.installed_metadata('snap', 'fixture', execute, ())
            self.assertEqual(resource['entries'], [])
            self.assertEqual(resource['files'], [str(root.parent / 'current/meta/snap.yaml')])
            metadata_path.write_text('name: fixture\nversion: 1.0\napps:\n  fixture:\n    command: bin/fixture\n')
            application = native.installed_metadata('snap', 'fixture', execute, ())
            self.assertEqual(application['entries'], ['/snap/bin/fixture'])
            self.assertTrue(application['requiresLaunch'])

    def test_snap_installed_block_mapping_accepts_common_scalar_contents(self):
        # snapd snap/info_snap_yaml.go defines apps as a named mapping, with
        # description/environment/plugs alongside it; punctuation there is data.
        resource = ('name: fixture\nversion: 1.0\narchitectures:\n- arm64\n'
                    'description: |\n  Runtime {data} & tools * for applications.\n'
                    'environment:\n  PATH: ${SNAP}/usr/bin:${PATH}\n'
                    'plugs:\n  content: {}\n')
        self.assertEqual(native.snap_app_names(resource, 'fixture'), [])
        self.assertEqual(native.snap_app_names(resource + 'apps: {} # no apps\n', 'fixture'), [])
        application = (resource + '"apps": # public entries\n'
                       '    fixture: # main\n'
                       '        command: bin/fixture\n'
                       '        environment:\n'
                       '            FLAGS: "{x} * &"\n'
                       '    helper:\n'
                       '        command: bin/helper\n')
        self.assertEqual(native.snap_app_names(application, 'fixture'), ['fixture', 'helper'])

    def test_unsupported_snap_shapes_fail_instead_of_becoming_resource_only(self):
        for suffix in ('apps: *alias\n', 'apps: {fixture: {command: bin/fixture}}\n',
                       'apps:\n', 'apps: []\n', 'apps:\n  <<: *alias\n',
                       'apps:\n  fixture:\n    command: bin/fixture\n  fixture:\n    command: other\n',
                       'apps: {}\napps: {}\n', '<<: *other\n',
                       '"a\\u0070ps": {}\n'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                native.snap_app_names('name: fixture\n' + suffix, 'fixture')
        with self.assertRaises(ValueError):
            native.snap_app_names('name: another\n', 'fixture')

    def test_repository_scope_does_not_turn_os_catalog_into_test_selection(self):
        for image in ('macos26', 'ubuntu2404'):
            selection = checks.load(REPO / 'images' / image / 'application-tests.json')
            inventory = checks.load(REPO / 'images' / image / 'applications.json')['inventory']
            mapping = checks.expected_plan_inventory_ids(REPO / 'applications', selection, inventory)
            covered = {value for values in mapping.values() for value in values}
            self.assertEqual(selection['scope'],'provisioned')
            self.assertEqual(list(mapping),selection['plans'])
            self.assertFalse(any(key.startswith('native:') for key in mapping))
            self.assertTrue({a['id'] for a in inventory['applications']} - covered)
            self.assertEqual(set(selection['provisioning']),set(selection['plans']))


if __name__ == '__main__':
    unittest.main()
