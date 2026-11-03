"""The checks fail closed (2026-11-03 decision): a tool that is missing or
fails, or a path that cannot be searched, is a FAIL with a reason, never a PASS.

Each check script runs in a guest sandbox (isolation.guest_environment) whose
PATH holds exactly the tools and stubs a test names, first with all of them,
so the checks under test pass, then with one tool removed or failing, which
must turn those checks into FAILs.
"""
import isolation  # first: the tests keep nothing of the shell's environment
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CHECKS = sorted(REPO.glob('images/*/checks/*'))
MACOS_LINES = ('macos26', 'macos27')
BLOCK_START, BLOCK_END = '# --- fail closed (2026-11-03)', '# --- end fail closed ---\n'
SHELLS = {'.sh': '/bin/bash', '.zsh': '/bin/zsh'}
UNPRIVILEGED = os.geteuid() != 0


def block(text):
    return text[text.index(BLOCK_START):text.index(BLOCK_END) + len(BLOCK_END)]


def passes(stdout):
    return {line[len('PASS  '):] for line in stdout.splitlines() if line.startswith('PASS  ')}


def fails(stdout):
    return [line[len('FAIL  '):] for line in stdout.splitlines() if line.startswith('FAIL  ')]


class Sandbox:
    """A scratch root: the script copied in with its host paths moved under it."""

    def __init__(self, case, source, replacements=()):
        temporary = tempfile.TemporaryDirectory()
        case.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        (self.root / 'tmp').mkdir()
        text = source.read_text()
        for old, new in replacements:
            text = text.replace(old, new.format(root=self.root))
        self.script = self.root / 'checks' / source.name
        self.script.parent.mkdir()
        self.script.write_text(text)
        self.shell = SHELLS[source.suffix]

    def write(self, relative, text=''):
        path = self.home / relative if not relative.startswith('/') else self.root / relative[1:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run(self, stubs, tools, drop=None):
        """Run the script; `drop` names a stub or tool the sandbox goes without.

        Every run gets a fresh sandbox, so no stub is ever written through a
        link an earlier run made to a system tool.
        """
        sandbox = Path(tempfile.mkdtemp(prefix='sandbox-', dir=self.root))
        env = isolation.guest_environment(sandbox, {k: v for k, v in stubs.items() if k != drop},
                                          [t for t in tools if t != drop], HOME=self.home, TMPDIR=self.root / 'tmp')
        return subprocess.run([self.shell, str(self.script)], env=env, capture_output=True, text=True, timeout=120)


class ConventionTests(unittest.TestCase):
    def test_every_check_opens_with_the_same_fail_closed_block(self):
        reference = block((REPO / 'images/ubuntu2404/checks/no-secrets.sh').read_text())
        self.assertGreaterEqual(len(CHECKS), 6)
        for path in CHECKS:
            with self.subTest(check=str(path.relative_to(REPO))):
                self.assertEqual(block(path.read_text()), reference)

    def test_no_check_judges_absence_by_a_tool_left_unchecked(self):
        # Outside the block, a FAIL that an `if` reaches tests a shell variable
        # the script set or a tool's presence, never a tool's status or a path; absence goes
        # through `absent`, `missing` or `none`. And no search pipes into grep -q.
        negative = re.compile(r'^[ \t]*(?:el)?if ([^\n]*?);\s*then\s+(?:bad\b|print -- "FAIL|echo "FAIL)', re.M)
        variable_test = re.compile(r'^(?:\[\[? -[zn] "\$\{?\w+\}?" \]\]?|! command -v [\w-]+ >/dev/null 2>&1)$')
        for path in CHECKS:
            with self.subTest(check=str(path.relative_to(REPO))):
                text = path.read_text().replace(block(path.read_text()), '')
                self.assertEqual([c for c in negative.findall(text) if not variable_test.match(c)], [])
                self.assertNotRegex(text, r'\|\s*grep -q \.')


class PrimitiveTests(unittest.TestCase):
    """`missing`, the one way a check decides that a path is absent."""

    @unittest.skipUnless(UNPRIVILEGED, 'root searches every directory')
    def test_missing_tells_absent_present_and_unknown_apart_in_bash_and_zsh(self):
        functions = block((REPO / 'images/ubuntu2404/checks/no-secrets.sh').read_text())
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / 'open').mkdir()
        (root / 'open/file').write_text('x')
        (root / 'open/dangling').symlink_to(root / 'nowhere')
        (root / 'shut/inner').mkdir(parents=True)
        (root / 'shut').chmod(0)
        self.addCleanup((root / 'shut').chmod, 0o755)
        cases = {'open/file': 1, 'open/dangling': 1, 'open/none': 0, 'open/none/deeper': 0,
                 'open/file/under-a-file': 0, 'shut/inner': 2, 'shut/none': 2, 'none/at/all': 0}
        for shell in ('/bin/bash', '/bin/zsh'):
            for relative, expected in cases.items():
                with self.subTest(shell=shell, path=relative):
                    script = functions + f'missing "{root / relative}"; echo $?'
                    out = subprocess.run([shell, '-c', script], env=isolation.guest_environment(root / 'sandbox'),
                                         capture_output=True, text=True).stdout
                    self.assertEqual(out.strip(), str(expected))


