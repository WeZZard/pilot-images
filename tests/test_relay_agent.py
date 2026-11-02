"""The relay agent in the images: its lock, the package check, update-software, phase 62, the
phase 65 grants and the checks (docs/relay-agent.md).

Fixture-only: nothing here reaches the network, a VM, launchd or systemd.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
LINES = ('macos26', 'macos27', 'ubuntu2404')
MACOS = ('macos26', 'macos27')
LOCK = 'guest/relay-agent.lock.json'
NO_SECRETS = {'macos26': 'no-secrets.zsh', 'macos27': 'no-secrets.zsh', 'ubuntu2404': 'no-secrets.sh'}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executable(platform):
    if platform == 'darwin-arm64':
        return struct.pack('<II', 0xFEEDFACF, 0x0100000C) + bytes(64)
    machine = {'linux-arm64': 183, 'linux-x86_64': 62}[platform]
    return b'\x7fELF\x02\x01' + bytes(12) + struct.pack('<H', machine) + bytes(64)


def archive(members):
    """A gzipped tar of (name, bytes, mode) members."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for name, data, mode in members:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def pinned_lock(version='0.2.0', digests=None):
    package = load('relay_agent_package', 'host/relay-agent-package.py')
    digests = digests or {}
    return {'schemaVersion': 1, 'repository': 'WeZZard/vm-service', 'version': version,
            'platforms': {p: {'url': package.release_url('WeZZard/vm-service', version, p), 'sha256': digests.get(p, 'a' * 64)}
                          for p in package.PLATFORMS}}


