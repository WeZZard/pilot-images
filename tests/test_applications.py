"""Fixture-only application plans, evidence gates, and vmctl orchestration."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

REPO = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


checks = module('checks', REPO / 'applications/check.py')
host = module('inventory', REPO / 'host/inventory.py')
with patch.dict(sys.modules, inventory=host):
    acceptance = module('acceptance', REPO / 'host/application-acceptance.py')
    clone = module('clone_checks', REPO / 'host/check-clone.py')
capture = module('capture_checks', REPO / 'applications/cua-driver/capture.py')


def passed(argv, timeout, startup=False, temporary_root=None):
    directory='/fixture/home/snap/firefox/common/pilot-app-fixture'
    result=dict(status='pass', argv=[a.replace('{temporary}',directory) for a in argv])
    if temporary_root is not None:
        result.update(temporaryRoot=temporary_root,temporaryDirectory=directory)
    return result


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.apps = self.root / 'applications'
        (self.apps / 'demo').mkdir(parents=True)
        shutil.copy(REPO / 'applications/check.py', self.apps / 'check.py')
        self.config = dict(architectures=['arm64'], executable=sys.executable,
            version=['--version'], launch=dict(mode='command', args=['--version']),
            timeoutSeconds=2, extensions=[], optional=False)
        self.manifest = dict(schemaVersion=1, id='demo', inventoryIds=['demo'], platforms={'linux': self.config})
        self.selection = dict(schemaVersion=1, image='fixture', plans=['demo'], dependencies={})
        self.inventory = dict(os='linux', architecture='arm64', applications=[dict(id='demo')])
        self.save()

    def save(self):
        (self.apps / 'demo/manifest.json').write_text(json.dumps(self.manifest))

    def run_plan(self, execute=passed):
        return checks.run(self.apps, self.selection, self.inventory, 'build-1', execute)

    def test_baseline_only_configuration_passes(self):
        report = self.run_plan()
        self.assertEqual(report['status'], 'pass')
        self.assertEqual([c['check'] for c in report['applications'][0]['baseline']], ['availability', 'version', 'launch'])
        self.assertEqual(report['applications'][0]['extensions'], [])

    def test_failed_baseline_cannot_be_replaced_by_extension(self):
        self.config['extensions'] = ['extra.py']
        (self.apps / 'demo/extra.py').write_text('pass\n')
        self.save()
        def execute(argv, timeout, startup=False):
            return dict(status='pass' if argv[-1].endswith('extra.py') else 'fail')
        report = self.run_plan(execute)
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['applications'][0]['extensions'][0]['status'], 'pass')

    def test_extension_failure_distinct_from_baseline(self):
        self.config['extensions'] = ['extra.py']
        (self.apps / 'demo/extra.py').write_text('raise SystemExit(1)\n')
        self.save()
        report = self.run_plan(lambda argv, timeout, startup=False: dict(status='fail' if argv[-1].endswith('extra.py') else 'pass'))
        self.assertEqual(report['status'], 'fail')
        self.assertTrue(all(c['status'] == 'pass' for c in report['applications'][0]['baseline']))

    def test_extension_selection_is_isolated(self):
        (self.apps / 'other').mkdir()
        other = copy.deepcopy(self.manifest)
        other.update(id='other', inventoryIds=[])
        (self.apps / 'other/manifest.json').write_text(json.dumps(other))
        self.selection['plans'].append('other')
        before = self.run_plan()['applications'][1]
        self.config['extensions'] = ['extra.py']
        (self.apps / 'demo/extra.py').write_text('pass\n')
        self.save()
        self.assertEqual(self.run_plan()['applications'][1], before)

    def test_missing_required_executable_fails(self):
        self.config['executable'] = '/missing-fixture-tool'
        self.save()
        self.assertEqual(self.run_plan()['status'], 'fail')

    def test_optional_absent_is_not_a_pass_and_installed_optional_fails(self):
        self.config.update(optional=True, executable='/missing-fixture-tool')
        self.save()
        self.inventory['applications'] = []
        self.assertEqual(self.run_plan()['applications'][0]['status'], 'not-applicable')
        self.inventory['applications'] = [dict(id='demo')]
        self.assertEqual(self.run_plan()['status'], 'fail')

    def test_unsupported_installed_platform_fails(self):
        self.inventory['os'] = 'macos'
        self.assertEqual(self.run_plan()['status'], 'fail')
        self.inventory['os'] = 'linux'
        self.inventory['architecture'] = 'unsupported'
        self.assertEqual(self.run_plan()['status'], 'fail')

    def test_unclassified_and_explicit_dependency_coverage(self):
        self.inventory['applications'].append(dict(id='lib-demo'))
        report = self.run_plan()
        self.assertEqual(report['unclassified'], ['lib-demo'])
        self.assertEqual(report['status'], 'fail')
        self.selection['dependencies']['lib-demo'] = dict(plan='demo', reason='The demo launch loads this library.')
        self.assertEqual(self.run_plan()['status'], 'pass')
        self.selection['dependencies']['lib-demo']['plan'] = 'missing'
        with self.assertRaises(ValueError):
            self.run_plan()

    def test_missing_plan_and_extension_traversal_fail(self):
        self.selection['plans'] = ['missing']
        with self.assertRaises(FileNotFoundError):
            self.run_plan()
        self.selection['plans'] = ['../demo']
        with self.assertRaises(ValueError):
            self.run_plan()
        self.selection['plans'] = ['demo']
        self.config['extensions'] = ['../other.py']
        self.save()
        with self.assertRaises(ValueError):
            self.run_plan()

    def test_plan_hash_changes_only_for_selected_source_files(self):
        before = checks.plan_digest(self.apps, self.selection)
        (self.apps / 'demo/__pycache__').mkdir()
        (self.apps / 'demo/__pycache__/x.pyc').write_bytes(b'cache')
        self.assertEqual(checks.plan_digest(self.apps, self.selection), before)
        (self.apps / 'demo/PLAN.md').write_text('Changed plan.\n')
        self.assertNotEqual(checks.plan_digest(self.apps, self.selection), before)

    def test_real_fixture_command_timeout_and_process_cleanup(self):
        self.assertEqual(checks.command([sys.executable, '-c', 'print("fixture")'], 2)['status'], 'pass')
        self.assertEqual(checks.command([sys.executable, '-c', 'import time;time.sleep(10)'], .02)['status'], 'fail')
        self.assertEqual(checks.command([sys.executable, '-c', 'import time;time.sleep(10)'], .02, startup=True)['status'], 'pass')
        self.assertEqual(checks.command([sys.executable, '-c', 'pass'], 2, startup=True)['status'], 'fail')

    def test_command_output_bound_and_no_shell(self):
        result = checks.command([sys.executable, '-c', 'print("x"*10000)'], 2)
        self.assertTrue(result['stdoutTruncated'])
        self.assertEqual(len(result['stdout']), 8192)
        result = checks.command(['/missing-fixture'], 1)
        self.assertEqual(result['status'], 'fail')

    def test_acceptance_receipt_binds_report_plan_and_stopped_association(self):
        image = self.root / 'images/fixture'
        image.mkdir(parents=True)
        (image / 'application-tests.json').write_text(json.dumps(self.selection))
        report = self.run_plan()
        report['inventorySha256'] = 'a' * 64
        portable = self.root / 'portable.json'
        portable.write_text(json.dumps(dict(inventory=self.inventory, provenance=dict(evidenceId='build-1', rawSha256='a' * 64))))
        evidence = self.root / 'build-1'; evidence.mkdir()
        report_path = evidence / 'report.json'
        report_path.write_text(json.dumps(report))
        assoc = self.root / 'association.json'
        assoc.write_text(json.dumps(dict(schemaVersion=2, image='fixture', inventorySha256='b' * 64,
            base=dict(base_vm='work', path='/fixture/work', files={name: dict(st_dev=1, st_ino=1, st_size=1, st_mtime_ns=1) for name in ('config.json', 'disk.img')}))))
        receipt = self.root / 'receipt.json'
        with patch.object(acceptance, 'REPO', self.root):
            (image / 'checks').mkdir()
            for name in ('acceptance', 'no-secrets'):
                script = image / 'checks' / (name + '.sh')
                script.write_text('#!/bin/sh\nexit 0\n')
                (evidence / script.name).write_bytes(script.read_bytes())
                (evidence / (name + '.log')).write_text('fixture check exited zero\n')
                acceptance.record_image_check(evidence, 'fixture', name, script, 0)
            acceptance.seal(report_path, assoc, portable, receipt, 'fixture')
            self.assertEqual(acceptance.verify(receipt, assoc, portable, 'fixture'), str(report_path))
            report_path.write_text(report_path.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'report changed'):
                acceptance.verify(receipt, assoc, portable, 'fixture')
            report_path.write_text(json.dumps(report))
            self.config['launch']['args'] = ['--help']
            self.save()
            with self.assertRaisesRegex(ValueError, 'stale'):
                acceptance.verify(receipt, assoc, portable, 'fixture')

    def test_host_accepts_native_coverage_but_rejects_false_native_evidence(self):
        shutil.copy(REPO / 'applications/native.py', self.apps / 'native.py')
        self.selection['sources'] = ['dpkg']
        self.inventory['applications'].append(dict(id='dpkg:resource', version='1'))
        resource = self.root / 'resource.txt'
        resource.write_text('Fixture package resource.')
        report = checks.run(self.apps, self.selection, self.inventory, 'build-1', passed,
            observe_native=lambda *args: dict(files=[str(resource)], metadata='fixture dpkg metadata', version='1'))
        self.assertEqual(report['status'], 'pass')
        report['inventorySha256'] = 'a' * 64
        image = self.root / 'images/fixture'
        image.mkdir(parents=True)
        (image / 'application-tests.json').write_text(json.dumps(self.selection))
        portable = self.root / 'portable.json'
        portable.write_text(json.dumps(dict(inventory=self.inventory, provenance=dict(evidenceId='build-1', rawSha256='a' * 64))))
        report_path = self.root / 'report.json'
        with patch.object(acceptance, 'REPO', self.root):
            report_path.write_text(json.dumps(report))
            acceptance.validate_report(report_path, portable, 'fixture')
            for mutation in ('skip', 'version', 'resource', 'identity', 'missing'):
                bad = copy.deepcopy(report)
                native = bad['applications'][-1]
                if mutation == 'skip': native['status'] = 'not-applicable'
                if mutation == 'version': native['baseline'][1].update(expected='wrong', observed='wrong')
                if mutation == 'resource': native['baseline'][2]['evidence'] = {}
                if mutation == 'identity': native['inventoryIds'] = ['dpkg:another']
                if mutation == 'missing': bad['applications'].pop()
                report_path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError, msg=mutation):
                    acceptance.validate_report(report_path, portable, 'fixture')

    def test_repository_plans_test_provisioned_apps_without_expanding_os_inventory(self):
        for image in ('macos26', 'ubuntu2404'):
            selection = checks.load(REPO / 'images' / image / 'application-tests.json')
            observed = checks.load(REPO / 'images' / image / 'applications.json')['inventory']
            with patch.object(checks.shutil, 'which', return_value='/fixture'):
                def unavailable(*args):
                    raise ValueError('fixture has no installed native metadata')
                report = checks.run(REPO / 'applications', selection, observed, 'fixture', passed, observe_native=unavailable)
            self.assertEqual(report['status'], 'pass')
            self.assertEqual(report['unclassified'], [])
            self.assertEqual([r['id'] for r in report['applications']],selection['plans'])
            self.assertTrue(report['notTestedInventoryIds'])
            self.assertFalse(any(r['id'].startswith('native:') for r in report['applications']))


class PathAndCaptureTests(unittest.TestCase):
    def test_state_precedence_canonicalization_and_store_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            vm = root / 'vms'
            vm.mkdir()
            alias = root / 'alias'
            alias.symlink_to(vm)
            env = dict(HOME=str(root), XDG_STATE_HOME=str(root / 'xdg'), PILOT_IMAGES_STATE_DIR=str(root / 'override'))
            value = host.state_directory(vm, env)
            self.assertEqual(value, root / 'override/stores' / hashlib.sha256(str(vm).encode()).hexdigest())
            self.assertEqual(value, host.state_directory(alias, env))
            self.assertNotEqual(value, host.state_directory(root / 'other', env))
            del env['PILOT_IMAGES_STATE_DIR']
            self.assertTrue(str(host.state_directory(vm, env)).startswith(str(root / 'xdg/pilot-images/stores')))
            del env['XDG_STATE_HOME']
            self.assertTrue(str(host.state_directory(vm, env)).startswith(str(root / '.local/state/pilot-images/stores')))

    def test_png_validation(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\0\0\0')) + chunk(b'IEND', b'')
        self.assertEqual(capture.png_dimensions(png), (1, 1))
        for invalid in (b'not a PNG', png[:-1], png + b'extra', png[:40] + b'x' + png[41:]):
            with self.assertRaises(ValueError):
                capture.png_dimensions(invalid)

    def test_image_prerequisites_are_not_optional_repairs(self):
        mac = (REPO / 'images/macos26/guest/30-node.zsh').read_text()
        self.assertIn('/usr/local/pilot-node', mac)
        self.assertIn('~/.zshenv', mac)
        linux = (REPO / 'images/ubuntu2404/guest/45-capture.sh').read_text()
        self.assertIn('WaylandEnable=false', linux)
        self.assertIn('serve --no-overlay', linux)
        self.assertNotIn('DISPLAY=:0', linux)
        driver = (REPO / 'images/macos26/guest/60-cua-driver.zsh').read_text()
        self.assertNotIn('phase 60 SKIPPED', driver)
        self.assertNotIn("Run 'cua-driver permissions grant'", driver)
        self.assertFalse((REPO / 'lines').exists())
        self.assertFalse((REPO / 'inventories').exists())


class CloneFixtureTests(unittest.TestCase):
    def test_fresh_clone_noninteractive_commands_and_failure_cleanup(self):
        for fail in (False, True):
            with tempfile.TemporaryDirectory() as d:
                evidence = Path(d).resolve() / 'accept-fixture'
                evidence.mkdir()
                calls = []
                def invoke(argv, **kwargs):
                    calls.append(argv)
                    stdout, rc = '', 0
                    if argv[1] == 'acquire':
                        stdout = json.dumps(dict(vm='pilot-fixture', image_kind='linux'))
                    elif argv[1] == 'exec' and '--output' in argv:
                        rc = 1 if fail else 0
                    elif argv[1] == 'pull':
                        target = Path(argv[-1])
                        if target.name == 'inventory.json':
                            target.write_text(json.dumps(dict(schemaVersion=1, os='linux', architecture='arm64', collectedAt='2026-09-16T00:00:00Z', sources=[dict(id='fixture', status='unavailable')], applications=[])))
                        else:
                            raw = evidence / 'inventory.json'
                            selection = checks.load(REPO / 'images/ubuntu2404/application-tests.json')
                            with patch.object(checks.shutil, 'which', return_value='/fixture'):
                                report = checks.run(REPO / 'applications', selection, json.loads(raw.read_text()), evidence.name, passed)
                            report['inventorySha256'] = hashlib.sha256(raw.read_bytes()).hexdigest()
                            if fail: report['status'] = 'fail'
                            target.write_text(json.dumps(report))
                    return subprocess.CompletedProcess(argv, rc, stdout, '')
                with patch.dict(sys.modules, inventory=host):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'acceptance failed'):
                            clone.check_clone('ubuntu2404', evidence, invoke)
                    else:
                        clone.check_clone('ubuntu2404', evidence, invoke)
                self.assertIn('--env', calls[0])
                self.assertIn('none', calls[0])
                self.assertEqual(calls[-1], ['vmctl', 'release', 'pilot-fixture'])
                commands = [c for c in calls if c[1] == 'exec']
                self.assertTrue(all('-lic' not in c and 'nvm' not in c for c in commands))
                self.assertTrue((evidence / 'applications.json').exists())


if __name__ == '__main__':
    unittest.main()