class NoSecretsTests(unittest.TestCase):
    """Each line's no-secrets scan, on a clean home that gives every search something to search."""

    def sandbox(self, line):
        name = 'no-secrets.sh' if line == 'ubuntu2404' else 'no-secrets.zsh'
        # The guest's Homebrew is the host's own on a Mac: the sandbox has none.
        box = Sandbox(self, REPO / 'images' / line / 'checks' / name, (('/opt/homebrew/bin:', ''),))
        for directory in ('.ssh', '.cursor', '.config/acli', 'snap/firefox', '.cache/ms-playwright/daemon', '.local/share/keyrings'):
            (box.home / directory).mkdir(parents=True, exist_ok=True)
        box.write('.ssh/id_ed25519.pub', 'ssh-ed25519 AAAA fixture')
        box.write('.cursor/cli-config.json', '{}')
        box.write('.config/acli/global_auth_config.yaml', 'profiles: []\n')
        box.write('.pi/agent/settings.json', '{"theme": "dark"}\n')
        box.write('.local/share/keyrings/login.keyring', '[keyring]\ndisplay-name=Login\n')
        box.write('.local/share/keyrings/default', 'login')
        return box

    # line -> (stubs, system tools, {tool: the checks that cannot pass without it})
    LINES = {
        'ubuntu2404': ({}, ('find', 'grep'), {
            'find': {'no firefox saved logins', 'no browser cookie stores', 'no private ssh keys', 'no other keyrings',
                     'no mcp-* profile directory holds cookies', 'no playwright-cli session files',
                     'no cookie store under ~/.cache/ms-playwright'},
            'grep': {'no credential material in pi settings', 'login keyring holds no items'}}),
        **{line: ({'gh': 'exit 1', 'security': 'exit 44'}, ('find', 'grep'), {
            'find': {'no coding-agent credential files', 'no private SSH keys'},
            'grep': {'no acli profile', 'no Cursor CLI account'},
            'gh': {'gh unauthenticated'},
            'security': {'no Claude Code keychain item'}}) for line in MACOS_LINES},
    }

    def test_a_clean_home_passes_every_line(self):
        for line, (stubs, tools, _) in self.LINES.items():
            with self.subTest(line=line):
                result = self.sandbox(line).run(stubs, tools)
                self.assertEqual((result.returncode, fails(result.stdout)), (0, []), result.stdout + result.stderr)

    def test_every_tool_removed_is_a_fail_with_its_reason(self):
        for line, (stubs, tools, needs) in self.LINES.items():
            box = self.sandbox(line)
            clean = passes(box.run(stubs, tools).stdout)
            for tool, checks in needs.items():
                with self.subTest(line=line, tool=tool):
                    self.assertLessEqual(checks, clean)
                    result = box.run(stubs, tools, drop=tool)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(checks & passes(result.stdout), set(), result.stdout)
                    self.assertIn(f'required tool missing: {tool}', fails(result.stdout))
                    for check in checks:
                        self.assertIn(f'cannot check ({check}): a tool that', result.stdout)
                    self.assertIn('NO-SECRETS SCAN FAILED', result.stdout)

    def test_a_tool_that_fails_is_a_fail(self):
        failing = {'find': 'exit 1', 'grep': 'exit 2', 'gh': 'exit 4', 'security': 'exit 51'}
        for line, (stubs, tools, needs) in self.LINES.items():
            box = self.sandbox(line)
            for tool, checks in needs.items():
                with self.subTest(line=line, tool=tool):
                    result = box.run({**stubs, tool: failing[tool]}, [t for t in tools if t != tool])
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(checks & passes(result.stdout), set(), result.stdout)
                    for check in checks:
                        self.assertIn(f'cannot check ({check}):', result.stdout)

    @unittest.skipUnless(UNPRIVILEGED, 'root searches every directory')
    def test_an_unreadable_path_is_a_fail(self):
        for line, (stubs, tools, _) in self.LINES.items():
            with self.subTest(line=line):
                box = self.sandbox(line)
                (box.home / '.config/relay-agent').mkdir(parents=True)
                (box.home / '.config/relay-agent').chmod(0)
                self.addCleanup((box.home / '.config/relay-agent').chmod, 0o755)
                # The key searches stop at ~/.ssh itself; these descend.
                keys, deep = (('no browser cookie stores', 'snap/inner') if line == 'ubuntu2404'
                              else ('no coding-agent credential files', '.cursor/inner'))
                (box.home / deep).mkdir()
                (box.home / deep).chmod(0)
                self.addCleanup((box.home / deep).chmod, 0o755)
                result = box.run(stubs, tools)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(f'cannot check ({keys}):', result.stdout)
                self.assertIn(f'cannot tell whether {box.home}/.config/relay-agent/config.json is present', result.stdout)

    def test_a_secret_is_named_never_printed(self):
        box = self.sandbox('ubuntu2404')
        box.write('.pi/agent/settings.json', '{"key": "sk-fixturefixture"}\n')
        result = box.run({}, ('find', 'grep'))
        self.assertIn('contains credential-like material', result.stdout)
        self.assertNotIn('sk-fixture', result.stdout + result.stderr)


