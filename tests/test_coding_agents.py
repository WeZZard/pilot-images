"""Phase 85 coding agents: the lock, its coverage of the `skills` agent list, and line parity.

Fixture-only: nothing here downloads, installs, or runs an agent.
"""
import importlib.util
import json
import pathlib
import re
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[1]
LINES = ('macos26', 'macos27')
GUEST_FILES = ('85-coding-agents.zsh', 'coding-agents.py', 'coding-agents.lock.json')
LOCK = json.loads((REPO / 'images/macos26/guest/coding-agents.lock.json').read_text())
SHA256 = re.compile(r'^[0-9a-f]{64}$')
METHOD_KEYS = {
    'npm': {'package', 'bin'},
    'npm-node': {'package', 'entry', 'bin', 'node'},
    'uv': {'package', 'spec', 'python', 'bin'},
    'archive': {'format', 'url', 'sha256', 'links', 'bin'},
    'script': {'url', 'sha256', 'args', 'bin'},
    'app': {'format', 'url', 'sha256', 'app', 'bundleId', 'bundleVersion', 'links'},
}


def load_helper():
    spec = importlib.util.spec_from_file_location('coding_agents', REPO / 'images/macos26/guest/coding-agents.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LockSchemaTests(unittest.TestCase):
    def test_every_entry_is_pinned_for_its_method(self):
        ids = [a['id'] for a in LOCK['agents']]
        self.assertEqual(len(ids), len(set(ids)))
        for agent in LOCK['agents']:
            with self.subTest(agent=agent['id']):
                self.assertIn(agent['method'], METHOD_KEYS)
                for key in ('id', 'name', 'version', 'source'):
                    self.assertIsInstance(agent[key], str)
                    self.assertTrue(agent[key].strip())
                self.assertTrue(agent['skills'])
                self.assertTrue(agent['source'].startswith('https://'))
                self.assertLessEqual(METHOD_KEYS[agent['method']], set(agent))
                if 'sha256' in agent:
                    self.assertRegex(agent['sha256'], SHA256)
                    self.assertTrue(agent['url'].startswith('https://'))
                if agent['method'] == 'uv':
                    self.assertEqual(agent['spec'], '%s==%s' % (agent['package'], agent['version']))
                if agent['method'] == 'npm-node':
                    self.assertRegex(agent['node']['sha256'], SHA256)
                    self.assertTrue(agent['node']['url'].startswith('https://nodejs.org/'))
                if agent['method'] == 'app':
                    self.assertTrue(agent['app'].endswith('.app'))
                    self.assertIsInstance(agent['bundleId'], str)
                    self.assertIsInstance(agent['bundleVersion'], str)
                    self.assertIn(agent['format'], ('zip', 'dmg'))
                if agent['method'] == 'archive':
                    self.assertIn(agent['format'], ('binary', 'zip', 'tar'))
                    self.assertIn(agent['bin'], agent['links'])

    def test_no_homebrew_entry(self):
        # A formula's version comes from the image's API cache and cannot be pinned.
        self.assertFalse([a['id'] for a in LOCK['agents'] if a['method'] == 'brew'])
        self.assertNotIn("'brew'", (REPO / 'images/macos26/guest/coding-agents.py').read_text())

    def test_every_entry_has_a_version_probe_or_an_app_bundle(self):
        for agent in LOCK['agents']:
            with self.subTest(agent=agent['id']):
                if agent['method'] != 'app':
                    self.assertTrue(agent['check'])
                if agent.get('check'):
                    self.assertIsInstance(agent['check'][0], str)

    def test_updater_switches_are_well_formed(self):
        for agent in LOCK['agents']:
            for action in agent['updates']:
                with self.subTest(agent=agent['id'], action=action):
                    kinds = set(action) & {'env', 'json', 'toml', 'command', 'hosts'}
                    self.assertEqual(len(kinds), 1)
                    if 'hosts' in action:
                        # Only an app with no off switch, and only its own feed host.
                        self.assertEqual(agent['method'], 'app')
                        for host in action['hosts']:
                            self.assertRegex(host, r'^[a-z0-9.-]+\.[a-z]+$')
                    if 'json' in action or 'toml' in action:
                        spec = action.get('json') or action['toml']
                        self.assertTrue(spec['path'].startswith('~/'))
                        self.assertTrue(spec['set'])
                    if 'command' in action:
                        # A command-written switch is verified by the file it leaves.
                        self.assertTrue(action['verify'])
                        for check in action['verify']:
                            self.assertTrue(check['path'].startswith('~/'))


class CoverageTests(unittest.TestCase):
    def test_agent_list_has_78_ids_from_the_pinned_commit(self):
        agent_list = LOCK['agentList']
        self.assertEqual(agent_list['commit'], 'a80e4c9d12d607631249d4d7d059f835d4b2f13a')
        self.assertEqual(agent_list['file'], 'src/agents.ts')
        self.assertEqual(len(agent_list['ids']), 78)
        self.assertEqual(len(set(agent_list['ids'])), 78)

    def test_every_id_is_installed_earlier_installed_here_or_explained(self):
        installed = {s for a in LOCK['agents'] for s in a['skills']}
        earlier = set(LOCK['installedEarlier'])
        missing = set(LOCK['notInstalled'])
        self.assertEqual(installed | earlier | missing, set(LOCK['agentList']['ids']))
        self.assertFalse(installed & missing)
        self.assertFalse(earlier & missing)
        self.assertFalse(installed & earlier)
        for reason in LOCK['notInstalled'].values():
            self.assertTrue(reason.strip())

    def test_agents_installed_earlier_have_their_own_phase(self):
        for skill, phase in LOCK['installedEarlier'].items():
            with self.subTest(skill=skill):
                self.assertTrue((REPO / 'images/macos26' / phase).is_file())

    def test_every_lock_entry_has_a_manifest_and_plan(self):
        for agent in LOCK['agents']:
            with self.subTest(agent=agent['id']):
                directory = REPO / 'applications' / agent['id']
                manifest = json.loads((directory / 'manifest.json').read_text())
                self.assertEqual(manifest['id'], agent['id'])
                self.assertIn('macos', manifest['platforms'])
                plan = (directory / 'PLAN.md').read_text()
                self.assertIn(agent['version'], plan)
                if agent['method'] == 'app':
                    self.assertEqual(manifest['inventoryIds'], ['bundle:' + agent['bundleId']])
                if agent['method'] == 'npm':
                    self.assertEqual(manifest['inventoryIds'], ['npm:' + agent['package']])

    def test_readme_lists_every_agent_and_every_exclusion(self):
        readme = (REPO / 'README.md').read_text()
        section = readme[readme.index('## Coding agents'):readme.index('## Publishing')]
        for agent in LOCK['agents']:
            self.assertIn('| %s |' % agent['name'], section)
        for skill in LOCK['notInstalled']:
            self.assertIn('| `%s` |' % skill, section)


class ResolutionDateTests(unittest.TestCase):
    def test_lock_carries_a_utc_resolution_date(self):
        self.assertRegex(LOCK['resolvedBefore'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

    def test_npm_and_uv_resolve_at_the_lock_date(self):
        helper = load_helper()
        self.assertEqual(helper.resolution_env(LOCK),
                         {'npm_config_before': LOCK['resolvedBefore'], 'UV_EXCLUDE_NEWER': LOCK['resolvedBefore']})

    def test_resolution_date_stays_out_of_the_shell_profile(self):
        helper = load_helper()
        self.assertNotIn('npm_config_before', helper.agent_env(LOCK))
        self.assertNotIn('UV_EXCLUDE_NEWER', helper.agent_env(LOCK))


class LineParityTests(unittest.TestCase):
    def block(self, text, start, end):
        return text[text.index(start):text.index(end)]

    def test_guest_files_are_identical_on_every_macos_line(self):
        for name in GUEST_FILES:
            reference = (REPO / 'images/macos26/guest' / name).read_bytes()
            for line in LINES:
                with self.subTest(line=line, name=name):
                    self.assertEqual((REPO / 'images' / line / 'guest' / name).read_bytes(), reference)

    def test_checks_carry_the_same_rows_on_every_macos_line(self):
        for script, start, end in (('acceptance.zsh', '# --- coding agents (phase 85;', '# --- Xcode (reports SKIP'),
                                   ('no-secrets.zsh', '# The coding agents (phase 85)', 'if gh auth status')):
            reference = self.block((REPO / 'images/macos26/checks' / script).read_text(), start, end)
            for line in LINES:
                with self.subTest(line=line, script=script):
                    text = self.block((REPO / 'images' / line / 'checks' / script).read_text(), start, end)
                    self.assertEqual(text, reference.replace('images/macos26/', 'images/%s/' % line))
                    if script == 'acceptance.zsh':
                        self.assertIn('kern.hv_vmm_present', text)
                        self.assertIn('coding-agents.py" verify', text)

    def test_selections_plan_every_agent_from_phase_85(self):
        for line in LINES:
            selection = json.loads((REPO / 'images' / line / 'application-tests.json').read_text())
            for agent in LOCK['agents']:
                with self.subTest(line=line, agent=agent['id']):
                    self.assertIn(agent['id'], selection['plans'])
                    self.assertEqual(selection['provisioning'][agent['id']]['path'],
                                     'images/%s/guest/85-coding-agents.zsh' % line)


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)

    def test_toml_switch_round_trips_into_its_table(self):
        path = self.root / 'config.toml'
        path.write_text('name = "x"\n\n[cli]\nauto_update = true\n\n[other]\nauto_update = true\n')
        self.helper.write_toml(path, 'cli', {'auto_update': False})
        self.assertTrue(self.helper.toml_contains(path, 'cli', {'auto_update': False}))
        self.assertTrue(self.helper.toml_contains(path, 'other', {'auto_update': True}))
        self.helper.write_toml(path, None, {'enable_update_checks': False})
        self.assertTrue(self.helper.toml_contains(path, None, {'enable_update_checks': False}))

    def test_json_switch_merges_without_dropping_settings(self):
        data = {'general': {'theme': 'dark', 'enableAutoUpdate': True}}
        self.helper.deep_merge(data, {'general': {'enableAutoUpdate': False}})
        self.assertEqual(data, {'general': {'theme': 'dark', 'enableAutoUpdate': False}})
        self.assertTrue(self.helper.deep_contains(data, {'general': {'enableAutoUpdate': False}}))
        self.assertFalse(self.helper.deep_contains(data, {'general': {'enableAutoUpdate': True}}))

    def test_env_block_is_rewritten_not_appended(self):
        zshenv = self.root / '.zshenv'
        zshenv.write_text('export PATH="/x:$PATH" # pilot-runtime-path\n')
        with mock.patch.object(self.helper, 'ZSHENV', zshenv):
            self.helper.write_env(LOCK)
            once = zshenv.read_text()
            self.helper.write_env(LOCK)
        self.assertEqual(zshenv.read_text(), once)
        self.assertIn('# pilot-runtime-path', once)
        for key, value in self.helper.agent_env(LOCK).items():
            self.assertIn('export %s=%s %s' % (key, value, self.helper.ENV_MARK), once)

    def test_hosts_block_is_rewritten_and_lifted(self):
        hosts = self.helper.agent_hosts(LOCK)
        self.assertIn('file.cdn.minimax.io', hosts)
        self.assertIn('download.zencoder.ai', hosts)
        base = '127.0.0.1\tlocalhost\n::1 localhost\n'
        once = self.helper.hosts_text(base, hosts)
        self.assertEqual(self.helper.hosts_text(once, hosts), once)
        self.assertTrue(once.startswith(base))
        for host in hosts:
            for line in self.helper.hosts_lines(host):
                self.assertIn(line + '\n', once)
        # install lifts the block so the vendor downloads can reach the same hosts.
        self.assertEqual(self.helper.hosts_text(once, []), base)

    def test_moved_archive_binary_is_reached_through_an_exec_wrapper(self):
        import tarfile
        payload = self.root / 'payload'
        payload.mkdir()
        (payload / 'agentkernel').write_text('#!/bin/sh\necho kernel\n')
        (payload / 'codearts').write_text('#!/bin/sh\nexec "$(dirname "$0")/bin/codearts" "$@"\n')
        archive = self.root / 'agent.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name in ('agentkernel', 'codearts'):
                tar.add(payload / name, arcname=name)
        agent = next(a for a in LOCK['agents'] if a.get('wrap'))
        with mock.patch.object(self.helper, 'LOCAL_BIN', self.root / 'bin'), \
                mock.patch.object(self.helper, 'AGENTS_ROOT', self.root / 'agents'), \
                mock.patch.object(self.helper, 'fetch', return_value=archive):
            self.helper.install_archive(agent)
            self.assertEqual(self.helper.installed_version(agent), agent['version'])
            root = self.root / 'agents' / agent['id'] / agent['version']
            self.assertTrue((root / 'bin/codearts').is_file())
            command = self.root / 'bin/codearts'
            self.assertFalse(command.is_symlink())
            self.assertIn(str(root / 'codearts'), command.read_text())
            result = self.helper.run([str(command)])
            self.assertEqual(result.stdout.strip(), 'kernel')

    def test_install_skips_an_agent_already_at_its_pin(self):
        agent = next(a for a in LOCK['agents'] if a['method'] == 'npm')
        lock = {**LOCK, 'agents': [agent]}
        lock_path = self.root / 'lock.json'
        lock_path.write_text(json.dumps(lock))
        with mock.patch.object(self.helper, 'ZSHENV', self.root / '.zshenv'), \
                mock.patch.object(self.helper, 'DOWNLOADS', self.root / 'downloads'), \
                mock.patch.object(self.helper, 'installed_version', return_value=agent['version']), \
                mock.patch.object(self.helper, 'apply_updates') as updates, \
                mock.patch.object(self.helper, 'install') as install, \
                mock.patch('sys.argv', ['coding-agents.py', 'install', '--lock', str(lock_path)]):
            self.assertEqual(self.helper.main(), 0)
        install.assert_not_called()
        updates.assert_called_once()


if __name__ == '__main__':
    unittest.main()
