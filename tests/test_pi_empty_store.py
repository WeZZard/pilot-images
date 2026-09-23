import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class EmptyStoreTests(unittest.TestCase):
    def test_cleanup_only_exact_empty_store_and_preserves_nonempty(self):
        for image,suffix in [('ubuntu2404','sh'),('macos26','zsh')]:
            text=(ROOT/f'images/{image}/guest/50-agents.{suffix}').read_text()
            script=next(s for s in re.findall("python3 - <<'PY'\\n(.*?)\\nPY",text,re.S) if 'auth.json' in s)
            for data in (b'{}',b'{}\n',b'{"fixture":"nonsecret"}',b'{}\nextra'):
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'.pi/agent/auth.json';path.parent.mkdir(parents=True);path.write_bytes(data)
                    r=subprocess.run([sys.executable,'-c',script],env={**os.environ,'HOME':directory},capture_output=True,text=True)
                    if data in (b'{}',b'{}\n'):
                        self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(path.exists())
                    else:
                        self.assertNotEqual(r.returncode,0);self.assertEqual(path.read_bytes(),data);self.assertNotIn('nonsecret',r.stderr)

if __name__=='__main__':unittest.main()