class AcceptanceTests(unittest.TestCase):
    """The acceptance checks that assert absence, run whole among stubs."""

    UBUNTU_STUBS = {'sleep': 'exit 0', 'pgrep': 'exit 1', 'systemctl': 'echo disabled',
                    'playwright-cli': 'exit 0'}
    UBUNTU_TOOLS = ('cat', 'rm', 'grep', 'find', 'mktemp')

    def ubuntu(self):
        return Sandbox(self, REPO / 'images/ubuntu2404/checks/acceptance.sh')

    def test_ubuntu_absence_checks_pass_among_stubs_that_find_nothing(self):
        result = self.ubuntu().run(self.UBUNTU_STUBS, self.UBUNTU_TOOLS)
        self.assertLessEqual({'no gnome-initial-setup process', 'boot not gated by systemd-networkd-wait-online',
                              'cli smoke: session closed'}, passes(result.stdout), result.stdout + result.stderr)

    def test_ubuntu_absence_checks_fail_without_their_tool(self):
        box = self.ubuntu()
        for change, check in ((dict(drop='pgrep'), 'no gnome-initial-setup process'),
                              (dict(drop='systemctl'), 'boot not gated by systemd-networkd-wait-online'),
                              (dict(stubs={'playwright-cli': '[ "$1" != list ] || exit 3'}), 'cli smoke: session closed')):
            with self.subTest(change=change):
                result = box.run({**self.UBUNTU_STUBS, **change.get('stubs', {})}, self.UBUNTU_TOOLS, change.get('drop'))
                self.assertNotIn(check, passes(result.stdout))
                self.assertIn(f'cannot check ({check}):', result.stdout)
                self.assertNotEqual(result.returncode, 0)

    MACOS_STUBS = {'sleep': 'exit 0', 'sysctl': 'echo 1', 'pgrep': 'exit 1', 'xattr': 'exit 0',
                   'crontab': 'echo "crontab: no crontab for fixture" >&2; exit 1'}
    MACOS_TOOLS = ('grep',)
    CLAUDE = '#!/bin/sh\n[ "$1 $2" = "mcp get" ] && echo "$3: npx -y @fixture/$3@1.0.0"\nexit 0\n'

    def macos(self, line):
        box = Sandbox(self, REPO / 'images' / line / 'checks/acceptance.zsh',
                      (('/tmp/', '{root}/tmp/'), ('/Applications', '{root}/Applications')))
        (box.root / 'Applications/Fixture.app').mkdir(parents=True)
        (box.root / 'Applications/Unity').mkdir()
        box.write('/guest/unity.lock', 'UNITY_VERSION=0.0.0f0\n')
        box.write('.codex/config.toml', '[mcp_servers.playwright]\nargs = ["@playwright/mcp@1.0.0"]\n')
        claude = box.write('.local/bin/claude', self.CLAUDE)
        claude.chmod(0o755)
        return box

    def macos_checks(self, line):
        checks = {'pgrep': {'no Setup Assistant/MiniBuddy modal running'},
                  'xattr': {'no quarantined app bundles in /Applications'},
                  'crontab': {'VM has no crontab'}, 'grep': {'npx MCP servers pinned'}}
        if line == 'macos26':
            checks['pgrep'].add('no Unity process running')
            checks['xattr'].add('no quarantine under /Applications/Unity')
        return checks

    def test_macos_absence_checks_pass_among_stubs_that_find_nothing(self):
        for line in MACOS_LINES:
            with self.subTest(line=line):
                box = self.macos(line)
                result = box.run(self.MACOS_STUBS, self.MACOS_TOOLS)
                expected = set().union(*self.macos_checks(line).values(), {'claude playwright bare (host parity)'})
                # The sandbox's /Applications is the fixture's own.
                got = {check.replace(str(box.root), '') for check in passes(result.stdout)}
                self.assertLessEqual(expected, got, result.stdout + result.stderr)

    def test_macos_absence_checks_fail_without_their_tool(self):
        for line in MACOS_LINES:
            box = self.macos(line)
            for tool, checks in self.macos_checks(line).items():
                with self.subTest(line=line, tool=tool):
                    result = box.run(self.MACOS_STUBS, self.MACOS_TOOLS, drop=tool)
                    out = result.stdout.replace(str(box.root), '')
                    self.assertEqual(checks & passes(out), set(), out)
                    for check in checks:
                        self.assertIn(f'cannot check ({check}):', out)
                    self.assertNotEqual(result.returncode, 0)

    def test_macos_vm_rows_are_not_skipped_when_sysctl_cannot_tell(self):
        # The VM-only rows (the coding agents' verify among them) ran only
        # when sysctl said 1; a sysctl that failed skipped them silently.
        for line in MACOS_LINES:
            box = self.macos(line)
            for change in (dict(drop='sysctl'), dict(stubs={'sysctl': 'exit 1'}), dict(stubs={'sysctl': 'echo maybe'})):
                with self.subTest(line=line, change=change):
                    result = box.run({**self.MACOS_STUBS, **change.get('stubs', {})}, self.MACOS_TOOLS, change.get('drop'))
                    self.assertTrue(any(f.startswith('cannot tell whether this is a VM') for f in fails(result.stdout)), result.stdout)
                    self.assertNotEqual(result.returncode, 0)
            with self.subTest(line=line, sysctl='answers'):
                for answer in ('0', '1'):
                    out = box.run({**self.MACOS_STUBS, 'sysctl': f'echo {answer}'}, self.MACOS_TOOLS).stdout
                    self.assertFalse(any(f.startswith('cannot tell whether this is a VM') for f in fails(out)), out)

    def test_macos_coding_agents_verify_that_fails_silently_is_a_fail(self):
        # A helper that exits nonzero without printing a FAIL row is a FAIL row.
        for line in MACOS_LINES:
            with self.subTest(line=line):
                box = self.macos(line)
                box.write('/guest/coding-agents.lock.json', '{"agents": []}')
                box.write('/guest/coding-agents.py', 'import sys\nsys.exit(3)\n')
                out = box.run(self.MACOS_STUBS, self.MACOS_TOOLS).stdout
                self.assertIn('coding-agents.py verify failed (exit 3)', fails(out), out)

    def test_macos_absence_checks_fail_when_their_tool_fails(self):
        for line in MACOS_LINES:
            box = self.macos(line)
            (box.home / '.local/bin/claude').write_text('#!/bin/sh\nexit 1\n')
            stubs = {**self.MACOS_STUBS, 'crontab': 'echo "crontab: tmp/tmp.X: Permission denied" >&2; exit 1'}
            with self.subTest(line=line):
                out = box.run(stubs, self.MACOS_TOOLS).stdout
                for check in ('claude playwright bare (host parity)', 'npx MCP servers pinned', 'VM has no crontab'):
                    self.assertNotIn(check, passes(out))
                    self.assertIn(f'cannot check ({check}):', out)


if __name__ == '__main__':
    unittest.main()