class LockTests(unittest.TestCase):
    def setUp(self):
        self.package = load('relay_agent_package', 'host/relay-agent-package.py')

    def test_every_line_carries_the_same_lock(self):
        reference = (REPO / 'images/macos26' / LOCK).read_bytes()
        for line in LINES:
            with self.subTest(line=line):
                self.assertEqual((REPO / 'images' / line / LOCK).read_bytes(), reference)

    def test_the_committed_lock_reads_and_names_every_platform(self):
        lock = self.package.read_lock(REPO / 'images/macos26' / LOCK)
        self.assertEqual(sorted(lock['platforms']), ['darwin-arm64', 'linux-arm64', 'linux-x86_64'])
        self.assertEqual((REPO / 'images/macos26' / LOCK).read_text(), json.dumps(lock, indent=1) + '\n',
                         'the lock is written as update-software writes it')

    def check(self, lock):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock.json'
            path.write_text(json.dumps(lock))
            return self.package.read_lock(path)

    def test_a_pinned_lock_names_the_release_assets(self):
        lock = pinned_lock()
        self.assertEqual(self.check(lock)['platforms']['linux-arm64']['url'],
                         'https://github.com/WeZZard/vm-service/releases/download/v0.2.0/relay-agent-0.2.0-linux-arm64.tar.gz')

    def test_malformed_locks_are_refused(self):
        unpinned = json.loads((REPO / 'images/macos26' / LOCK).read_text())
        half = json.loads(json.dumps(unpinned)); half['platforms']['linux-arm64']['sha256'] = 'a' * 64
        moved = pinned_lock(); moved['platforms']['linux-arm64']['url'] = 'https://example.test/relay-agent.tar.gz'
        short = pinned_lock(); short['platforms']['darwin-arm64']['sha256'] = 'abc'
        missing = pinned_lock(); del missing['platforms']['linux-x86_64']
        extra = dict(pinned_lock(), note='x')
        for name, lock in (('half-pinned', half), ('foreign URL', moved), ('short digest', short),
                           ('missing platform', missing), ('extra field', extra), ('bad version', pinned_lock('latest'))):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(lock)

    def test_a_guest_uname_names_its_platform(self):
        self.assertEqual(self.package.platform_of('Darwin arm64'), 'darwin-arm64')
        self.assertEqual(self.package.platform_of('Linux aarch64\n'), 'linux-arm64')
        self.assertEqual(self.package.platform_of('Linux x86_64'), 'linux-x86_64')
        with self.assertRaises(ValueError):
            self.package.platform_of('Darwin x86_64')


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.package = load('relay_agent_package', 'host/relay-agent-package.py')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data) if isinstance(data, bytes) else path.write_text(data)
        return path

    def test_an_unpinned_lock_takes_a_local_build_and_reports_it(self):
        data = archive([('relay-agent', executable('linux-arm64'), 0o755)])
        result = self.package.fetch(REPO / 'images/ubuntu2404' / LOCK, 'linux-arm64', self.root / 'out.tgz', self.write('local.tgz', data))
        self.assertEqual(result, {'version': None, 'platform': 'linux-arm64', 'sha256': hashlib.sha256(data).hexdigest(), 'source': 'local'})
        self.assertEqual((self.root / 'out.tgz').read_bytes(), data)

    def test_an_unpinned_lock_without_a_local_build_names_the_override(self):
        with self.assertRaisesRegex(ValueError, 'RELAY_AGENT_ARCHIVE'):
            self.package.fetch(REPO / 'images/macos26' / LOCK, 'darwin-arm64', self.root / 'out.tgz')

    def test_a_pinned_lock_accepts_only_the_pinned_bytes(self):
        data = archive([('relay-agent', executable('darwin-arm64'), 0o755)])
        lock = self.write('lock.json', json.dumps(pinned_lock(digests={'darwin-arm64': hashlib.sha256(data).hexdigest()})))
        result = self.package.fetch(lock, 'darwin-arm64', self.root / 'out.tgz', self.write('copy.tgz', data))
        self.assertEqual((result['source'], result['version']), ('pinned', '0.2.0'))
        other = archive([('relay-agent', executable('darwin-arm64') + b'changed', 0o755)])
        with self.assertRaisesRegex(ValueError, 'the lock pins'):
            self.package.fetch(lock, 'darwin-arm64', self.root / 'out2.tgz', self.write('other.tgz', other))
        self.assertFalse((self.root / 'out2.tgz').exists())

    def test_a_pinned_download_must_stay_on_the_release_asset_hosts(self):
        data = archive([('relay-agent', executable('linux-arm64'), 0o755)])
        lock = self.write('lock.json', json.dumps(pinned_lock(digests={'linux-arm64': hashlib.sha256(data).hexdigest()})))

        class Response(io.BytesIO):
            def __init__(self, url):
                super().__init__(data)
                self.url = url

            def geturl(self):
                return self.url

        def opener(final):
            return lambda request, timeout: Response(final)
        self.package.fetch(lock, 'linux-arm64', self.root / 'a.tgz', opener=opener('https://release-assets.githubusercontent.com/x'))
        with self.assertRaisesRegex(ValueError, 'redirected'):
            self.package.fetch(lock, 'linux-arm64', self.root / 'b.tgz', opener=opener('https://example.test/x'))

    def test_an_archive_holds_one_executable_for_the_platform(self):
        cases = {
            'Linux build for macOS': ('darwin-arm64', [('relay-agent', executable('linux-arm64'), 0o755)]),
            'x86_64 build for arm64': ('linux-arm64', [('relay-agent', executable('linux-x86_64'), 0o755)]),
            'extra member': ('linux-arm64', [('relay-agent', executable('linux-arm64'), 0o755), ('README', b'x', 0o644)]),
            'nested path': ('linux-arm64', [('bin/relay-agent', executable('linux-arm64'), 0o755)]),
            'not executable': ('linux-arm64', [('relay-agent', executable('linux-arm64'), 0o644)]),
        }
        for name, (platform, members) in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.package.inspect_archive(archive(members), platform)
        for platform in self.package.PLATFORMS:
            self.package.inspect_archive(archive([('relay-agent', executable(platform), 0o755)]), platform)


