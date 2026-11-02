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


def unpinned_lock():
    """The lock before vm-service published a release: every pin null."""
    return {'schemaVersion': 1, 'repository': 'WeZZard/vm-service', 'version': None,
            'platforms': {p: {'url': None, 'sha256': None, 'executableSha256': None}
                          for p in ('darwin-arm64', 'linux-arm64', 'linux-x86_64')}}


def write_unpinned(directory):
    path = Path(directory) / 'unpinned.lock.json'
    path.write_text(json.dumps(unpinned_lock(), indent=1) + '\n')
    return path


def pinned_lock(version='0.2.0', digests=None, executables=None):
    package = load('relay_agent_package', 'host/relay-agent-package.py')
    digests, executables = digests or {}, executables or {}
    return {'schemaVersion': 1, 'repository': 'WeZZard/vm-service', 'version': version,
            'platforms': {p: {'url': package.release_url('WeZZard/vm-service', version, p), 'sha256': digests.get(p, 'a' * 64),
                              'executableSha256': executables.get(p, 'b' * 64)}
                          for p in package.PLATFORMS}}


def sha(data):
    return hashlib.sha256(data).hexdigest()


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

    def test_the_committed_lock_pins_a_release_on_every_platform(self):
        lock = self.package.read_lock(REPO / 'images/macos26' / LOCK)
        self.assertIsNotNone(lock['version'], 'promote-base refuses every line while the lock is unpinned')
        for platform, pin in lock['platforms'].items():
            self.assertEqual(pin['url'], self.package.release_url(lock['repository'], lock['version'], platform))

    def test_a_pre_release_version_reads(self):
        self.assertEqual(self.check(pinned_lock('0.2.0-rc.3'))['version'], '0.2.0-rc.3')
        for version in ('0.2.0-', '0.2.0-rc..3', 'v0.2.0', '0.2'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.check(pinned_lock(version))

    def test_a_pinned_lock_names_the_release_assets(self):
        lock = pinned_lock()
        self.assertEqual(self.check(lock)['platforms']['linux-arm64']['url'],
                         'https://github.com/WeZZard/vm-service/releases/download/v0.2.0/relay-agent-0.2.0-linux-arm64.tar.gz')

    def test_malformed_locks_are_refused(self):
        unpinned = unpinned_lock()
        half = json.loads(json.dumps(unpinned)); half['platforms']['linux-arm64']['sha256'] = 'a' * 64
        moved = pinned_lock(); moved['platforms']['linux-arm64']['url'] = 'https://example.test/relay-agent.tar.gz'
        short = pinned_lock(); short['platforms']['darwin-arm64']['sha256'] = 'abc'
        unpinned_executable = pinned_lock(); unpinned_executable['platforms']['linux-arm64']['executableSha256'] = None
        no_executable = pinned_lock(); del no_executable['platforms']['linux-arm64']['executableSha256']
        missing = pinned_lock(); del missing['platforms']['linux-x86_64']
        extra = dict(pinned_lock(), note='x')
        for name, lock in (('half-pinned', half), ('foreign URL', moved), ('short digest', short),
                           ('missing platform', missing), ('extra field', extra), ('bad version', pinned_lock('latest')),
                           ('no executable pin', unpinned_executable), ('no executable field', no_executable)):
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
        result = self.package.fetch(write_unpinned(self.root), 'linux-arm64', self.root / 'out.tgz', self.write('local.tgz', data))
        self.assertEqual(result, {'version': None, 'platform': 'linux-arm64', 'sha256': hashlib.sha256(data).hexdigest(),
                                  'executableSha256': sha(executable('linux-arm64')), 'source': 'local'})
        self.assertEqual((self.root / 'out.tgz').read_bytes(), data)

    def test_an_unpinned_lock_without_a_local_build_names_the_override(self):
        with self.assertRaisesRegex(ValueError, 'RELAY_AGENT_ARCHIVE'):
            self.package.fetch(write_unpinned(self.root), 'darwin-arm64', self.root / 'out.tgz')

    def test_a_pinned_lock_accepts_only_the_pinned_bytes(self):
        data = archive([('relay-agent', executable('darwin-arm64'), 0o755)])
        lock = self.write('lock.json', json.dumps(pinned_lock(digests={'darwin-arm64': hashlib.sha256(data).hexdigest()},
                                                              executables={'darwin-arm64': sha(executable('darwin-arm64'))})))
        result = self.package.fetch(lock, 'darwin-arm64', self.root / 'out.tgz', self.write('copy.tgz', data))
        self.assertEqual((result['source'], result['version']), ('pinned', '0.2.0'))
        self.assertEqual(result['executableSha256'], sha(executable('darwin-arm64')))
        other = archive([('relay-agent', executable('darwin-arm64') + b'changed', 0o755)])
        with self.assertRaisesRegex(ValueError, 'the lock pins'):
            self.package.fetch(lock, 'darwin-arm64', self.root / 'out2.tgz', self.write('other.tgz', other))
        self.assertFalse((self.root / 'out2.tgz').exists())

    def test_a_pinned_download_must_stay_on_the_release_asset_hosts(self):
        data = archive([('relay-agent', executable('linux-arm64'), 0o755)])
        lock = self.write('lock.json', json.dumps(pinned_lock(digests={'linux-arm64': hashlib.sha256(data).hexdigest()},
                                                              executables={'linux-arm64': sha(executable('linux-arm64'))})))

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
            self.assertEqual(self.package.inspect_archive(archive([('relay-agent', executable(platform), 0o755)]), platform),
                             sha(executable(platform)))

    def test_a_pinned_archive_whose_executable_is_not_the_pin_is_refused(self):
        data = archive([('relay-agent', executable('linux-arm64'), 0o755)])
        lock = self.write('lock.json', json.dumps(pinned_lock(digests={'linux-arm64': sha(data)})))
        with self.assertRaisesRegex(ValueError, 'executable hashes to'):
            self.package.fetch(lock, 'linux-arm64', self.root / 'out.tgz', self.write('copy.tgz', data))
        self.assertFalse((self.root / 'out.tgz').exists())


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
        have = self.package.read_lock(REPO / 'images/macos26' / LOCK)['version']
        rows = self.u.update_relay_agent(False, releases_of=lambda repository: [self.release('0.1.1', platforms=[])])
        self.assertEqual(rows[0][2:], (have, '', 'no feed: no release carries relay agent archives yet'))
        rows = self.u.update_relay_agent(False, releases_of=lambda repository: [self.release('99.0.0')])
        self.assertEqual(rows[0][2:], (have, '99.0.0', 'update'))

    def test_a_release_follows_its_own_pre_releases(self):
        key = self.u.relay_key
        self.assertLess(key('0.2.0-rc.3'), key('0.2.0'))
        self.assertLess(key('0.2.0-rc.2'), key('0.2.0-rc.3'))
        self.assertLess(key('0.2.0-rc.9'), key('0.2.0-rc.10'))
        self.assertLess(key('0.1.9'), key('0.2.0-rc.1'))

    def test_a_named_release_is_pinned_even_as_a_pre_release(self):
        releases = [self.release('0.2.0-rc.3', prerelease=True, published='2026-11-02T00:00:00Z'),
                    self.release('0.2.0-rc.4', draft=True, published='2026-11-03T00:00:00Z'),
                    self.release('0.1.1', published='2026-10-01T00:00:00Z')]
        self.assertEqual(self.u.relay_release(releases, self.platforms)[0], '0.1.1')
        version, assets, sums = self.u.relay_release(releases, self.platforms, '0.2.0-rc.3')
        self.assertEqual((version, sorted(assets), sums['name']), ('0.2.0-rc.3', self.platforms, 'SHA256SUMS'))
        self.assertEqual(self.u.relay_release(releases, self.platforms, '0.2.0-rc.4'), (None, None, None), 'drafts are never pinned')
        have = self.package.read_lock(REPO / 'images/macos26' / LOCK)['version']
        for named in ('0.1.1', '0.2.0-rc.3'):
            with self.subTest(named=named):
                rows = self.u.update_relay_agent(False, releases_of=lambda repository: releases, version=named)
                self.assertEqual(rows[0][2:], (have, named, 'current' if have == named else 'update'),
                                 'a named release is pinned even when it is older or a pre-release')
        rows = self.u.update_relay_agent(False, releases_of=lambda repository: releases, version='0.2.0-rc.4')
        self.assertTrue(rows[0][4].startswith('error: no published release v0.2.0-rc.4'))

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
            for platform in self.platforms:
                self.assertEqual(moved['platforms'][platform]['executableSha256'], sha(executable(platform)))
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
        self.assertLess(source.index('grep -Fq'), source.index('tar -xzf'))
        self.assertIn('install -m 644 "$PACKAGE" "$DEST/package.json"', source)

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
        self.assertIn('/tmp/payload/relay-agent-package.json', build)
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
    def run_phase(self, manager_running, package_sha=None, succeed=True):
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
        named = (package_sha or hashlib.sha256(data).hexdigest())
        (payload / 'relay-agent-package.json').write_text(json.dumps(
            {'version': None, 'platform': 'linux-arm64', 'sha256': named, 'executableSha256': 'c' * 64, 'source': 'local'}) + '\n')
        systemctl = ('echo "$*" >> "$FIXTURE_LOG"\n'
                     'case "$*" in "--user daemon-reload") exit %d ;; "--user enable relay-agent.service")\n'
                     '  mkdir -p "$HOME/.config/systemd/user/graphical-session.target.wants"\n'
                     '  ln -sf "$HOME/.config/systemd/user/relay-agent.service" "$HOME/.config/systemd/user/graphical-session.target.wants/relay-agent.service" ;;\n'
                     '  "--user is-active --quiet graphical-session.target") exit 1 ;; esac\n') % (0 if manager_running else 1)
        (bin_dir / 'systemctl').write_text('#!/bin/sh\n' + systemctl)
        (bin_dir / 'systemctl').chmod(0o755)
        env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'HOME': str(home), 'FIXTURE_LOG': str(root / 'calls')}
        result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, succeed, result.stdout + result.stderr)
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
                kept = json.loads((home / '.local/libexec/relay-agent/package.json').read_text())
                self.assertEqual((kept['source'], kept['platform']), ('local', 'linux-arm64'))
                self.assertFalse((root / 'payload/relay-agent-package.json').exists())

    def test_phase_refuses_a_package_record_of_another_archive(self):
        root, home = self.run_phase(True, package_sha='d' * 64, succeed=False)
        self.assertFalse((home / '.local/libexec/relay-agent/relay-agent').exists())

    def test_phase_refuses_bytes_that_do_not_match_the_staged_sum(self):
        source = (REPO / 'images/ubuntu2404/guest/62-relay-agent.sh').read_text()
        self.assertLess(source.index('sha256sum "$ARCHIVE"'), source.index('tar -xzf'))


