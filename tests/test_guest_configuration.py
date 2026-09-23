"""Guest configuration fixtures with no sudo, package manager, or VM effects."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def run_phase(self, name):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root=Path(temporary.name).resolve(); bin_dir=root/'bin';bin_dir.mkdir()
        source=REPO/'images/ubuntu2404/guest'/name
        script=root/name; script.write_text(source.read_text().replace('/etc/',str(root/'etc')+'/'))
        (root/'lib.sh').write_text('set -euo pipefail\nglog(){ :; }\napt_q(){ :; }\n')
        for tool,text in {'sudo':'exec "$@"','systemctl':'exit 0','snap':'exit 0','dconf':'printf "dconf %s\\n" "$*" >> "$FIXTURE_LOG"','sync':'printf "sync\\n" >> "$FIXTURE_LOG"'}.items():
            p=bin_dir/tool;p.write_text('#!/bin/sh\n'+text+'\n');p.chmod(0o755)
        profile=root/'etc/dconf/profile/user';profile.parent.mkdir(parents=True);profile.touch()
        env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],'FIXTURE_LOG':str(root/'calls')}
        result=subprocess.run(['/bin/bash',str(script)],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return root

    def test_empty_dconf_profile_is_repaired_and_writes_are_flushed(self):
        root=self.run_phase('30-desktop.sh')
        self.assertEqual((root/'etc/dconf/profile/user').read_text(),'user-db:user\nsystem-db:local\n')
        settings=(root/'etc/dconf/db/local.d/00-pilot-desktop').read_text()
        self.assertIn('scaling-factor=uint32 2',settings)
        self.assertIn('lock-enabled=false',settings)
        self.assertEqual((root/'calls').read_text(),'dconf update\nsync\n')

    def test_browser_policy_is_valid_json_and_flushed(self):
        root=self.run_phase('20-browsers.sh')
        policy=json.loads((root/'etc/chromium-browser/policies/managed/extensions.json').read_text())
        self.assertTrue(policy['ExtensionInstallForcelist'][0].startswith('lfmkphfpdbjijhpomgecfikhfohaoine;'))
        self.assertEqual((root/'calls').read_text(),'sync\n')

    def test_browser_cache_check_ignores_runtime_state_but_detects_new_revision(self):
        source=(REPO/'images/ubuntu2404/checks/acceptance.sh').read_text()
        function=re.search(r'  cache_listing\(\) \{.*?\}',source).group(0)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('chromium-1243','firefox-1542','ffmpeg-1011'): (root/name).mkdir()
            def listing():
                return subprocess.check_output(['/bin/bash','-c',function+'; cache_listing'],env={**os.environ,'PW_CACHE':str(root)},text=True)
            before=listing();(root/'b').mkdir();(root/'daemon').mkdir();(root/'cli-update-check.json').write_text('{}')
            self.assertEqual(listing(),before)
            (root/'chromium-9999').mkdir();self.assertNotEqual(listing(),before)


if __name__=='__main__': unittest.main()