class UpdateSoftwareTests(unittest.TestCase):
    def setUp(self):
        self.u = load('update_software', 'host/update-software.py')
        self.package = load('relay_agent_package', 'host/relay-agent-package.py')
        self.platforms = sorted(self.package.PLATFORMS)

    def release(self, version, platforms=None, draft=False, prerelease=False, published='2026-11-01T00:00:00Z'):
        names = ['relay-agent-%s-%s.tar.gz' % (version, p) for p in (self.platforms if platforms is None else platforms)]
        assets = [{'name': n, 'browser_download_url': 'https://github.com/WeZZard/vm-service/releases/download/v%s/%s' % (version, n)}
                  for n in names + ['SHA256SUMS']]
        return {'tag_name': 'v' + version, 'draft': draft, 'prerelease': prerelease, 'published_at': published, 'assets': assets}

    def test_the_newest_complete_published_release_wins(self):
        releases = [self.release('0.1.1', platforms=[], published='2026-10-01T00:00:00Z'),
                    self.release('0.3.0', draft=True, published='2026-11-03T00:00:00Z'),
                    self.release('0.4.0', prerelease=True, published='2026-11-04T00:00:00Z'),
                    self.release('0.2.1', platforms=['darwin-arm64'], published='2026-11-02T00:00:00Z'),
                    self.release('0.2.0', published='2026-11-01T00:00:00Z')]
        version, assets, sums = self.u.relay_release(releases, self.platforms)
        self.assertEqual(version, '0.2.0')
        self.assertEqual(sorted(assets), self.platforms)
        self.assertEqual(sums['name'], 'SHA256SUMS')
        self.assertEqual(self.u.relay_release(releases[:1], self.platforms), (None, None, None))

    def test_a_release_without_archives_is_reported_not_failed(self):
        rows = self.u.update_relay_agent(False, releases_of=lambda repository: [self.release('0.1.1', platforms=[])])
        self.assertEqual(rows[0][2:], ('unpinned', '', 'no feed: no release carries relay agent archives yet'))
        rows = self.u.update_relay_agent(False, releases_of=lambda repository: [self.release('0.2.0')])
        self.assertEqual(rows[0][2:], ('unpinned', '0.2.0', 'update'))

    def test_pins_are_hashed_matched_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            files, sums = {}, []
            for platform in self.platforms:
                data = archive([('relay-agent', executable(platform), 0o755)])
                name = 'relay-agent-0.2.0-%s.tar.gz' % platform
                files[self.package.release_url('WeZZard/vm-service', '0.2.0', platform)] = Path(directory) / name
                (Path(directory) / name).write_bytes(data)
                sums.append('%s  %s' % (hashlib.sha256(data).hexdigest(), name))
            _, assets, _ = self.u.relay_release([self.release('0.2.0')], self.platforms)
            lock = json.loads((REPO / 'images/macos26' / LOCK).read_text())
            moved = self.u.relay_pins(lock, '0.2.0', assets, '\n'.join(sums), fetch=files.get, package=self.package)
            self.assertEqual(moved['version'], '0.2.0')
            with tempfile.NamedTemporaryFile('w', suffix='.json') as written:
                written.write(json.dumps(moved)); written.flush()
                self.assertEqual(self.package.read_lock(written.name)['platforms'], moved['platforms'])
            wrong = sums[:1] + ['%s  %s' % ('0' * 64, sums[1].split()[1])] + sums[2:]
            with self.assertRaises(SystemExit):
                self.u.relay_pins(lock, '0.2.0', assets, '\n'.join(wrong), fetch=files.get, package=self.package)


class MacPhaseTests(unittest.TestCase):
    PHASE = 'guest/62-relay-agent.zsh'

    def test_phase_62_is_identical_and_discoverable_on_every_macos_line(self):
        reference = (REPO / 'images/macos26' / self.PHASE).read_bytes()
        for line in MACOS:
            with self.subTest(line=line):
                path = REPO / 'images' / line / self.PHASE
                self.assertEqual(path.read_bytes(), reference)
                self.assertTrue(path.stat().st_mode & 0o100)
        self.assertIn(b'source "${0:A:h}/lib.zsh"', reference)

    def test_phase_installs_and_checks_before_it_loads_the_job(self):
        source = (REPO / 'images/macos26' / self.PHASE).read_text()
        self.assertIn('DEST="$HOME/.local/libexec/relay-agent"', source)
        self.assertIn('shasum -a 256 "$ARCHIVE"', source)
        self.assertIn('codesign --verify --strict -R="identifier \\"$LABEL\\""', source)
        self.assertLess(source.index('codesign --verify'), source.index('launchctl bootstrap'))
        self.assertIn('LABEL=com.wezzard.relay-agent', source)
        self.assertIn('PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"', source)

    def test_the_launch_agent_runs_the_agent_in_the_aqua_session_and_keeps_it_alive(self):
        source = (REPO / 'images/macos26' / self.PHASE).read_text()
        plist = source[source.index('<?xml'):source.index('</plist>') + len('</plist>')]
        plist = plist.replace('$LABEL', 'com.wezzard.relay-agent').replace('$AGENT', '/home/x/.local/libexec/relay-agent/relay-agent').replace('$HOME', '/home/x')
        import plistlib
        job = plistlib.loads(plist.encode())
        self.assertEqual(job['Label'], 'com.wezzard.relay-agent')
        self.assertEqual(job['ProgramArguments'], ['/home/x/.local/libexec/relay-agent/relay-agent', 'run'])
        self.assertIs(job['RunAtLoad'], True)
        self.assertIs(job['KeepAlive'], True)
        self.assertEqual(job['LimitLoadToSessionType'], 'Aqua')

    def test_build_base_stages_the_package_and_reboots_after_phase_62(self):
        build = (REPO / 'host/build-base.zsh').read_text()
        self.assertIn('relay-agent-package.py', build)
        self.assertIn('RELAY_AGENT_ARCHIVE', build)
        self.assertIn("--uname \"$GUEST_UNAME\"", build)
        self.assertIn('/tmp/payload/relay-agent.sha256', build)
        self.assertIn('"$ONLY_PHASE" == 62 ||', build)
        self.assertIn('"$ONLY_PHASE" == 62 || "$ONLY_PHASE" == 65', build)