class GateTests(unittest.TestCase):
    """RA-I7: the evidence of the installed agent, and promotion only of the pinned release."""

    def setUp(self):
        self.package = load('relay_agent_package', 'host/relay-agent-package.py')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.exe = sha(executable('darwin-arm64'))
        self.archive = sha(b'archive')
        self.count = 0

    def package_record(self, **changes):
        value = {'version': '0.2.0', 'platform': 'darwin-arm64', 'sha256': self.archive,
                 'executableSha256': self.exe, 'source': 'pinned'}
        value.update(changes)
        return json.dumps(value)

    def evidence(self, uname='Darwin arm64', package=None, installed=None):
        self.count += 1
        folder = self.root / ('attempt-%d' % self.count)
        folder.mkdir()
        observed = folder / 'relay-agent.observed'
        observed.write_text('%s\n%s\n%s\n' % (uname, package or self.package_record(), installed or self.exe))
        output = folder / 'relay-agent.json'
        self.package.record(observed, output)
        return output

    def receipt(self, evidence):
        path = evidence.parent / 'receipt.json'
        path.write_text(json.dumps({'relayAgent': {'path': str(evidence), 'sha256': sha(evidence.read_bytes())}}))
        return path

    def lock(self, **kwargs):
        path = self.root / 'lock.json'
        kwargs.setdefault('digests', {'darwin-arm64': self.archive})
        kwargs.setdefault('executables', {'darwin-arm64': self.exe})
        path.write_text(json.dumps(pinned_lock(**kwargs)))
        return path

    def refused(self, lock, receipt, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.package.gate(lock, receipt)

    def test_the_evidence_names_the_archive_and_the_installed_executable(self):
        value = json.loads(self.evidence().read_text())
        self.assertEqual(value, {'schemaVersion': 1, 'platform': 'darwin-arm64',
                                 'archive': {'version': '0.2.0', 'source': 'pinned', 'sha256': self.archive},
                                 'archiveExecutableSha256': self.exe, 'installedSha256': self.exe})
        local = json.loads(self.evidence(package=self.package_record(version=None, source='local')).read_text())
        self.assertEqual(local['archive'], {'version': None, 'source': 'local', 'sha256': self.archive})

    def test_evidence_that_does_not_add_up_is_refused_and_never_rewritten(self):
        cases = {'other platform': dict(uname='Linux aarch64'), 'unknown platform': dict(uname='Darwin x86_64'),
                 'no installed hash': dict(installed='missing'),
                 'pinned without a version': dict(package=self.package_record(version=None)),
                 'extra field': dict(package=self.package_record(note='x'))}
        for name, case in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.evidence(**case)
        output = self.evidence()
        with self.assertRaises(FileExistsError):
            self.package.record(output.parent / 'relay-agent.observed', output)

    def test_the_pinned_release_passes(self):
        evidence = self.package.gate(self.lock(), self.receipt(self.evidence()))
        self.assertEqual(evidence['archive']['version'], '0.2.0')

    def test_an_unpinned_lock_promotes_nothing(self):
        receipt = self.receipt(self.evidence(package=self.package_record(version=None, source='local')))
        self.refused(write_unpinned(self.root), receipt, 'pins no release, so no base can be promoted')

    def test_a_pinned_pre_release_passes(self):
        lock = self.lock(version='0.2.0-rc.3')
        evidence = self.package.gate(lock, self.receipt(self.evidence(package=self.package_record(version='0.2.0-rc.3'))))
        self.assertEqual(evidence['archive']['version'], '0.2.0-rc.3')
        self.refused(lock, self.receipt(self.evidence()), 'is not the release the lock pins, 0.2.0-rc.3')

    def test_a_local_build_or_another_release_is_refused(self):
        lock = self.lock()
        for name, package in (('local', self.package_record(version=None, source='local')),
                              ('older', self.package_record(version='0.1.9')),
                              ('other archive', self.package_record(sha256='e' * 64))):
            with self.subTest(name=name):
                self.refused(lock, self.receipt(self.evidence(package=package)), 'is not the release the lock pins, 0.2.0')

    def test_an_installed_executable_that_is_not_the_pin_is_refused(self):
        receipt = self.receipt(self.evidence(installed='f' * 64))
        self.refused(self.lock(), receipt, 'installed relay agent executable hashes to f{64}, the lock pins')

    def test_missing_or_changed_evidence_is_refused(self):
        lock = self.lock()
        bare = self.root / 'bare.json'
        bare.write_text(json.dumps({'schemaVersion': 1}))
        self.refused(lock, bare, 'no relay agent evidence; extract it again')
        evidence = self.evidence()
        receipt = self.receipt(evidence)
        evidence.write_text(evidence.read_text().replace('"installedSha256"', '"installedSha256" '))
        self.refused(lock, receipt, 'changed after it was bound')

    def test_the_command_line_says_why(self):
        receipt = self.receipt(self.evidence(package=self.package_record(version=None, source='local')))
        result = subprocess.run(['python3', str(REPO / 'host/relay-agent-package.py'), 'gate',
                                 '--lock', str(REPO / 'images/macos26' / LOCK), '--receipt', str(receipt)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('relay agent: relay agent local build (darwin-arm64', result.stderr)
        result = subprocess.run(['python3', str(REPO / 'host/relay-agent-package.py'), 'gate',
                                 '--lock', str(self.lock()), '--receipt', str(self.receipt(self.evidence()))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_promotion_gates_on_the_work_receipt_before_any_rename(self):
        promote = (REPO / 'host/promote-base.zsh').read_text()
        self.assertIn('relay-agent-package.py" gate --lock "$RELAY_LOCK" --receipt "$WORK_ACCEPTANCE"', promote)
        self.assertLess(promote.index('inventory_verify_work'), promote.index(' gate --lock'))
        self.assertLess(promote.index(' gate --lock'), promote.index('tart rename "$WORK_VM"'))
        self.assertLess(promote.index(' gate --lock'), promote.index('invalidate --output "$BASE_INVENTORY"'))


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
