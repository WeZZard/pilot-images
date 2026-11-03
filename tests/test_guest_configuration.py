"""Guest configuration fixtures with no sudo, package manager, or VM effects."""
import isolation  # first: the tests keep nothing of the shell's environment
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[1]
#: The system tools a guest script run here may use; any other tool is a stub or fails.
GUEST_TOOLS=('dirname','mkdir','tee','grep','python3','awk','sort','id','chmod','find','ls')


class ConfigurationTests(unittest.TestCase):
    def run_phase(self, name, prepare=None):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root=Path(temporary.name).resolve()
        source=REPO/'images/ubuntu2404/guest'/name
        script=root/name; script.write_text(source.read_text().replace('/etc/',str(root/'etc')+'/'))
        (root/'lib.sh').write_text('set -euo pipefail\nglog(){ :; }\napt_q(){ :; }\n')
        profile=root/'etc/dconf/profile/user';profile.parent.mkdir(parents=True);profile.touch()
        if prepare: prepare(root)
        stubs={'sudo':'exec "$@"','systemctl':'exit 0','snap':'exit 0','dconf':'printf "dconf %s\\n" "$*" >> "$FIXTURE_LOG"','sync':'printf "sync\\n" >> "$FIXTURE_LOG"'}
        env=isolation.guest_environment(root,stubs,GUEST_TOOLS,FIXTURE_LOG=root/'calls')
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

    def test_login_keyring_is_passwordless_empty_and_unlocked_at_login(self):
        root=self.run_phase('30-desktop.sh')
        keyrings=root/'home/.local/share/keyrings'
        login=(keyrings/'login.keyring').read_text()
        self.assertEqual(re.findall(r'^\[.*\]$',login,re.M),['[keyring]'])
        self.assertIn('display-name=Login\n',login)
        self.assertEqual((keyrings/'default').read_text(),'login')
        self.assertEqual(keyrings.stat().st_mode&0o777,0o700)
        for name in ('login.keyring','default'):
            self.assertEqual((keyrings/name).stat().st_mode&0o777,0o600)
        entry=(root/'etc/xdg/autostart/pilot-keyring-unlock.desktop').read_text()
        self.assertIn('Exec=busctl --user call org.freedesktop.secrets /org/freedesktop/secrets '
                      'org.freedesktop.Secret.Service Unlock ao 1 /org/freedesktop/secrets/collection/login\n',entry)

    def test_existing_login_keyring_is_kept(self):
        def existing(root):
            keyrings=root/'home/.local/share/keyrings'; keyrings.mkdir(parents=True)
            (keyrings/'login.keyring').write_text('kept\n'); (keyrings/'default').write_text('login')
        root=self.run_phase('30-desktop.sh',existing)
        self.assertEqual((root/'home/.local/share/keyrings/login.keyring').read_text(),'kept\n')

    def test_desktop_session_selects_local_active_graphical_session_of_the_user(self):
        source=(REPO/'images/ubuntu2404/checks/acceptance.sh').read_text()
        function=re.search(r'^desktop_session\(\) \{.*?^\}',source,re.M|re.S).group(0)
        user=subprocess.check_output(['/usr/bin/id','-un'],text=True,env=isolation.environment()).strip()
        def session(sid,**changes):
            props=dict(Name=user,Type='x11',Remote='no',Active='yes',Class='user'); props.update(changes)
            return sid,props
        cases=(([session('3')],'3'),
               ([session('1',Type='tty',Remote='yes'),session('7',Type='wayland')],'7'),
               ([session('2',Class='greeter',Name='gdm'),session('4')],'4'),
               ([session('1',Type='tty')],''),([session('3',Remote='yes')],''),
               ([session('3',Active='no')],''),([session('3',Name='someone-else')],''),
               ([session('3',Class='greeter')],''),([],''))
        for sessions,expected in cases:
            with self.subTest(sessions=sessions), tempfile.TemporaryDirectory() as directory:
                table={sid:'\n'.join(f'{k}={v}' for k,v in props.items()) for sid,props in sessions}
                listing=''.join(f'{sid} 1000 {props["Name"]} - - active no -\n' for sid,props in sessions)
                script=['#!/bin/sh','if [ "$1" = list-sessions ]; then printf %s "$LISTING"; exit 0; fi','case "$2" in']
                script+=[f"  {sid}) printf '%s\\n' '{text}' ;;" for sid,text in table.items()]
                script+=['esac']
                env=isolation.guest_environment(directory,{'loginctl':'\n'.join(script[1:])},GUEST_TOOLS,LISTING=listing)
                out=subprocess.check_output(['/bin/bash','-c',function+'; desktop_session'],env=env,text=True)
                self.assertEqual(out.strip(),expected)

    def test_no_secrets_fails_on_a_login_keyring_item(self):
        script=REPO/'images/ubuntu2404/checks/no-secrets.sh'
        header='[keyring]\ndisplay-name=Login\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n'
        for body,extra,failed in (('',None,False),('\n[2]\nitem-type=0\nsecret=x\n',None,True),('','other.keyring',True)):
            with self.subTest(body=body,extra=extra), tempfile.TemporaryDirectory() as directory:
                keyrings=Path(directory)/'.local/share/keyrings'; keyrings.mkdir(parents=True)
                (keyrings/'login.keyring').write_text(header+body); (keyrings/'default').write_text('login')
                if extra: (keyrings/extra).write_text('x')
                result=subprocess.run(['/bin/bash',str(script)],env=isolation.guest_environment(directory,{},GUEST_TOOLS,HOME=directory),capture_output=True,text=True)
                self.assertEqual(result.returncode!=0,failed,result.stdout)
                self.assertEqual('FAIL  login keyring holds items' in result.stdout,bool(body))

    def test_browser_policy_is_valid_json_and_flushed(self):
        root=self.run_phase('20-browsers.sh')
        policy=json.loads((root/'etc/chromium-browser/policies/managed/extensions.json').read_text())
        self.assertTrue(policy['ExtensionInstallForcelist'][0].startswith('lfmkphfpdbjijhpomgecfikhfohaoine;'))
        self.assertEqual((root/'calls').read_text(),'sync\n')

    def test_browser_cache_check_ignores_runtime_state_but_detects_new_revision(self):
        source=(REPO/'images/ubuntu2404/checks/acceptance.sh').read_text()
        function=re.search(r'  cache_listing\(\) \{.*?\}',source).group(0)
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as scratch:
            root=Path(directory)
            for name in ('chromium-1243','firefox-1542','ffmpeg-1011'): (root/name).mkdir()
            def listing():
                return subprocess.check_output(['/bin/bash','-c',function+'; cache_listing'],env=isolation.guest_environment(scratch,{},GUEST_TOOLS,PW_CACHE=root),text=True)
            before=listing();(root/'b').mkdir();(root/'daemon').mkdir();(root/'cli-update-check.json').write_text('{}')
            self.assertEqual(listing(),before)
            (root/'chromium-9999').mkdir();self.assertNotEqual(listing(),before)


if __name__=='__main__': unittest.main()