class MacGrantTests(unittest.TestCase):
    def test_phase_65_grants_the_agent_the_rows_it_grants_sshd_keygen_wrapper(self):
        for line in MACOS:
            with self.subTest(line=line):
                source = (REPO / 'images' / line / 'guest/65-automation.zsh').read_text()
                self.assertIn('CLIENTS=("$CLIENT" "$AGENT")', source)
                self.assertIn('AGENT="$HOME/.local/libexec/relay-agent/relay-agent"', source)
                self.assertIn('CLIENT_REQ[$AGENT]=$(identifier_req_hex "$AGENT_ID")', source)
                self.assertIn('CLIENT_REQ[$CLIENT]=$(csreq_hex "$CLIENT")', source)
                self.assertEqual(source.count('for c in "${CLIENTS[@]}"; do'), 3, 'Apple Events rows, data-class rows, verification')

    def test_the_agent_requirement_names_only_its_signing_identifier(self):
        for line in MACOS:
            with self.subTest(line=line):
                lib = (REPO / 'images' / line / 'guest/lib.zsh').read_text()
                function = re.search(r'^identifier_req_hex\(\) \{.*?^\}', lib, re.M | re.S).group(0)
                self.assertIn('csreq -r="identifier \\"$1\\"" -b "$blob"', function)
        reference = re.search(r'^identifier_req_hex\(\) \{.*?^\}', (REPO / 'images/macos26/guest/lib.zsh').read_text(), re.M | re.S).group(0)
        self.assertIn(reference, (REPO / 'images/macos27/guest/lib.zsh').read_text())

    @unittest.skipUnless(Path('/usr/bin/csreq').exists(), 'needs macOS csreq')
    def test_the_requirement_compiles_to_the_blob_tcc_stores(self):
        script = 'source %s; identifier_req_hex com.wezzard.relay-agent' % (REPO / 'images/macos26/guest/lib.zsh')
        blob = subprocess.check_output(['/bin/zsh', '-c', script], text=True)
        self.assertEqual(blob, 'fade0c000000002c000000010000000200000017636f6d2e77657a7a6172642e72656c61792d6167656e7400')


