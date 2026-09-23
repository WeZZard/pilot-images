#!/usr/bin/env python3
"""Persistent-inode, per-Tart-home/line advisory lock; stdlib macOS/Linux.

Exec, rather than supervise, the lifecycle shell. The inheritable descriptor is
also retained by ordinary shell children: killing the shell cannot unlock while
an inherited child still runs. Never unlink lock files or take over by PID/age.
"""
import fcntl
import os
from pathlib import Path
import re
import stat
import sys

FD_ENV = 'PILOT_MAINTENANCE_FD'


def main():
    from environment import initialize
    initialize()
    mode, line, *command = sys.argv[1:]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', line):
        raise ValueError('invalid maintenance line')
    root = Path(os.environ.get('TART_HOME', str(Path.home() / '.tart'))).resolve()
    directory = root / 'maintenance-locks'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise ValueError('unsafe maintenance lock directory')
    path = directory / (line + '.lock')
    if mode == 'check':
        fd = int(os.environ[FD_ENV])
    elif mode == 'acquire':
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    else:
        raise ValueError('unknown mode')
    info = os.fstat(fd)
    named = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(named.st_mode)
            or info.st_uid != os.getuid() or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
        raise ValueError('unsafe or replaced maintenance lock')
    if mode == 'check':
        probe = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # flock on the inherited open file description must succeed,
                # unlike the independent probe (which must be excluded).
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            raise ValueError('inherited descriptor was not locked')
        finally:
            os.close(probe)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.set_inheritable(fd, True)
    os.environ[FD_ENV] = str(fd)
    os.execvp(command[0], command)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(f'maintenance lock refused (busy or unsafe): {exc}', file=sys.stderr)
        sys.exit(75)
