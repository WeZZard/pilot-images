"""Offline selected-profile composition with fake executables and config output."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
HOST = REPO / 'host'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = load('image_environment', HOST / 'environment.py')


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.events = self.root / 'events.jsonl'
        self.bin = self.root / 'selected bin'
        self.bin.mkdir()
        self.vmctl = self.bin / 'vmctl'
        self.tart = self.bin / 'tart'
        self.vmctl.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
from pathlib import Path
if sys.argv[1:]==['environment','--json']:
 print(Path(os.environ['VM_ENVIRONMENT_FILE']+'.response').read_text())
else:
 with open(os.environ['TEST_EVENTS'],'a') as f:
  f.write(json.dumps(dict(binary=sys.argv[0],args=sys.argv[1:],store=os.environ.get('TART_HOME'),state=os.environ.get('PILOT_IMAGES_STATE_DIR')))+'\\n')
 if sys.argv[1]=='acquire':
  print(json.dumps(dict(vm='pilot-fixture',image_kind='linux')))
 elif sys.argv[1]=='pull':
  target=Path(sys.argv[-1])
  value=dict(status='pass')
  if target.name=='inventory.json':
   value=dict(schemaVersion=1,os='linux',architecture='arm64',collectedAt='2026-09-16T00:00:00Z',sources=[dict(id='fixture',status='unavailable')],applications=[])
  else:
   import importlib.util,hashlib
   from unittest.mock import patch
   repo=Path(os.environ['PILOT_REPO'])
   spec=importlib.util.spec_from_file_location('fixture_checks',repo/'applications/check.py')
   checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
   raw=target.parent/'inventory.json';selection=checks.load(repo/'images/ubuntu2404/application-tests.json')
   def passed(argv,timeout,startup=False,temporary_root=None):
    directory='/fixture/home/snap/firefox/common/pilot-app-fixture'
    result=dict(status='pass',argv=[a.replace('{temporary}',directory) for a in argv])
    if temporary_root is not None: result.update(temporaryRoot=temporary_root,temporaryDirectory=directory)
    return result
   with patch.object(checks.shutil,'which',return_value='/fixture'):
    value=checks.run(repo/'applications',selection,json.loads(raw.read_text()),target.parent.name,passed)
   value['inventorySha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
  target.write_text(json.dumps(value))
''')
        self.tart.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
with open(os.environ['TEST_EVENTS'],'a') as f:
 f.write(json.dumps(dict(binary=sys.argv[0],args=sys.argv[1:],store=os.environ.get('TART_HOME')))+'\\n')
if sys.argv[1]=='list':
 print('local pilot-ubuntu-base stopped')
 print('local pilot-ubuntu2404-work stopped')
 print('local pilot-existing stopped')
elif sys.argv[1]=='ip': print('192.0.2.1')
''')
        self.vmctl.chmod(0o755)
        self.tart.chmod(0o755)
        trap = self.root / 'hostile-bin'
        trap.mkdir()
        for name in ('tart', 'vmctl'):
            path = trap / name
            path.write_text('#!/bin/sh\nexit 99\n')
            path.chmod(0o755)
        self.profile = dict(schemaVersion=1, id='fixture', vmServiceUrl='http://127.0.0.1:9876',
            imageRepository=str(REPO), tartHome=str(self.root / "store 'quoted' $(false)"),
            serviceStateDir=str(self.root / 'service'), imageStateDir=str(self.root / 'images-state'),
            relayStateDir=str(self.root / 'relay'), vmctlPath=str(self.vmctl), tartPath=str(self.tart))
        self.selector = self.root / 'profile.json'
        self.save()
        self.env = dict(os.environ, VM_ENVIRONMENT_FILE=str(self.selector),
            TEST_EVENTS=str(self.events), PATH=str(trap) + os.pathsep + os.environ['PATH'],
            PYTHONDONTWRITEBYTECODE='1')
        for key in bootstrap.EXPORTS:
            self.env[key] = str(self.root / 'hostile' / key)
        self.env.update(VM_SERVICE_HOST='wrong', VM_SERVICE_PORT='1')

    def response(self):
        p = self.profile
        identity = {key: p[key] for key in bootstrap.IDENTITY_FIELDS}
        identity['fingerprint'] = hashlib.sha256(json.dumps(p, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        exported = {key: p[field] for key, field in bootstrap.EXPORTS.items()}
        exported.update(VM_ENVIRONMENT_FILE=str(self.selector), VM_ENVIRONMENT_FINGERPRINT=identity['fingerprint'], VM_SERVICE_HOST='127.0.0.1', VM_SERVICE_PORT='9876')
        return dict(profile=p, identity=identity, environment=exported)

    def save(self, response=None):
        self.selector.write_text(json.dumps(self.profile))
        Path(str(self.selector) + '.response').write_text(json.dumps(response or self.response()))

    def run_cli(self, script, *args, success=True):
        result = subprocess.run([sys.executable, str(HOST / script), *args], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def run_shell(self, command, *args, success=True):
        result = subprocess.run(['zsh', '-c', command, 'fixture', *map(str, args)], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def recorded(self):
        return [json.loads(row) for row in self.events.read_text().splitlines()]

    def test_resolution_is_read_only_and_overrides_every_legacy_export(self):
        before = dict(self.env)
        exports = bootstrap.resolve(self.env)
        self.assertEqual(exports, self.response()['environment'])
        self.assertEqual(self.env, before)
        for key in ('tartHome', 'serviceStateDir', 'imageStateDir', 'relayStateDir'):
            self.assertFalse(Path(self.profile[key]).exists())
        self.assertFalse(self.events.exists())
        self.assertEqual(json.loads(self.run_cli('environment.py').stdout), exports)

    def test_explicit_blank_selection_refuses_instead_of_using_legacy_store(self):
        with self.assertRaises(ValueError):
            bootstrap.resolve({'VM_ENVIRONMENT_FILE': ''})
        self.env['VM_ENVIRONMENT_FILE'] = ''
        self.run_shell('source "$1"; tart list', HOST / 'lib/common.zsh', success=False)
        self.assertFalse(self.events.exists())

    def test_no_profile_is_noop_and_import_does_not_resolve(self):
        self.assertEqual(bootstrap.resolve({'TART_HOME': '/legacy'}), {})
        with patch.dict(os.environ, self.env), patch('subprocess.run', side_effect=AssertionError('import executed a subprocess')):
            load('import_environment', HOST / 'environment.py')
            inventory = load('inventory', HOST / 'inventory.py')
            with patch.dict(sys.modules, inventory=inventory):
                for script in ('check-clone.py', 'maintenance-lock.py', 'application-acceptance.py', 'capture-package.py'):
                    load(script[:-3], HOST / script)
        self.assertFalse(self.events.exists())

    def test_inconsistent_response_is_rejected_before_exports_or_mutation(self):
        for mutate in (
            lambda d: d['environment'].update(PATH='/evil'),
            lambda d: d['environment'].update(TART='/legacy/tart'),
            lambda d: d['identity'].update(imageRepository='/wrong'),
            lambda d: d['identity'].update(fingerprint='0' * 64),
            lambda d: d['environment'].pop('PILOT_IMAGES_STATE_DIR'),
            lambda d: d['environment'].update(VM_ENVIRONMENT_FILE='/different'),
        ):
            response = copy.deepcopy(self.response())
            mutate(response)
            self.save(response)
            result = self.run_cli('environment.py', '--shell', success=False)
            self.assertEqual(result.stdout, '')
        self.assertFalse(self.events.exists())

    def test_wrong_checkout_and_invalid_backend_never_fall_back(self):
        self.profile['imageRepository'] = str(self.root)
        self.save()
        for script, args in (
            ('inventory.py', ['state-path']), ('maintenance-lock.py', ['acquire', 'fixture', 'true']),
            ('check-clone.py', ['ubuntu2404']), ('application-acceptance.py', ['--help']),
            ('capture-package.py', ['--help']),
        ):
            result = self.run_cli(script, *args, success=False)
            self.assertIn('invoke that checkout', result.stderr)
        self.run_shell('source "$1"; tart clone a b', HOST / 'lib/common.zsh', success=False)
        self.assertFalse(self.events.exists())
        self.profile['vmctlPath'] = 'vmctl'
        self.save()
        self.run_cli('environment.py', success=False)
        self.profile['vmctlPath'] = str(self.root / 'hostile-bin/vmctl')
        self.save()
        self.run_cli('environment.py', success=False)
        self.assertFalse(Path(self.profile['tartHome']).exists())

    def test_shell_wrapper_quoting_and_nohup_use_selected_binary_and_store(self):
        self.run_shell('source "$1"; tart list; tart_background run fixture; wait', HOST / 'lib/common.zsh')
        rows = self.recorded()
        self.assertEqual({row['args'][0] for row in rows}, {'list', 'run'})
        self.assertTrue(all(row['binary'] == str(self.tart) and row['store'] == self.profile['tartHome'] for row in rows))

    def test_selected_shell_configuration_cannot_drift_after_composition(self):
        self.run_shell('source "$1"; TART_HOME=/wrong; tart list', HOST / 'lib/common.zsh', success=False)
        self.assertFalse(self.events.exists())

    def test_real_shell_entrypoints_use_selected_tart(self):
        self.run_shell('zsh "$1" fixture ubuntu2404', HOST / 'new-clone.zsh')
        self.run_shell('zsh "$1" pilot-existing --line ubuntu2404', HOST / 'run-clone.zsh')
        self.assertTrue((Path(self.profile['imageStateDir']) / 'logs/tart-run-pilot-existing.log').is_file())
        rows = self.recorded()
        self.assertTrue({'clone', 'set', 'run', 'list', 'ip'} <= {row['args'][0] for row in rows})
        self.assertTrue(all(row['binary'] == str(self.tart) and row['store'] == self.profile['tartHome'] for row in rows))

    def test_standalone_clone_uses_selected_vmctl_for_full_lifecycle(self):
        self.run_cli('check-clone.py', 'ubuntu2404')
        rows = self.recorded()
        self.assertEqual({row['args'][0] for row in rows}, {'acquire', 'exec', 'push', 'pull', 'release'})
        self.assertTrue(all(row['binary'] == str(self.vmctl) and row['store'] == self.profile['tartHome']
                            and row['state'] == self.profile['imageStateDir'] for row in rows))
        self.assertEqual(rows[-1]['args'], ['release', 'pilot-fixture'])
        pushes = [row['args'][2] for row in rows if row['args'][0] == 'push']
        self.assertTrue(all(path.startswith(str(REPO) + '/') for path in pushes))
        self.assertTrue(list(Path(self.profile['imageStateDir']).glob('stores/*/extracted/accept-*')))
        self.assertFalse((self.root / 'hostile').exists())

    def test_work_clone_checks_selected_tart_and_uses_selected_lock(self):
        # No association exists, so this stops after lock and stopped-state checks.
        self.run_cli('check-clone.py', 'ubuntu2404', '--source', 'work', success=False)
        rows = self.recorded()
        self.assertEqual(rows[0]['binary'], str(self.tart))
        self.assertEqual(rows[0]['store'], self.profile['tartHome'])
        self.assertTrue((Path(self.profile['tartHome']) / 'maintenance-locks/ubuntu2404.lock').is_file())
        self.assertFalse((self.root / 'hostile').exists())

    def test_distinct_profiles_select_distinct_read_only_catalog_and_lock_state(self):
        outputs = []
        for suffix in ('one', 'two'):
            self.profile.update(id=suffix, tartHome=str(self.root / suffix / 'tart'),
                imageStateDir=str(self.root / suffix / 'images'))
            self.save()
            outputs.append(self.run_cli('inventory.py', 'state-path').stdout.strip())
            expected = Path(self.profile['imageStateDir']) / 'stores' / hashlib.sha256(
                str(Path(self.profile['tartHome']) / 'vms').encode()).hexdigest()
            self.assertEqual(outputs[-1], str(expected))
            self.assertFalse(expected.exists())
            self.run_cli('maintenance-lock.py', 'acquire', 'fixture', sys.executable, '-c', 'pass')
            self.assertTrue((Path(self.profile['tartHome']) / 'maintenance-locks/fixture.lock').is_file())
        self.assertNotEqual(*outputs)
        self.run_cli('inventory.py', 'state-path', '--root', str(self.root / 'hostile'), success=False)
        self.assertFalse((self.root / 'hostile').exists())


if __name__ == '__main__':
    unittest.main()