class UbuntuPhaseTests(unittest.TestCase):
    def run_phase(self, manager_running):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        payload, bin_dir, home = root / 'payload', root / 'bin', root / 'home'
        for folder in (payload, bin_dir, home):
            folder.mkdir()
        script = root / '62-relay-agent.sh'
        script.write_text((REPO / 'images/ubuntu2404/guest/62-relay-agent.sh').read_text().replace('/tmp/payload/', str(payload) + '/'))
        (root / 'lib.sh').write_text('set -euo pipefail\nglog(){ :; }\n')
        data = archive([('relay-agent', b'#!/bin/sh\necho relay-agent 0.1.1\n', 0o755)])
        (payload / 'relay-agent.tar.gz').write_bytes(data)
        (payload / 'relay-agent.sha256').write_text(hashlib.sha256(data).hexdigest() + '\n')
        systemctl = ('echo "$*" >> "$FIXTURE_LOG"\n'
                     'case "$*" in "--user daemon-reload") exit %d ;; "--user enable relay-agent.service")\n'
                     '  mkdir -p "$HOME/.config/systemd/user/graphical-session.target.wants"\n'
                     '  ln -sf "$HOME/.config/systemd/user/relay-agent.service" "$HOME/.config/systemd/user/graphical-session.target.wants/relay-agent.service" ;;\n'
                     '  "--user is-active --quiet graphical-session.target") exit 1 ;; esac\n') % (0 if manager_running else 1)
        (bin_dir / 'systemctl').write_text('#!/bin/sh\n' + systemctl)
        (bin_dir / 'systemctl').chmod(0o755)
        env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'HOME': str(home), 'FIXTURE_LOG': str(root / 'calls')}
        result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return root, home

    def test_phase_installs_the_agent_and_enables_its_user_unit(self):
        for running in (True, False):
            with self.subTest(manager_running=running):
                root, home = self.run_phase(running)
                agent = home / '.local/libexec/relay-agent/relay-agent'
                self.assertTrue(agent.stat().st_mode & 0o100)
                unit = (home / '.config/systemd/user/relay-agent.service').read_text()
                for line in ('ExecStart=%h/.local/libexec/relay-agent/relay-agent run', 'WantedBy=graphical-session.target',
                             'PartOf=graphical-session.target', 'Restart=always'):
                    self.assertIn(line + '\n', unit)
                wants = home / '.config/systemd/user/graphical-session.target.wants/relay-agent.service'
                self.assertTrue(wants.is_symlink())
                self.assertEqual(Path(os.readlink(wants)), home / '.config/systemd/user/relay-agent.service')
                self.assertEqual('--user enable relay-agent.service' in (root / 'calls').read_text(), running)
                self.assertFalse((root / 'payload/relay-agent.tar.gz').exists())

    def test_phase_refuses_bytes_that_do_not_match_the_staged_sum(self):
        source = (REPO / 'images/ubuntu2404/guest/62-relay-agent.sh').read_text()
        self.assertLess(source.index('sha256sum "$ARCHIVE"'), source.index('tar -xzf'))


class CheckTests(unittest.TestCase):
    def test_no_secrets_requires_the_configuration_and_state_absent_on_every_line(self):
        for line in LINES:
            with self.subTest(line=line):
                source = (REPO / 'images' / line / 'checks' / NO_SECRETS[line]).read_text()
                self.assertIn('absent "$HOME/.config/relay-agent/config.json"', source)
                self.assertIn('absent "$HOME/.local/state/relay-agent"', source)

    def test_ubuntu_no_secrets_fails_on_a_configuration_or_state(self):
        script = REPO / 'images/ubuntu2404/checks/no-secrets.sh'
        for relative, failed in ((None, False), ('.config/relay-agent/config.json', True), ('.local/state/relay-agent/executions', True)):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as home:
                if relative:
                    (Path(home) / relative).parent.mkdir(parents=True)
                    (Path(home) / relative).write_text('{}')
                result = subprocess.run(['/bin/bash', str(script)], env={**os.environ, 'HOME': home}, capture_output=True, text=True)
                self.assertEqual(result.returncode != 0, failed, result.stdout)

    def block(self, path, start, end):
        text = path.read_text()
        return text[text.index(start):text.index(end)]

    def test_macos_acceptance_reads_the_job_from_the_aqua_session_on_every_line(self):
        start, end = '# --- relay agent (phases 62 and 65', 'if pi list'
        reference = self.block(REPO / 'images/macos26/checks/acceptance.zsh', start, end)
        for line in MACOS:
            with self.subTest(line=line):
                self.assertEqual(self.block(REPO / 'images' / line / 'checks/acceptance.zsh', start, end), reference)
        self.assertIn('launchctl print "gui/$(id -u)/$_ra_label"', reference)
        self.assertIn("session = Aqua", reference)
        self.assertIn('LimitLoadToSessionType', reference)
        self.assertIn('waiting for its configuration', reference)
        self.assertIn("client='$_ra_agent'", reference)

    def test_ubuntu_acceptance_places_the_agent_in_the_desktop_session(self):
        block = self.block(REPO / 'images/ubuntu2404/checks/acceptance.sh', '# --- relay agent (phase 62', '# --- desktop dconf ---')
        self.assertLess((REPO / 'images/ubuntu2404/checks/acceptance.sh').read_text().index('DESKTOP_SID="$(desktop_session)"'),
                        (REPO / 'images/ubuntu2404/checks/acceptance.sh').read_text().index('# --- relay agent (phase 62'))
        for needle in ('systemctl --user is-active relay-agent.service', 'graphical-session.target',
                       'loginctl show-user "$(id -u)" -p Display --value', '"$RA_USER_DISPLAY" = "$DESKTOP_SID"',
                       '/proc/$RA_PID/exe', 'waiting for its configuration'):
            self.assertIn(needle, block)


if __name__ == '__main__':
    unittest.main()
