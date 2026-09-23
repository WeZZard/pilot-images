from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class MacRuntimePathTests(unittest.TestCase):
    def test_acceptance_does_not_replace_image_runtime_path(self):
        source=(ROOT/'images/macos26/checks/acceptance.zsh').read_text()
        self.assertNotIn('export PATH=',source)
        self.assertNotIn('pyenv init',source)
        smoke=next(line for line in source.splitlines() if line.startswith('if node -e'))
        self.assertNotIn('2>/dev/null',smoke)
        self.assertIn('headless:true',smoke)
        self.assertIn('timeout:20000',smoke)
        self.assertIn('finally',smoke)

if __name__=='__main__':unittest.main()
