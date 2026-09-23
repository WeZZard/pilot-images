"""Fixture-only host publication tests: no collection, SSH, Tart or real images."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pilot_inventory_host', REPO / 'host/inventory.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class HostInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vms = self.root / 'vms'
        self.work = self.vms / 'work'
        self.work.mkdir(parents=True)
        for name in ('disk.img', 'config.json', 'nvram.bin'):
            (self.work / name).write_bytes(b'fixture')
        self.raw = self.root / 'original.json'
        self.data = dict(schemaVersion=1, os='macos', architecture='arm64',
                         collectedAt='2026-09-01T00:00:00Z', sources=[dict(id='bundles', status='available', roots=['/Applications'])],
                         applications=[dict(id='editor', name='Editor', aliases=[], version='1')])
        self.raw.write_text(json.dumps(self.data))
        self.output = host.state_directory(self.vms, {'PILOT_IMAGES_STATE_DIR': str(self.root / 'state')}) / 'base/macos26.json'
        self.portable = self.root / 'images/macos26/applications.json'

    def bind(self, **kwargs):
        return host.bind(self.raw, self.output, self.vms, 'work', 'macos26', 'macos', portable=self.portable, mode='work', evidence_id='fixture', collector=self.raw, aliases=self.raw, **kwargs)

    def test_wire_shape_and_original_preserved(self):
        original = self.raw.read_bytes()
        result = self.bind()
        self.assertEqual(set(result), {'schemaVersion', 'image', 'base', 'inventorySha256'})
        self.assertEqual(set(result['base']), {'base_vm', 'path', 'files'})
        for values in result['base']['files'].values():
            self.assertEqual(set(values), {'st_dev', 'st_ino', 'st_size', 'st_mtime_ns'})
        host.verify(result, self.vms, 'work', 'macos26', 'macos', self.portable)
        self.assertEqual(self.raw.read_bytes(), original)

    def test_changed_portable_bytes_cannot_verify(self):
        doc = self.bind()
        self.portable.write_bytes(self.portable.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            host.verify(doc, self.vms, 'work', 'macos26', 'macos', self.portable)

    def test_portable_precedes_association_and_failure_invalidates(self):
        real = host.atomic_write
        calls = []
        def fail(output, raw):
            calls.append(output)
            if output == self.output:
                raise OSError('fixture publication failure')
            real(output, raw)
        with patch.object(host, 'atomic_write', side_effect=fail):
            with self.assertRaises(OSError):
                self.bind()
        self.assertEqual(calls, [self.portable, self.output])
        self.assertFalse(self.output.exists())
        self.assertTrue(self.portable.exists())

    def test_changed_work_cannot_promote(self):
        doc = self.bind()
        (self.work / 'disk.img').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            host.verify(doc, self.vms, 'work', 'macos26', 'macos', self.portable)

    def test_rename_carries_identity_and_inventory(self):
        self.bind()
        saved = self.root / 'work.json'
        saved.write_bytes(self.output.read_bytes())
        self.work.rename(self.vms / 'base')
        result = host.bind(self.portable, self.output, self.vms, 'base', 'macos26', 'macos', saved, portable=self.portable)
        self.assertEqual(result['base']['base_vm'], 'base')
        self.assertEqual(result['base']['path'], str(self.vms / 'base'))
        host.verify(result, self.vms, 'base', 'macos26', 'macos', self.portable)

    def test_mutation_after_rename_removes_old_publication(self):
        self.bind()
        saved = self.root / 'work.json'
        saved.write_bytes(self.output.read_bytes())
        self.work.rename(self.vms / 'base')
        (self.vms / 'base/disk.img').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            host.bind(self.portable, self.output, self.vms, 'base', 'macos26', 'macos', saved, portable=self.portable)
        self.assertFalse(self.output.exists())

    def test_pre_and_post_publication_change_fail_closed(self):
        real = host.fingerprint
        for changed_call in (2, 3):
            count = 0
            def fingerprint(*args):
                nonlocal count
                count += 1
                result = real(*args)
                if count == changed_call:
                    result['files']['disk.img']['st_size'] += 1
                return result
            with patch.object(host, 'fingerprint', side_effect=fingerprint):
                with self.assertRaises(ValueError):
                    self.bind()
            self.assertFalse(self.output.exists())

    def test_invalid_raw_invalidates_prior_output(self):
        self.bind()
        self.raw.write_text('{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaises(ValueError):
            self.bind()
        self.assertFalse(self.output.exists())

    def test_symlinks_and_required_files(self):
        (self.work / 'nvram.bin').unlink()
        with self.assertRaises(FileNotFoundError):
            host.fingerprint(self.vms, 'work', 'macos')
        self.assertEqual(len(host.fingerprint(self.vms, 'work', 'linux')['files']), 2)
        (self.work / 'nvram.bin').symlink_to(self.raw)
        with self.assertRaises(ValueError):
            host.fingerprint(self.vms, 'work', 'linux')
        alias = self.root / 'alias'
        alias.symlink_to(self.vms, target_is_directory=True)
        with self.assertRaises(ValueError):
            host.fingerprint(alias, 'work', 'macos')

    def test_inventory_validation(self):
        for change in ({'schemaVersion': True}, {'architecture': 'unknown'}, {'extra': 1}, {'sources': []}):
            with self.assertRaises(ValueError):
                host.validate(dict(self.data, **change), 'macos')
        with self.assertRaises(ValueError):
            host.validate(self.data, 'linux')

    def test_backend_compatibility_when_sibling_available(self):
        # Test-only optional consumer import; production helper is standalone.
        backend_path = REPO.parent / 'vm-service/bin/application_catalog.py'
        if not backend_path.is_file():
            self.skipTest('optional sibling backend not checked out')
        spec = importlib.util.spec_from_file_location('catalog_compat', backend_path)
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        doc = self.bind()
        self.assertEqual(doc['base'], backend.fingerprint_base(self.vms, 'work', 'macos'))
        self.assertEqual(host.read_json(self.portable)['inventory'], backend.validate_inventory(self.data))
        with patch.dict(os.environ, {'PILOT_IMAGES_STATE_DIR': str(self.root / 'state')}):
            self.assertEqual(backend.association_path(self.vms, 'macos26'), self.output)
            catalog = backend.load_catalog(self.root, {'macos26': {'base_vm': 'work', 'kind': 'macos'}}, base_root=self.vms)
        self.assertEqual(catalog['images'][0]['applications'], self.data['applications'])

    def test_backend_state_paths_match_all_configuration_branches(self):
        backend_path = REPO.parent / 'vm-service/bin/application_catalog.py'
        if not backend_path.is_file():
            self.skipTest('optional sibling backend not checked out')
        spec = importlib.util.spec_from_file_location('catalog_path_compat', backend_path)
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        alias = self.root / 'store-alias'
        alias.symlink_to(self.vms, target_is_directory=True)
        environments = [
            {'HOME': str(self.root)},
            {'HOME': str(self.root), 'XDG_STATE_HOME': str(self.root / 'xdg')},
            {'HOME': str(self.root), 'XDG_STATE_HOME': str(self.root / 'xdg'), 'PILOT_IMAGES_STATE_DIR': str(self.root / 'override')},
            {'HOME': str(self.root), 'XDG_STATE_HOME': '', 'PILOT_IMAGES_STATE_DIR': ''},
        ]
        for env in environments:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                for root in (self.vms, alias, self.root / 'unicode-图像'):
                    self.assertEqual(backend.association_path(root, 'macos26'), host.state_directory(root) / 'base/macos26.json')
                self.assertEqual(backend.association_path(alias, 'macos26'), backend.association_path(self.vms, 'macos26'))
        self.assertFalse((self.root / 'override').exists(), 'path discovery must not publish state')

    def test_shell_integration_order_without_execution(self):
        build = (REPO / 'host/build-base.zsh').read_text()
        self.assertLess(build.index('inventory_invalidate "$WORK_INVENTORY"'), build.index('vm_start_headless'))
        self.assertLess(build.index('inventory_extract "$IP"'), build.index('tart stop "$WORK_VM"'))
        promote = (REPO / 'host/promote-base.zsh').read_text()
        self.assertLess(promote.index('inventory_verify_work'), promote.index('tart rename "$WORK_VM"'))
        refresh = (REPO / 'host/refresh-base.zsh').read_text()
        self.assertLess(refresh.index('inventory_invalidate "$BASE_INVENTORY"'), refresh.index('vm_start_headless'))
        self.assertLess(refresh.index('inventory_extract "$IP"'), refresh.index('tart stop "$BASE_VM"'))


if __name__ == '__main__':
    unittest.main()
