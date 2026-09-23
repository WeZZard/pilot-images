"""Offline validation of pinned archive acquisition and safe extraction."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
import subprocess
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capture_package', ROOT / 'host/capture-package.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def archive(extra=None, machine=183):
    out = io.BytesIO()
    header = b'\x7fELF\x02\x01' + b'\0' * 12 + struct.pack('<H', machine)
    with tarfile.open(fileobj=out, mode='w:gz') as tar:
        for name in sorted(m.REQUIRED):
            data = b'/* fixture header */' if name.endswith('.h') else header
            member = tarfile.TarInfo(name); member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
        if extra:
            tar.addfile(extra, io.BytesIO(b'x' * extra.size))
    return out.getvalue()


class CapturePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.lock = json.loads((ROOT / 'images/ubuntu2404/cua-driver.lock.json').read_text())

    def fixture(self, data):
        lock = dict(self.lock, sha256=hashlib.sha256(data).hexdigest())
        path = self.root / 'lock.json'; path.write_text(json.dumps(lock))
        source = self.root / 'source.tar.gz'; source.write_bytes(data)
        return path, source

    def test_checked_in_lock_uses_exact_official_version(self):
        lock = m.read_lock(ROOT / 'images/ubuntu2404/cua-driver.lock.json')
        self.assertEqual(lock['version'], '0.28.2')
        self.assertEqual(lock['sha256'], '55e8a32839a4ac369a773df4dac87b345bd4567779221ade4a5e39223a45a2e8')
        self.assertIn('Linux preview', lock['upstreamStatus'])

    def test_offline_fetch_and_extract_verify_archive_and_architecture(self):
        lock, source = self.fixture(archive())
        copied = self.root / 'downloaded.tar.gz'
        m.fetch(lock, copied, source)
        self.assertEqual(copied.read_bytes(), source.read_bytes())
        output = self.root / 'files'
        m.extract(lock, copied, output)
        self.assertEqual({p.name for p in output.iterdir()}, m.REQUIRED)
        self.assertEqual((output / 'cua-driver').stat().st_mode & 0o777, 0o755)
        with self.assertRaisesRegex(ValueError, 'new'):
            m.extract(lock, copied, output)

    def test_guest_verifier_is_standalone_without_host_environment_module(self):
        lock, source = self.fixture(archive())
        helper = self.root / 'capture-package.py'
        helper.write_bytes((ROOT / 'host/capture-package.py').read_bytes())
        env = {k: v for k, v in os.environ.items() if not k.startswith('VM_ENVIRONMENT')}
        result = subprocess.run([sys.executable, str(helper), 'extract', '--lock', str(lock), '--archive', str(source), '--output', str(self.root / 'guest-files')], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'guest-files/cua-driver').exists())

    def test_rejects_hash_mismatch_before_creating_output(self):
        lock, source = self.fixture(archive())
        source.write_bytes(source.read_bytes() + b'corruption')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            m.fetch(lock, self.root / 'output', source)
        self.assertFalse((self.root / 'output').exists())

    def test_rejects_non_native_binary(self):
        lock, source = self.fixture(archive(machine=62))
        with self.assertRaisesRegex(ValueError, 'AArch64'):
            m.extract(lock, source, self.root / 'files')
        self.assertFalse((self.root / 'files').exists())

    def test_rejects_traversal_links_duplicates_and_special_files(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE), ('link', tarfile.SYMTYPE), ('device', tarfile.CHRTYPE), ('cua-driver', tarfile.REGTYPE)]:
            with self.subTest(name=name):
                extra = tarfile.TarInfo(name); extra.type = kind
                extra.linkname = '/outside'
                lock, source = self.fixture(archive(extra))
                with self.assertRaises(ValueError):
                    m.extract(lock, source, self.root / 'files')
                self.assertFalse((self.root / 'files').exists())

    def test_rejects_non_official_download_lock(self):
        lock, _ = self.fixture(archive())
        value = json.loads(lock.read_text()); value['url'] = 'https://example.invalid/tool.tar.gz'; lock.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'official'):
            m.read_lock(lock)

    def test_download_redirect_and_output_are_checked_without_execution(self):
        lock, source = self.fixture(archive()); data = source.read_bytes()
        class Response(io.BytesIO):
            def geturl(self): return 'https://release-assets.githubusercontent.com/fixture'
        def opener(request, timeout):
            self.assertEqual(request.full_url, self.lock['url']); return Response(data)
        output = self.root / 'download'
        m.fetch(lock, output, opener=opener)
        self.assertEqual(output.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
