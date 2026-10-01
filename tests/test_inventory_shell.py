"""Execute real lifecycle scripts/library/writer in a disposable fake Tart tree.
Only common.zsh's external boundary is replaced. No guest/collector is executed.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]

COMMON = r'''
log() { print -r -- "$*"; }
warn() { print -r -- "WARN $*"; }
die() { print -r -- "$*" >&2; exit 1; }
require() { :; }
event() {
  print -r -- "$*" >> "$REPO_ROOT/events"
  if [[ -n "${HOLD_EVENT:-}" && "$*" == "$HOLD_EVENT" ]]; then
    print ready > "$REPO_ROOT/ready"
    python3 -c 'import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); end=time.monotonic()+20
while not p.exists():
 if time.monotonic()>end: sys.exit(90)
 time.sleep(.01)' "$REPO_ROOT/resume"
  fi
}
vm_exists() { [[ -d "$TART_HOME/vms/$1" ]]; }
vm_start_headless() {
  [[ ! -e "$BASE_INVENTORY" || "$1" == work ]] || die 'stale base at boot'
  [[ ! -e "$WORK_INVENTORY" || "$1" == base ]] || die 'stale work at boot'
  event "start $1"
  print running > "$REPO_ROOT/state"
}
wait_ip() { print fixture; }
wait_ssh() { :; }
sleep() { :; }
vscp() { event copy; }
vscp_retry() { vscp "$@"; }
vssh_retry() { vssh "$@"; }
vssh() {
  local cmd=$2
  event "ssh $cmd"
  case "$cmd" in
    *'ls /tmp/payload/guest | grep'*) print -l 00 10 20 30 40 45 50 ;;
    *'ls /tmp/payload/guest/00-'*) print /tmp/payload/guest/00-system.sh ;;
    *'ls /tmp/payload/guest/40-'*) print /tmp/payload/guest/40-automation.sh ;;
    *'ls /tmp/payload/guest/45-'*) print /tmp/payload/guest/45-capture.sh ;;
    *'ls /tmp/payload/guest/50-'*) print /tmp/payload/guest/50-agents.sh ;;
    *'ls /tmp/payload/guest/65-'*) print /tmp/payload/guest/65-automation.sh ;;
    *'ls /tmp/payload/checks/acceptance.'*) print /tmp/payload/checks/acceptance.sh ;;
    *'ls /tmp/payload/checks/no-secrets.'*) print /tmp/payload/checks/no-secrets.sh ;;
    *'bash /tmp/payload/guest/00-system.sh'*) [[ "${FAIL:-}" != phase ]] ;;
    *'for s in "$d"/'*) [[ "${FAIL:-}" != update ]] ;;
    *'70-no-self-update.zsh'*) [[ "${FAIL:-}" != freeze ]] ;;
    *'acceptance.'*) [[ "${FAIL:-}" != acceptance ]] ;;
    *'no-secrets.'*) [[ "${FAIL:-}" != secrets ]] ;;
    *'collect.py --aliases'*) [[ "${FAIL:-}" != extract ]] ;;
    'cat /tmp/payload/inventory/installed.json') print -r -- "$FIXTURE_JSON" ;;
    *'python3 /tmp/payload/applications/check.py '*) [[ "${FAIL:-}" != apps ]] ;;
    'cat /tmp/payload/application-report.json') python3 "$REPO_ROOT/make-report.py" "$RAW_INVENTORY" ;;
  esac
}
tart() {
  event "tart $*"
  case "$1" in
    list) local listing='local fixture-seed@sha256:0000000000000000000000000000000000000000000000000000000000000000 stopped'
      if [[ -n "${NO_OCI_SEED:-}" ]]; then listing='local unrelated stopped'; fi
      for vm in work base seed; do
        if vm_exists "$vm"; then listing+=$'\n'"local $vm $(<"$REPO_ROOT/state")"; fi
      done
      print -r -- "$listing" ;;
    stop) [[ "${FAIL:-}" != stop ]] || return 1; print stopped > "$REPO_ROOT/state" ;;
    rename) mv "$TART_HOME/vms/$2" "$TART_HOME/vms/$3"
      if [[ "${FAIL:-}" == rename-mutation ]]; then print changed >> "$TART_HOME/vms/$3/disk.img"; fi ;;
    *) die "unmocked Tart operation: $*" ;;
  esac
}
'''


@unittest.skipUnless(shutil.which('zsh'), 'zsh required')
class ShellLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        shutil.copytree(REPO / 'host', self.root / 'host')
        (self.root / 'host/lib/common.zsh').write_text(COMMON)
        shutil.copytree(REPO / 'inventory', self.root / 'inventory')
        (self.root / 'applications/fixture').mkdir(parents=True)
        shutil.copy(REPO / 'applications/check.py', self.root / 'applications/check.py')
        config = dict(architectures=['arm64'], optional=False, executable='/fixture/tool', version=['--version'], launch=dict(args=['--help'], mode='command'), timeoutSeconds=10, extensions=[])
        (self.root / 'applications/fixture/manifest.json').write_text(json.dumps(dict(schemaVersion=1, id='fixture', inventoryIds=[], platforms=dict(macos=config, linux=config))))
        (self.root / 'make-report.py').write_text('''import sys,json,hashlib,importlib.util
from pathlib import Path
r=Path(__file__).parent
s=importlib.util.spec_from_file_location('checks',r/'applications/check.py')
c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
raw=Path(sys.argv[1])
observed=json.loads(raw.read_text())
print(json.dumps(dict(schemaVersion=1,image='fixture',os=observed['os'],architecture=observed['architecture'],dependencies={},status='pass',unclassified=[],buildId=raw.parent.name,inventorySha256=hashlib.sha256(raw.read_bytes()).hexdigest(),planSha256=c.plan_digest(r/'applications',json.loads((r/'images/fixture/application-tests.json').read_text())),applications=[dict(id='fixture',inventoryIds=[],status='pass',baseline=[dict(check='availability',status='pass',executable='/fixture/tool'),dict(check='version',status='pass',argv=['/fixture/tool','--version']),dict(check='launch',status='pass',argv=['/fixture/tool','--help'])],extensions=[])])))
''')
        line = self.root / 'images/fixture'
        (line / 'guest').mkdir(parents=True)
        (line / 'checks').mkdir()
        for name in ('acceptance', 'no-secrets'):
            (line / 'checks' / (name + '.sh')).write_text('#!/bin/bash\nexit 0\n')
        (line / 'application-tests.json').write_text(json.dumps(dict(schemaVersion=1, image='fixture', plans=['fixture'], dependencies={})))
        (line / 'line.conf').write_text('LINE_KIND=macos\nGUEST_SHELL=bash\nWORK_VM=work\nBASE_VM=base\nSEED_LOCAL=seed\nSEED_OCI=fixture-seed\nGUEST_USER=fixture\nGUEST_PASS=fixture\nXCODE_VERSION=1\nNODE_MAJOR=1\nPYTHON_VERSION=1\nNVM_VERSION=1\nXCODE_XIP=/nonexistent-fixture\n')
        (line / 'seed.lock').write_text('SEED_OCI=fixture-seed\nSEED_DIGEST=sha256:' + '0' * 64 + '\n')
        self.vms = self.root / 'tart/vms'
        for vm in ('work', 'seed'):
            (self.vms / vm).mkdir(parents=True)
            for name in ('disk.img', 'config.json', 'nvram.bin'):
                (self.vms / vm / name).write_bytes(b'fixture')
        (self.root / 'state').write_text('stopped\n')
        self.data = dict(schemaVersion=1, os='macos', architecture='arm64',
                         collectedAt='2026-09-01T00:00:00Z',
                         sources=[dict(id='bundles', status='available', roots=['/Applications'])],
                         applications=[])
        self.env = dict(os.environ, TART_HOME=str(self.root / 'tart'),
                        FIXTURE_JSON=json.dumps(self.data), HOME=str(self.root))
        self.env['PILOT_IMAGES_STATE_DIR'] = str(self.root / 'state-dir')
        # A stand-in bundle: macOS builds pack the host's CuaDriver.app.
        cua = self.root / 'host-apps' / 'CuaDriver.app'
        cua.mkdir(parents=True)
        self.env['CUA_DRIVER_APP'] = str(cua)
        self.store = self.root / 'state-dir/stores' / hashlib.sha256(str(self.vms).encode()).hexdigest()
        self.work = self.store / 'work/fixture.json'
        self.base = self.store / 'base/fixture.json'
        self.fresh_receipt = self.store / 'acceptance/fresh-work/fixture.json'
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'tart').write_text('#!/bin/zsh\nprint "local work $(<\"$HOME/state\")"\n')
        (bin_dir / 'vmctl').write_text('''#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
root=Path(os.environ['HOME'])
sys.path.insert(0,str(root/'host'))
import inventory
args=sys.argv[1:]
with (root/'vmctl-events').open('a') as f: f.write(json.dumps(args)+'\\n')
fail=os.environ.get('CLONE_FAIL','')
if args[0]=='acquire':
 state=inventory.state_directory(root/'tart/vms')
 pair=inventory.read_json(state/'work/fixture.json')
 expected=inventory.read_json(args[args.index('--expected-source-fingerprint')+1])
 assert expected==pair['base']
 lease=dict(vm='owned-clone',image_kind='macos',source='work',source_vm='work',source_fingerprint=pair['base'])
 if fail=='source': lease['source']='base'
 print(json.dumps(lease))
elif args[0]=='pull':
 target=Path(args[-1])
 if target.name=='inventory.json':
  value=json.loads(os.environ['FIXTURE_JSON']);value['collectedAt']='2026-09-16T01:02:03Z'
  if fail=='inventory': value['architecture']='x86_64'
  target.write_text(json.dumps(value))
 else:
  value=json.loads(subprocess.check_output([sys.executable,str(root/'make-report.py'),str(target.parent/'inventory.json')]))
  if fail=='report': value['status']='fail'
  target.write_text(json.dumps(value))
elif args[0]=='release':
 if fail=='mutation': (root/'tart/vms/work/disk.img').write_bytes(b'changed')
 if fail=='plan': (root/'applications/fixture/PLAN.md').write_text('changed')
 if fail=='running': (root/'state').write_text('running')
 if fail=='cleanup': sys.exit(1)
elif args[0] not in ('exec','push'): raise RuntimeError(args)
''')
        for executable in bin_dir.iterdir():
            executable.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']

    def certify(self, fail='', success=True):
        result = subprocess.run(['python3', str(self.root / 'host/check-clone.py'), 'fixture', '--source', 'work'],
            env=dict(self.env, CLONE_FAIL=fail), text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def run_script(self, script, *args, fail='', success=True):
        # Failed maintenance deliberately leaves a running VM; operator recovery
        # is required before another attempt (never silently reuse it).
        (self.root / 'state').write_text('stopped\n')
        result = subprocess.run(['zsh', str(self.root / 'host' / script), 'fixture', *args],
                                env=dict(self.env, FAIL=fail), text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return (self.root / 'events').read_text()

    def stale(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('stale')

    def test_overlapping_entrypoints_fail_before_any_mutation(self):
        scripts = ('build-base.zsh', 'refresh-base.zsh',
                   'promote-base.zsh', 'extract-work-inventory.zsh')
        for holder in scripts:
            with self.subTest(holder=holder):
                # Give every holder its own disposable fixture tree.
                fixture = ShellLifecycleTests()
                fixture.setUp()
                try:
                    if holder == 'refresh-base.zsh':
                        (fixture.vms / 'work').rename(fixture.vms / 'base')
                    if holder == 'promote-base.zsh':
                        fixture.run_script('extract-work-inventory.zsh')
                        fixture.certify()
                    if holder == 'build-base.zsh':
                        line = fixture.root / 'images/fixture/line.conf'
                        line.write_text(line.read_text().replace('LINE_KIND=macos', 'LINE_KIND=linux'))
                        fixture.data['os'] = 'linux'
                        fixture.env['FIXTURE_JSON'] = json.dumps(fixture.data)
                    args = ['--phase', '00'] if holder == 'build-base.zsh' else []
                    hold = ('tart rename work base' if holder == 'promote-base.zsh'
                            else 'start base' if holder == 'refresh-base.zsh' else 'start work')
                    proc = subprocess.Popen(['zsh', str(fixture.root / 'host' / holder), 'fixture', *args],
                                            env=dict(fixture.env, HOLD_EVENT=hold),
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    try:
                        deadline = time.monotonic() + 10
                        while not (fixture.root / 'ready').exists():
                            if proc.poll() is not None:
                                _, err = proc.communicate()
                                self.fail(f'holder exited before barrier: {err!r}')
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(.01)
                        before = (fixture.root / 'events').read_bytes()
                        # Sentinel associations must survive every rejected contender.
                        saved = {}
                        for path in (fixture.work, fixture.base):
                            saved[path] = path.read_bytes() if path.exists() else None
                            fixture.stale(path)
                        for contender in scripts:
                            result = subprocess.run(['zsh', str(fixture.root / 'host' / contender),
                                                     'fixture', *(['--phase', '00'] if contender == 'build-base.zsh' else [])],
                                                    env=fixture.env, capture_output=True, timeout=5)
                            self.assertEqual(result.returncode, 75, result.stderr)
                            self.assertEqual((fixture.root / 'events').read_bytes(), before)
                            for path in saved:
                                self.assertEqual(path.read_text(), 'stale')
                        for path, content in saved.items():
                            if content is None:
                                path.unlink()
                            else:
                                path.write_bytes(content)
                        (fixture.root / 'resume').touch()
                        _, err = proc.communicate(timeout=10)
                        self.assertEqual(proc.returncode, 0, err)
                        # The persistent inode remains, but the OS lock is released.
                        result = subprocess.run(['python3', str(fixture.root / 'host/maintenance-lock.py'),
                                                 'acquire', 'fixture', 'true'], env=fixture.env)
                        self.assertEqual(result.returncode, 0)
                    finally:
                        if proc.poll() is None:
                            (fixture.root / 'resume').touch()
                            proc.communicate(timeout=25)
                finally:
                    fixture.doCleanups()

    def test_signal_does_not_unlock_surviving_child(self):
        child = self.root / 'child.py'
        child.write_text('import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\np.with_suffix(".ready").touch()\nwhile not p.exists(): time.sleep(.01)\n')
        shell = self.root / 'holder.zsh'
        shell.write_text('python3 "$1" "$2" &\nwait\n')
        release = self.root / 'child-release'
        command = ['python3', str(self.root / 'host/maintenance-lock.py'), 'acquire', 'fixture']
        proc = subprocess.Popen([*command, 'zsh', str(shell), str(child), str(release)], env=self.env)
        try:
            deadline = time.monotonic() + 5
            while not release.with_suffix('.ready').exists():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            proc.kill()  # strongest case: no exit trap can run
            proc.wait(timeout=5)
            busy = subprocess.run([*command, 'true'], env=self.env, capture_output=True)
            self.assertEqual(busy.returncode, 75)
        finally:
            release.touch()
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while True:
            result = subprocess.run([*command, 'true'], env=self.env, capture_output=True)
            if result.returncode == 0:
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)

    def test_extraction_only_then_real_promotion(self):
        self.stale(self.work)
        events = self.run_script('extract-work-inventory.zsh')
        self.assertIn('acceptance.sh', events)
        self.assertIn('no-secrets.sh', events)
        self.assertNotIn('/tmp/payload/guest/', events)
        self.assertLess(events.index('collect.py --aliases'), events.index('tart stop work'))
        self.assertEqual(json.loads((self.store / 'pending/fixture.json').read_text())['inventory'], self.data)
        self.certify()
        original = json.loads(self.fresh_receipt.read_text())
        report_bytes = Path(original['report']).read_bytes()
        raw_bytes = Path(original['raw']).read_bytes()
        self.run_script('promote-base.zsh')
        self.assertEqual(Path(original['report']).read_bytes(), report_bytes)
        self.assertEqual(Path(original['raw']).read_bytes(), raw_bytes)
        self.assertFalse(self.fresh_receipt.exists())
        base_receipt = json.loads((self.store / 'acceptance/base/fixture.json').read_text())
        self.assertEqual(base_receipt['reportSha256'], original['reportSha256'])
        self.assertEqual(base_receipt['rawSha256'], original['rawSha256'])
        self.assertFalse(self.work.exists())
        self.assertEqual(json.loads(self.base.read_text())['base']['base_vm'], 'base')

    def test_fresh_clone_failures_release_owned_clone_without_receipt(self):
        for failure in ('source', 'inventory', 'report', 'cleanup', 'mutation', 'plan', 'running'):
            with self.subTest(failure=failure):
                fixture = ShellLifecycleTests()
                fixture.setUp()
                try:
                    fixture.run_script('extract-work-inventory.zsh')
                    fixture.certify(fail=failure, success=False)
                    self.assertFalse(fixture.fresh_receipt.exists())
                    calls = [json.loads(line) for line in (fixture.root / 'vmctl-events').read_text().splitlines()]
                    self.assertEqual(calls[-1], ['release', 'owned-clone'])
                    self.assertIn('--expected-source-fingerprint', calls[0])
                finally:
                    fixture.doCleanups()

    def test_promotion_requires_fresh_receipt_and_preserves_failed_evidence(self):
        self.run_script('extract-work-inventory.zsh')
        self.stale(self.base)
        events = self.run_script('promote-base.zsh', success=False)
        self.assertNotIn('tart rename', events)
        self.assertEqual(self.base.read_text(), 'stale')
        self.certify()
        original = self.fresh_receipt.read_bytes()
        for key, value in (('schemaVersion', False), ('source', 'base'), ('association', {}), ('planSha256', '0' * 64), ('buildId', 'wrong')):
            receipt = json.loads(original)
            receipt[key] = value
            self.fresh_receipt.write_text(json.dumps(receipt))
            events = self.run_script('promote-base.zsh', success=False)
            self.assertNotIn('tart rename', events)
            self.assertEqual(self.base.read_text(), 'stale')
        self.fresh_receipt.write_bytes(original)
        receipt = json.loads(original)
        for key in ('raw', 'report', 'lease'):
            path = Path(receipt[key])
            content = path.read_bytes()
            path.write_bytes(content + b' ')
            events = self.run_script('promote-base.zsh', success=False)
            self.assertNotIn('tart rename', events)
            path.write_bytes(content)

    def test_fresh_receipt_revalidates_report_and_lease_not_only_hashes(self):
        self.run_script('extract-work-inventory.zsh')
        self.certify()
        original = json.loads(self.fresh_receipt.read_text())
        for name, field, value in (('report', 'status', False), ('report', 'inventorySha256', '0' * 64),
                ('report', 'buildId', 'work-build'), ('lease', 'source', 'base'),
                ('lease', 'source_fingerprint', {})):
            path = Path(original[name])
            before = path.read_bytes()
            document = json.loads(before)
            document[field] = value
            path.write_text(json.dumps(document))
            receipt = dict(original)
            receipt[name + 'Sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.fresh_receipt.write_text(json.dumps(receipt))
            events = self.run_script('promote-base.zsh', success=False)
            self.assertNotIn('tart rename', events)
            path.write_bytes(before)
        self.fresh_receipt.write_text(json.dumps(original))
        (self.root / 'applications/fixture/PLAN.md').write_text('Plan changed after certification.')
        events = self.run_script('promote-base.zsh', success=False)
        self.assertNotIn('tart rename', events)

    def test_inventory_replacement_invalidates_fresh_receipt(self):
        self.run_script('extract-work-inventory.zsh')
        self.certify()
        receipt = json.loads(self.fresh_receipt.read_text())
        report_bytes = Path(receipt['report']).read_bytes()
        self.run_script('extract-work-inventory.zsh')
        self.assertFalse(self.fresh_receipt.exists())
        self.assertEqual(Path(receipt['report']).read_bytes(), report_bytes)

    def test_check_clone_contends_on_existing_maintenance_lock(self):
        result = subprocess.run(['python3', str(self.root / 'host/maintenance-lock.py'), 'acquire', 'fixture',
            'python3', '-c', 'import os,subprocess,sys; e=dict(os.environ);e.pop("PILOT_MAINTENANCE_FD");sys.exit(subprocess.call(sys.argv[1:],env=e))',
            'python3', str(self.root / 'host/check-clone.py'), 'fixture', '--source', 'work'], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 75)
        self.assertFalse((self.root / 'vmctl-events').exists())

    def test_promotion_refuses_missing_acceptance_before_rename(self):
        self.run_script('extract-work-inventory.zsh')
        (self.store / 'acceptance/work/fixture.json').unlink()
        events = self.run_script('promote-base.zsh', success=False)
        self.assertNotIn('tart rename', events)
        self.assertFalse(self.base.exists())

    def test_promotion_refuses_changed_plan_before_rename(self):
        self.run_script('extract-work-inventory.zsh')
        (self.root / 'applications/fixture/PLAN.md').write_text('Changed acceptance plan.\n')
        events = self.run_script('promote-base.zsh', success=False)
        self.assertNotIn('tart rename', events)

    def test_promotion_refuses_changed_work_before_rename(self):
        self.run_script('extract-work-inventory.zsh')
        (self.vms / 'work/disk.img').write_bytes(b'changed')
        self.stale(self.base)
        events = self.run_script('promote-base.zsh', success=False)
        self.assertNotIn('tart rename', events)
        self.assertEqual(self.base.read_text(), 'stale')

    def test_promotion_mutation_after_rename_leaves_no_publication(self):
        self.run_script('extract-work-inventory.zsh')
        self.certify()
        self.run_script('promote-base.zsh', fail='rename-mutation', success=False)
        self.assertFalse(self.base.exists())
        self.assertTrue((self.vms / 'base').exists())

    def test_extraction_and_stop_failures_invalidate_work(self):
        for fail in ('acceptance', 'secrets', 'extract', 'apps', 'stop'):
            self.stale(self.work)
            self.run_script('extract-work-inventory.zsh', fail=fail, success=False)
            self.assertFalse(self.work.exists())

    def test_refresh_failure_invalidation_and_success_publication(self):
        (self.vms / 'work').rename(self.vms / 'base')
        for fail in ('update', 'freeze', 'acceptance', 'secrets', 'extract', 'apps', 'stop'):
            self.stale(self.base)
            self.run_script('refresh-base.zsh', fail=fail, success=False)
            self.assertFalse(self.base.exists())
        events = self.run_script('refresh-base.zsh')
        self.assertTrue(self.base.exists())
        self.assertLess(events.rindex('collect.py --aliases'), events.rindex('tart stop base'))

    def test_resume_runs_remaining_phases_without_recloning(self):
        events = self.run_script('build-base.zsh', '--from-phase', '40')
        for phase in ('40-automation.sh', '45-capture.sh', '50-agents.sh'):
            self.assertIn('bash /tmp/payload/guest/' + phase, events)
        self.assertNotIn('bash /tmp/payload/guest/00-system.sh', events)
        self.assertNotIn('tart clone', events)
        self.assertTrue(self.work.exists())

    def test_phase_reruns_do_not_need_the_oci_seed_entry(self):
        # The OCI cache can be purged while the pristine local seed remains; a
        # phase re-run never touches either, a fresh build still needs the OCI.
        self.env['NO_OCI_SEED'] = '1'
        events = self.run_script('build-base.zsh', '--phase', '00')
        self.assertIn('bash /tmp/payload/guest/00-system.sh', events)
        self.assertNotIn('tart clone', events)
        (self.root / 'events').write_text('')
        shutil.rmtree(self.vms / 'work')
        events = self.run_script('build-base.zsh', success=False)
        self.assertNotIn('start', events)
        self.assertNotIn('tart clone', events)

    def test_tcc_grant_phases_reboot_before_checks(self):
        # Phases 60 and 65 write TCC rows; the checks must run after a fresh
        # login, as a clone would see them, so a single-phase run reboots first.
        events = self.run_script('build-base.zsh', '--phase', '65')
        self.assertIn('bash /tmp/payload/guest/65-automation.sh', events)
        self.assertLess(events.index('bash /tmp/payload/guest/65-automation.sh'), events.index('ssh sudo reboot'))
        self.assertLess(events.index('ssh sudo reboot'), events.index('acceptance.'))
        (self.root / 'events').write_text('')
        events = self.run_script('build-base.zsh', '--phase', '50')
        self.assertIn('bash /tmp/payload/guest/50-agents.sh', events)
        self.assertNotIn('ssh sudo reboot', events)

    def test_build_rejects_bad_seed_lock_before_mutating_work(self):
        lock = self.root / 'images/fixture/seed.lock'
        for value in ('SEED_OCI=wrong\nSEED_DIGEST=sha256:' + '0' * 64 + '\n', 'SEED_OCI=fixture-seed\nSEED_DIGEST=unlocked\n'):
            lock.write_text(value)
            (self.root / 'events').write_text('')
            events = self.run_script('build-base.zsh', '--phase', '00', success=False)
            self.assertEqual(events, '')

    def test_build_phase_failure_invalidates_before_boot(self):
        # Linux avoids all host app/Xcode discovery in the production build script.
        line = self.root / 'images/fixture/line.conf'
        line.write_text(line.read_text().replace('LINE_KIND=macos', 'LINE_KIND=linux'))
        self.data['os'] = 'linux'
        self.env['FIXTURE_JSON'] = json.dumps(self.data)
        self.stale(self.work)
        events = self.run_script('build-base.zsh', '--phase', '00', fail='phase', success=False)
        self.assertFalse(self.work.exists())
        self.assertNotIn('collect.py --aliases', events)
        for fail in ('acceptance', 'secrets'):
            self.stale(self.work)
            self.run_script('build-base.zsh', '--phase', '00', fail=fail, success=False)
            self.assertFalse(self.work.exists())
        self.run_script('build-base.zsh', '--phase', '00')
        self.assertTrue(self.work.exists())


if __name__ == '__main__':
    unittest.main()
