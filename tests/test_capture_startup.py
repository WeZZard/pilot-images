import importlib.util
from pathlib import Path
import unittest
import os
import socket
import tempfile

p=Path(__file__).resolve().parents[1]/'applications/cua-driver/capture.py'
s=importlib.util.spec_from_file_location('capture_startup',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class StartupTests(unittest.TestCase):
    def test_waits_for_desktop_without_replaying_capture(self):
        samples=iter([False,False,True]); now=[0]; pauses=[]
        def pause(n):pauses.append(n);now[0]+=n
        m.wait_for_native_x11(check=lambda:next(samples),clock=lambda:now[0],pause=pause,timeout=5)
        self.assertEqual(pauses,[1,1])
    def test_deadline_is_bounded(self):
        now=[0]
        def pause(n):now[0]+=n
        with self.assertRaisesRegex(RuntimeError,'deadline'):
            m.wait_for_native_x11(check=lambda:False,clock=lambda:now[0],pause=pause,timeout=2)
        self.assertEqual(now[0],2)
    def test_daemon_socket_requires_same_user_listening_endpoint(self):
        with tempfile.TemporaryDirectory(prefix='pc-',dir='/tmp') as tmp:
            path=Path(tmp)/'driver.sock'
            self.assertFalse(m.daemon_socket_ready(path))
            path.write_text('not a socket')
            with self.assertRaisesRegex(RuntimeError,'Unix socket'):m.daemon_socket_ready(path)
            path.unlink()
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(str(path))
                self.assertFalse(m.daemon_socket_ready(path))
                server.listen(1)
                self.assertTrue(m.daemon_socket_ready(path))
                connection,_=server.accept();connection.close()
                with self.assertRaisesRegex(RuntimeError,'same-user'):m.daemon_socket_ready(path,os.getuid()+1)

    def test_requires_same_user_local_active_x11(self):
        for kind,active,remote,expected in [('x11','yes','no',True),('wayland','yes','no',False),('x11','no','no',False),('x11','yes','yes',False)]:
            def query(argv,**kwargs):
                return '3 1000 admin seat0 tty2\n4 1001 other seat1 tty3' if argv[1]=='list-sessions' else f'Type={kind}\nActive={active}\nRemote={remote}\n'
            self.assertEqual(m.native_x11_ready(query,1000),expected)

if __name__=='__main__':unittest.main()
