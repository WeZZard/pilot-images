"""Fixture-only tests: all command execution and discovery are injected."""
import datetime
import importlib.util
import json
import pathlib
import plistlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('inventory_collect', ROOT / 'inventory/collect.py')
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
MAPPINGS = json.loads((ROOT / 'inventory/aliases.json').read_text())


class CollectorTests(unittest.TestCase):
    def setUp(self):
        # An accidental real inventory command is a test failure.
        self.guard = patch.object(c.subprocess, 'run', side_effect=AssertionError('host subprocess forbidden'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_dpkg_installed_only(self):
        result = c.parse_dpkg('installed\tfoo:arm64\t1.2\nconfig-files\tremoved\t1\n')
        self.assertEqual(result, [c.record('dpkg', 'foo:arm64', 'foo:arm64', '1.2')])
        for raw in ['foo', 'weird\tfoo\t1', 'installed\tfoo\t']:
            with self.assertRaises(c.ExtractionError):
                c.parse_dpkg(raw)

    def test_snap(self):
        result = c.parse_snap('Name Version Rev Tracking Publisher Notes\nfirefox 140.0 12 latest/stable mozilla** -\n')
        self.assertEqual(c.normalize(result, MAPPINGS)[0]['id'], 'firefox')
        for raw in ['', 'bad header', 'Name Version Rev Tracking Publisher Notes\nfirefox']:
            with self.assertRaises(c.ExtractionError):
                c.parse_snap(raw)

    def test_brew_installed_not_available(self):
        fixture = {'formulae': [{'name': 'node', 'versions': {'stable': '99'},
                                  'installed': [{'version': '22'}]},
                                 {'name': 'absent', 'installed': []}],
                   'casks': [{'token': 'chrome', 'version': '999', 'installed': '140'},
                             {'token': 'absent', 'installed': None}]}
        self.assertEqual([a['version'] for a in c.parse_brew(json.dumps(fixture))], ['22', '140'])
        for raw in ['{}', '{', '{"formulae":[],"casks":[{"token":"a","installed":[]}]}',
                    '{"formulae":[{"name":"a","installed":[{}]}],"casks":[]}']:
            with self.assertRaises(c.ExtractionError):
                c.parse_brew(raw)

    def test_npm(self):
        result = c.parse_npm('{"dependencies":{"@scope/pkg":{"version":"2"},"unknown":{}}}')
        self.assertEqual(result[0]['id'], 'npm:@scope/pkg')
        self.assertIsNone(result[1]['version'])
        self.assertEqual(c.parse_npm('{}'), [])
        for raw in ['[]', '{', '{"dependencies":[]}', '{"error":{ "code":"bad"}}',
                    '{"dependencies":{"foo":{"missing":true}}}', '{"a":1,"a":2}']:
            with self.assertRaises(c.ExtractionError):
                c.parse_npm(raw)

    def test_bundles_utilities_no_nested_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = [pathlib.Path(tmp) / 'Applications', pathlib.Path(tmp) / 'System/Applications']
            for root in roots:
                root.mkdir(parents=True)
            def app(path, identifier, **extra):
                contents = path / 'Contents'
                contents.mkdir(parents=True)
                (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier, **extra}))
            app(roots[0] / 'Firefox.app', 'org.mozilla.firefox', CFBundleShortVersionString='140')
            app(roots[0] / 'Firefox.app/Contents/Helper.app', 'ignored')
            app(roots[1] / 'Utilities/Tool.app', 'tool', CFBundleVersion='3')
            apps = c.normalize(c.scan_bundles(roots), MAPPINGS)
            self.assertEqual([a['id'] for a in apps], ['bundle:tool', 'firefox'])
            self.assertEqual([a['version'] for a in apps], ['3', '140'])
            (roots[0] / 'Firefox.app/Contents/Info.plist').write_bytes(b'bad plist')
            with self.assertRaises(c.ExtractionError):
                c.scan_bundles(roots)
        with self.assertRaises(c.ExtractionError):
            c.scan_bundles([pathlib.Path(tmp) / 'missing'])

    def test_mapping_does_not_invent_and_conflicts(self):
        self.assertEqual(c.normalize([], MAPPINGS), [])
        a = c.record('snap', 'firefox', 'firefox', '140')
        b = c.record('bundle', 'org.mozilla.firefox', 'Firefox', '140')
        self.assertEqual(len(c.normalize([a, b, a], MAPPINGS)), 1)
        for version in ['141', None]:
            with self.assertRaises(c.ExtractionError):
                c.normalize([a, dict(b, version=version)], MAPPINGS)
        self.assertEqual(len(c.normalize([dict(a, version=None), dict(b, version=None)], MAPPINGS)), 1)
        self.assertEqual(c.normalize([c.record('snap', 'unmapped', 'unmapped', None)], MAPPINGS)[0]['id'], 'snap:unmapped')

    def test_collect_provenance_and_failures(self):
        calls = []
        def runner(argv):
            calls.append(argv)
            return 'installed\tfoo\t1\n'
        now = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
        result = c.collect('linux', 'arm64', runner=runner,
                           which=lambda name: '/bin/dpkg-query' if name == 'dpkg-query' else None,
                           now=now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['collectedAt'], '2026-01-02T00:00:00Z')
        self.assertEqual(result['sources'][1:], [{'id': 'snap', 'status': 'unavailable'},
                                                {'id': 'npm', 'status': 'unavailable'}])
        with self.assertRaises(c.ExtractionError):
            c.collect('linux', 'arm64', runner=runner, which=lambda _: None)
        for response in [RuntimeError('failed command'), 'malformed output']:
            def broken(argv):
                if argv[0] == 'dpkg-query':
                    return ''
                if isinstance(response, Exception):
                    raise response
                return response
            with self.assertRaises(c.ExtractionError):
                c.collect('linux', 'arm64', runner=broken, which=lambda name: name)
        with tempfile.TemporaryDirectory() as tmp:
            mac = c.collect('macos', 'x86_64', runner=runner, which=lambda _: None, roots=[tmp])
            self.assertEqual(mac['applications'], [])
            self.assertEqual(mac['sources'][0]['id'], 'bundles')
        with self.assertRaises(c.ExtractionError):
            c.collect('windows', 'arm64', runner=runner, which=lambda _: None)

    def test_field_and_count_bounds(self):
        c.record('s', 'i' * 126, 'n' * 256, 'v' * 256)
        for args in [('s', 'i' * 127, 'n', None), ('s', 'i', 'n' * 257, None),
                     ('s', 'i', 'n', 'v' * 257), ('s', 'i', 'n', 1)]:
            with self.assertRaises(c.ExtractionError):
                c.record(*args)
        mapping = {'s:a': {'id': 'a', 'name': 'a', 'aliases': ['x'] * 16}}
        self.assertEqual(c.normalize([], mapping), [])
        for aliases in [['x'] * 17, ['x' * 257], 'wrong']:
            with self.assertRaises(c.ExtractionError):
                c.normalize([], {'s:a': dict(mapping['s:a'], aliases=aliases)})
        apps = [c.record('s', str(i), 'n', None) for i in range(20001)]
        self.assertEqual(len(c.normalize(apps[:-1], {})), 20000)
        with self.assertRaises(c.ExtractionError):
            c.normalize(apps, {})

    def test_output_utf8_bound(self):
        overhead = len(c.encode({'x': ''}))
        self.assertEqual(len(c.encode({'x': 'a' * (c.MAX_BYTES - overhead)})), c.MAX_BYTES)
        with self.assertRaises(c.ExtractionError):
            c.encode({'x': 'a' * (c.MAX_BYTES - overhead + 1)})
        with self.assertRaises(c.ExtractionError):
            c.encode({'x': '界' * (c.MAX_BYTES // 2)})


if __name__ == '__main__':
    unittest.main()
