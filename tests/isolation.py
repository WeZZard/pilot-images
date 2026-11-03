"""The environment of the tests and of every process they start (2026-11-03 decision).

Nothing is copied from the shell that ran the tests: it may select a real
instance (VM_ENVIRONMENT_FILE), point MACHCTL or TART at the installed tools,
or name the operator's stores (TART_HOME, HOME). Every test module imports
this one first, and importing it replaces the runner's own environment with
the isolated one, so code a test calls in process sees none of the shell's
variables either. A test that starts a process gives it `environment(...)`,
the isolated base plus what the test names, such as MACHCTL and TART set to
its own stubs.

A guest phase or check script runs only through `guest_environment(...)`:
its PATH is one directory holding the test's stubs and links to exactly the
system tools the script needs, so a tool nobody stubbed fails instead of
running for real.
"""
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile

ISOLATION_VARIABLE = 'PILOT_IMAGES_ISOLATED'
#: The system directories: they hold no installed machctl, Tart or service.
SYSTEM_PATH = ('/usr/bin', '/bin', '/usr/sbin', '/sbin')
#: HOME when a test names none: a directory that holds nothing of the operator's.
EMPTY_HOME = '/var/empty'

# The one interpreter the tests run under, linked by name, so `python3` in a
# script is this one and not whatever leads the shell's PATH.
_TOOLS = Path(tempfile.mkdtemp(prefix='pilot-images-test-tools-'))
(_TOOLS / 'python3').symlink_to(sys.executable)
atexit.register(shutil.rmtree, _TOOLS, True)


def path(*directories):
    """The isolated PATH with the test's own directories, such as its stubs, first."""
    return os.pathsep.join([*map(str, directories), str(_TOOLS), *SYSTEM_PATH])


def environment(**variables):
    """A child's environment: only what this function sets, then `variables`."""
    env = {'PATH': path(), 'HOME': EMPTY_HOME, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
           ISOLATION_VARIABLE: '1', 'TMPDIR': tempfile.gettempdir()}
    env.update({name: str(value) for name, value in variables.items()})
    return env


def guest_environment(root, stubs=None, tools=(), **variables):
    """The environment of a guest script run on the host, inside `root`.

    PATH is `root/sandbox-bin` alone: each stub (name -> sh body) and a link
    to each named system tool, resolved only in the system directories
    (python3 is the tests' own interpreter).
    """
    bin_dir = Path(root) / 'sandbox-bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (stubs or {}).items():
        stub = bin_dir / name
        stub.write_text('#!/bin/sh\n' + body + '\n')
        stub.chmod(0o755)
    for tool in tools:
        found = sys.executable if tool == 'python3' else shutil.which(tool, path=os.pathsep.join(SYSTEM_PATH))
        if found is None:
            raise FileNotFoundError(f'{tool} is not a system tool; stub it instead')
        link = bin_dir / tool
        if not link.is_symlink():
            link.symlink_to(found)
    variables.setdefault('HOME', str(Path(root) / 'home'))
    return environment(**variables) | {'PATH': str(bin_dir)}


# The runner itself keeps nothing of the shell either.
os.environ.clear()
os.environ.update(environment())
