"""Fixture-only GUI session discovery, runner isolation and progress contract."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / 'applications'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gui = load('gui_test', ROOT / 'gui.py')
check = load('check_gui_test', ROOT / 'check.py')


def session(**changes):
    return dict(dict(Id='3', User='1000', Active='yes', Remote='no', Type='x11',
                     Class='user', State='active', Scope='session-3.scope', Display=''), **changes)


def environment(**changes):
    return dict(dict(DISPLAY=':7', XAUTHORITY='/run/user/1000/gdm/Xauthority',
                     DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus',
                     XDG_RUNTIME_DIR='/run/user/1000', XDG_CURRENT_DESKTOP='ubuntu:GNOME',
                     XDG_SESSION_TYPE='x11', DESKTOP_SESSION='ubuntu'), **changes)


def process(**changes):
    return dict(dict(uid=1000, name='gnome-shell', environment=environment(),
                     cgroup='0::/user.slice/user-1000.slice/user@1000.service/session.slice/org.gnome.Shell@x11.service'), **changes)


class GuiContextTests(unittest.TestCase):
    def select(self, sessions=None, processes=None):
        return gui.select_context([session()] if sessions is None else sessions,
                                  [process()] if processes is None else processes, 1000)

    def test_selects_unique_same_user_active_x11_not_ssh_or_greeter(self):
        sessions = [session(), session(Id='4', Type='tty'), session(Id='1', User='120', Class='greeter')]
        self.assertEqual(self.select(sessions), environment())
        self.assertEqual(self.select()['DISPLAY'], ':7')

    def test_accepts_scoped_session_process(self):
        self.assertEqual(self.select(processes=[process(name='gnome-session-b', cgroup='0::/user.slice/session-3.scope')]), environment())

    def test_missing_ambiguous_remote_wayland_inactive_and_foreign_fail(self):
        for sessions in ([], [session(), session(Id='4')], [session(Remote='yes')],
                         [session(Type='wayland')], [session(Active='no')], [session(User='1001')],
                         [session(), session(Id='4', Type='wayland')]):
            with self.subTest(sessions=sessions), self.assertRaises(gui.ContextError):
                self.select(sessions)

    def test_unknown_or_foreign_process_cannot_supply_context(self):
        for processes in ([], [process(uid=1001)], [process(name='ssh')],
                          [process(cgroup='0::/unrelated')],
                          [process(environment=environment(XDG_SESSION_ID='99'))],
                          [process(environment={'DISPLAY': ':0'})]):
            with self.subTest(processes=processes), self.assertRaises(gui.ContextError):
                self.select(processes=processes)

    def test_conflicting_contexts_fail_and_duplicates_are_allowed(self):
        self.assertEqual(self.select(processes=[process(), process()]), environment())
        with self.assertRaises(gui.ContextError):
            self.select(processes=[process(), process(environment=environment(DISPLAY=':8'))])

    def test_rejects_forwarded_display_remote_bus_and_other_runtime(self):
        for change in ({'DISPLAY': 'localhost:10'}, {'DBUS_SESSION_BUS_ADDRESS': 'tcp:host=evil'},
                       {'XDG_RUNTIME_DIR': '/run/user/1001'}, {'XAUTHORITY': 'relative'}):
            with self.subTest(change=change), self.assertRaises(gui.ContextError):
                self.select(processes=[process(environment=environment(**change))])
        with self.assertRaises(gui.ContextError):
            self.select(sessions=[session(Display=':99')])

    def test_only_allowlisted_environment_leaves_parser_and_selector(self):
        raw = b'DISPLAY=:7\0SECRET_TOKEN=super-secret\0PATH=/evil\0SSH_AUTH_SOCK=/secret\0'
        self.assertEqual(gui.gui_environment(raw), {'DISPLAY': ':7'})
        self.assertEqual(self.select(processes=[process(environment={**environment(), 'SECRET_TOKEN': 'super-secret'})]), environment())

    def test_failed_query_never_exposes_stderr_or_repairs(self):
        with patch.object(gui.subprocess, 'run', return_value=Mock(returncode=1, stderr='SECRET', stdout='')) as run:
            with self.assertRaisesRegex(gui.ContextError, '^loginctl session query failed$'):
                gui.resolve_context()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['loginctl', 'list-sessions', '--no-legend', '--no-pager'])

    def test_gui_startup_merges_only_desktop_context(self):
        fake = Mock(pid=99999)
        fake.wait.side_effect = [subprocess.TimeoutExpired('app', 1), 0]
        with patch.object(check.sys, 'platform', 'linux'), patch.object(check, 'gui_module', return_value=gui), \
                patch.object(gui, 'resolve_context', return_value=environment()), \
                patch.dict(check.os.environ, {'DISPLAY': ':99', 'WAYLAND_DISPLAY': 'stale', 'PATH': '/safe'}, clear=True), \
                patch.object(check.subprocess, 'Popen', return_value=fake) as popen, patch.object(check.os, 'killpg'):
            result = check.command(['/app'], 1, startup=True)
        self.assertEqual(result['status'], 'pass')
        env = popen.call_args.kwargs['env']
        self.assertEqual(env['DISPLAY'], ':7')
        self.assertEqual(env['PATH'], '/safe')
        self.assertNotIn('WAYLAND_DISPLAY', env)
        self.assertNotIn('XAUTHORITY', json.dumps(result))
        self.assertNotIn('environment', result)

    def test_unknown_gui_context_fails_visibly_without_launch_or_repair(self):
        with patch.object(check.sys, 'platform', 'linux'), patch.object(check, 'gui_module', return_value=gui), \
                patch.object(gui, 'resolve_context', side_effect=gui.ContextError('desktop process context is missing or ambiguous')), \
                patch.object(check.subprocess, 'Popen') as popen:
            result = check.command(['/app'], 1, startup=True)
        popen.assert_not_called()
        self.assertEqual(result['status'], 'fail')
        self.assertIn('GUI context unavailable', result['detail'])

    def test_headless_cli_and_macos_do_not_discover_or_change_desktop(self):
        for platform, startup, args in [('linux', False, ['--version']),
                ('linux', True, ['--headless']), ('linux', True, ['--headless=new']),
                ('linux', True, ['-headless']), ('darwin', True, [])]:
            fake = Mock(pid=99999)
            fake.wait.return_value = 0
            with self.subTest(platform=platform, args=args), patch.object(check.sys, 'platform', platform), \
                    patch.object(check, 'gui_module') as loader, \
                    patch.dict(check.os.environ, {'DISPLAY': ':99'}, clear=True), \
                    patch.object(check.subprocess, 'Popen', return_value=fake) as popen, patch.object(check.os, 'killpg'):
                check.command(['/app', *args], 1, startup=startup)
                loader.assert_not_called()
                self.assertEqual(popen.call_args.kwargs['env']['DISPLAY'], ':99')

    def test_staged_import_and_digest_include_gui(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('check.py', 'gui.py'):
                shutil.copy(ROOT / name, root / name)
            staged = load('staged_check', root / 'check.py')
            self.assertEqual(Path(staged.gui_module().__file__), root / 'gui.py')
            selection = {'plans': []}
            before = staged.plan_digest(root, selection)
            (root / 'gui.py').write_text((root / 'gui.py').read_text() + '\n# changed\n')
            self.assertNotEqual(before, staged.plan_digest(root, selection))

    def test_progress_opt_in_and_final_status_for_installed_unsupported(self):
        selection = dict(schemaVersion=1, image='fixture', plans=['demo'], dependencies={})
        inventory = dict(os='linux', architecture='arm64', applications=[{'id': 'demo'}])
        result = dict(id='demo', inventoryIds=['demo'], baseline=[], extensions=[], status='not-applicable')
        with patch.object(check, 'expected_plan_inventory_ids', return_value={'demo': ['demo']}), \
                patch.object(check, 'test_application', side_effect=lambda *args: copy.deepcopy(result)), \
                patch.object(check, 'plan_digest', return_value='hash'), patch.object(check.sys, 'stderr', new_callable=io.StringIO) as stderr:
            check.run(ROOT, selection, inventory, 'build')
            self.assertEqual(stderr.getvalue(), '')
            progress = Mock()
            report = check.run(ROOT, selection, inventory, 'build', progress=progress)
            progress.assert_called_once_with('demo', 'fail')
            self.assertEqual(report['applications'][0]['status'], 'fail')

    def test_native_progress_reports_each_completed_application(self):
        selection = dict(schemaVersion=1, image='fixture', plans=[], dependencies={}, sources=['dpkg'])
        inventory = dict(os='linux', architecture='arm64', applications=[{'id': 'dpkg:a'}, {'id': 'dpkg:b'}])
        native = Mock(SOURCES={'dpkg'})
        native.baseline.side_effect = lambda record, *args, **kwargs: dict(
            id='native:' + record['id'], inventoryIds=[record['id']], baseline=[], extensions=[], status='pass')
        mapping = {'native:' + app['id']: [app['id']] for app in inventory['applications']}
        progress = Mock()
        with patch.object(check, 'expected_plan_inventory_ids', return_value=mapping), \
                patch.object(check, 'native_module', return_value=native), \
                patch.object(check, 'plan_digest', return_value='hash'):
            check.run(ROOT, selection, inventory, 'build', progress=progress)
        self.assertEqual([call.args for call in progress.call_args_list],
                         [('native:dpkg:a', 'pass'), ('native:dpkg:b', 'pass')])

    def test_cli_progress_is_names_status_only_stderr_and_flushed(self):
        with patch('builtins.print') as output:
            check.cli_progress('native:dpkg:calculator\nunsafe', 'pass')
        output.assert_called_once_with('"native:dpkg:calculator\\nunsafe" pass', file=check.sys.stderr, flush=True)


if __name__ == '__main__':
    unittest.main()
