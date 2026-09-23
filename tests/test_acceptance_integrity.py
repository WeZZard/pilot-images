"""Host-only regression boundaries: no real guest, Tart, or vm-service calls."""
import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_inventory_shell as shell


class AcceptanceIntegrityTests(unittest.TestCase):
    setUp = shell.ShellLifecycleTests.setUp
    run_script = shell.ShellLifecycleTests.run_script
    certify = shell.ShellLifecycleTests.certify

    def test_missing_image_checks_cannot_extract(self):
        for name in ('acceptance', 'no-secrets'):
            path = self.root / 'images/fixture/checks' / (name + '.sh')
            content = path.read_bytes()
            path.unlink()
            self.run_script('extract-work-inventory.zsh', success=False)
            self.assertFalse(self.work.exists())
            path.write_bytes(content)

    def test_failed_checks_retain_exit_and_log_without_receipt(self):
        for failure, name in (('acceptance', 'acceptance'), ('secrets', 'no-secrets')):
            self.run_script('extract-work-inventory.zsh', fail=failure, success=False)
            results = list((self.store / 'extracted').glob('*/' + name + '.result.json'))
            self.assertTrue(results)
            failed = [json.loads(path.read_text()) for path in results]
            self.assertTrue(any(value['returncode'] != 0 and Path(value['log']).is_file() for value in failed))
            self.assertFalse(self.work.exists())

    def test_fresh_receipt_cannot_bypass_missing_or_tampered_image_evidence(self):
        self.run_script('extract-work-inventory.zsh')
        self.certify()
        receipt = json.loads((self.store / 'acceptance/work/fixture.json').read_text())
        for record in receipt['imageChecks']:
            result = json.loads(Path(record['result']).read_text())
            for path in map(Path, (record['result'], result['script'], result['retainedScript'], result['log'])):
                original = path.read_bytes()
                for mutation in ('missing', 'changed'):
                    with self.subTest(path=path, mutation=mutation):
                        if mutation == 'missing':
                            path.unlink()
                        else:
                            path.write_bytes(original + b'changed')
                        events = self.run_script('promote-base.zsh', success=False)
                        self.assertNotIn('tart rename', events)
                        self.assertTrue(self.fresh_receipt.exists())
                        path.write_bytes(original)
        # A new clone attempt must reject bad work evidence before acquisition.
        Path(receipt['imageChecks'][0]['result']).unlink()
        before = (self.root / 'vmctl-events').read_bytes()
        self.certify(success=False)
        self.assertEqual((self.root / 'vmctl-events').read_bytes(), before)
        self.assertFalse(self.fresh_receipt.exists())

    def test_check_result_from_another_attempt_cannot_be_rebound(self):
        self.run_script('extract-work-inventory.zsh')
        self.certify()
        path = self.store / 'acceptance/work/fixture.json'
        receipt = json.loads(path.read_text())
        record = receipt['imageChecks'][0]
        result_path = Path(record['result'])
        result = json.loads(result_path.read_text())
        result['buildId'] = 'another-attempt'
        result_path.write_text(json.dumps(result))
        record['sha256'] = hashlib.sha256(result_path.read_bytes()).hexdigest()
        path.write_text(json.dumps(receipt))
        events = self.run_script('promote-base.zsh', success=False)
        self.assertNotIn('tart rename', events)

    def test_required_image_checks_run_after_application_checks(self):
        events = self.run_script('extract-work-inventory.zsh')
        self.assertLess(events.index('applications/check.py'), events.index('/acceptance.sh'))
        self.assertLess(events.index('/acceptance.sh'), events.index('/no-secrets.sh'))

    def test_base_report_is_fully_validated_and_owned_lease_released(self):
        sys.path.insert(0, str(self.root / 'host'))
        self.addCleanup(sys.path.remove, str(self.root / 'host'))
        host_spec = importlib.util.spec_from_file_location('integrity_inventory', self.root / 'host/inventory.py')
        host_inventory = importlib.util.module_from_spec(host_spec)
        host_spec.loader.exec_module(host_inventory)
        modules = patch.dict(sys.modules, inventory=host_inventory)
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location('integrity_clone', self.root / 'host/check-clone.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for failure in ('none', 'malformed', 'buildId', 'inventorySha256', 'planSha256', 'image', 'plan-during-stage'):
            with self.subTest(failure=failure):
                evidence = self.root / ('base-attempt-' + failure)
                evidence.mkdir()
                calls = []
                plan_file = self.root / 'applications/fixture/PLAN.md'
                def invoke(argv, **kwargs):
                    args = argv[1:]
                    calls.append(args)
                    stdout = ''
                    if args[0] == 'acquire':
                        stdout = json.dumps(dict(vm='owned-base-clone', image_kind='macos'))
                    elif args[0] == 'push' and failure == 'plan-during-stage':
                        plan_file.write_text('changed during stage')
                    elif args[0] == 'pull':
                        target = Path(args[-1])
                        if target.name == 'inventory.json':
                            target.write_text(json.dumps(self.data))
                        else:
                            report = json.loads(subprocess.check_output(['python3', str(self.root / 'make-report.py'), str(evidence / 'inventory.json')]))
                            if failure == 'malformed':
                                report = dict(status='pass')
                            elif failure in ('buildId', 'inventorySha256', 'planSha256', 'image'):
                                report[failure] = 'wrong'
                            target.write_text(json.dumps(report))
                    return subprocess.CompletedProcess(argv, 0, stdout, '')
                try:
                    if failure == 'none':
                        module.check_clone('fixture', evidence, invoke)
                    else:
                        with self.assertRaises((ValueError, KeyError)):
                            module.check_clone('fixture', evidence, invoke)
                    self.assertEqual(calls[-1], ['release', 'owned-base-clone'])
                finally:
                    plan_file.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
