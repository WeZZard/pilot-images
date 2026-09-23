"""Password bootstrap transport reuse fixtures; never connects to a guest."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class TransportTests(unittest.TestCase):
    def test_ssh_and_scp_reuse_private_short_control_path_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); bin_dir = root / 'bin'; bin_dir.mkdir()
            log = root / 'calls.jsonl'
            (bin_dir / 'sshpass').write_text('#!/bin/sh\nshift 2\nexec "$@"\n')
            fake = '''#!%s
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
control=next(a.split('=',1)[1] for a in args if a.startswith('ControlPath='))
parent=Path(control).parent
with open(os.environ['FIXTURE_LOG'],'a') as f:f.write(json.dumps(dict(tool=Path(sys.argv[0]).name,args=args,control=control,mode=parent.stat().st_mode&0o777))+'\\n')
''' % sys.executable
            for name in ('ssh', 'scp'):
                (bin_dir / name).write_text(fake)
            for path in bin_dir.iterdir(): path.chmod(0o755)
            env = {k:v for k,v in os.environ.items() if not k.startswith('VM_ENVIRONMENT')}
            env.update(PATH=str(bin_dir)+os.pathsep+os.environ['PATH'], FIXTURE_LOG=str(log))
            command='source "$1"; GUEST_USER=fixture; GUEST_PASS=factory; vssh 127.0.0.2 true; vssh 127.0.0.2 command; vscp 127.0.0.2 /fixture/source /fixture/dest'
            result=subprocess.run(['/bin/zsh','-c',command,'fixture',str(REPO/'host/lib/common.zsh')],env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            calls=[json.loads(row) for row in log.read_text().splitlines()]
            self.assertEqual([c['tool'] for c in calls[:3]],['ssh','ssh','scp'])
            self.assertEqual(len({c['control'] for c in calls}),1)
            self.assertTrue(all(c['mode']==0o700 for c in calls))
            self.assertLess(len(calls[0]['control'].replace('%C','f'*40)),104)
            self.assertTrue(any('-O' in c['args'] and 'exit' in c['args'] for c in calls))
            self.assertFalse(Path(calls[0]['control']).parent.exists())

    def test_xcode_archive_follows_only_top_level_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); app=root/'Xcode-26.6.app'; (app/'Contents').mkdir(parents=True)
            (app/'Contents/file').write_text('fixture')
            (app/'Contents/link').symlink_to('file')
            staging=root/'staging'; staging.mkdir(); (staging/'Xcode.app').symlink_to(app)
            archive=root/'xcode.tgz'
            subprocess.run(['/usr/bin/tar','-H','-C',str(staging),'-czf',str(archive),'Xcode.app'],check=True)
            with tarfile.open(archive) as tar:
                self.assertTrue(tar.getmember('Xcode.app').isdir())
                self.assertTrue(tar.getmember('Xcode.app/Contents/link').issym())
                self.assertEqual(tar.extractfile('Xcode.app/Contents/file').read(),b'fixture')


if __name__=='__main__': unittest.main()
