"""Read-only discovery of the current user's active GNOME X11 desktop."""
import os
from pathlib import Path
import re
import stat
import subprocess


class ContextError(RuntimeError):
    """The desktop context cannot be established without guessing or repair."""


GUI_KEYS = frozenset('DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR '
                     'XDG_CURRENT_DESKTOP XDG_SESSION_DESKTOP XDG_SESSION_TYPE '
                     'XDG_SESSION_ID DESKTOP_SESSION'.split())
# Remove stale SSH/Wayland toolkit overrides only for headed startup checks.
CLEAR_KEYS = GUI_KEYS | {'WAYLAND_DISPLAY', 'GDK_BACKEND', 'QT_QPA_PLATFORM'}


def gui_environment(raw):
    """Retain only desktop routing metadata, never unrelated environment values."""
    result = {}
    for item in raw.split(b'\0'):
        key, separator, value = item.partition(b'=')
        if separator and key.decode(errors='replace') in GUI_KEYS:
            result[key.decode()] = value.decode(errors='strict')
    return result


def select_context(sessions, processes, uid):
    """Select one local active same-user desktop and one consistent context."""
    active = [s for s in sessions if s.get('User') == str(uid)
              and s.get('Active') == 'yes' and s.get('Remote') == 'no'
              and s.get('Class') == 'user' and s.get('State') == 'active'
              and s.get('Type') in ('x11', 'wayland')]
    if len(active) != 1 or active[0]['Type'] != 'x11':
        raise ContextError('expected exactly one active local same-user X11 desktop')
    session = active[0]
    contexts = []
    for process in processes:
        if process['uid'] != uid or process['name'] not in ('gnome-shell', 'gnome-session-b'):
            continue
        env = {k: v for k, v in process['environment'].items() if k in GUI_KEYS}
        sid = env.get('XDG_SESSION_ID')
        if sid and sid != session['Id']:
            continue
        groups = [line.split(':', 2)[-1].split('/') for line in process['cgroup'].splitlines()]
        scoped = bool(session.get('Scope')) and any(session['Scope'] in group for group in groups)
        # Modern GNOME runs its shell under the user manager, outside session-N.scope.
        # A unique active graphical session plus this exact same-user X11 unit is required.
        managed = process['name'] == 'gnome-shell' and any(
            group == ['', 'user.slice', f'user-{uid}.slice', f'user@{uid}.service',
                      'session.slice', 'org.gnome.Shell@x11.service'] for group in groups)
        if not (scoped or managed):
            continue
        if env.get('XDG_SESSION_TYPE') != 'x11':
            continue
        if not all(env.get(k) for k in ('DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                                       'XDG_RUNTIME_DIR', 'XDG_CURRENT_DESKTOP')):
            continue
        if session.get('Display') and session['Display'] != env['DISPLAY']:
            raise ContextError('desktop display metadata disagrees')
        # Session identity is established above; do not make otherwise identical
        # shell/session environments ambiguous because only one exports its ID.
        env.pop('XDG_SESSION_ID', None)
        if env not in contexts:
            contexts.append(env)
    if len(contexts) != 1:
        raise ContextError('desktop process context is missing or ambiguous')
    env = contexts[0]
    if not re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', env['DISPLAY']):
        raise ContextError('desktop requires a local X11 display')
    runtime = f'/run/user/{uid}'
    if env['XDG_RUNTIME_DIR'] != runtime or not re.fullmatch(
            re.escape('unix:path=' + runtime + '/bus') + r'(?:,guid=[0-9a-f]+)?',
            env['DBUS_SESSION_BUS_ADDRESS']):
        raise ContextError('desktop runtime or session bus is not local to this user')
    if not Path(env['XAUTHORITY']).is_absolute():
        raise ContextError('desktop Xauthority path is not absolute')
    return env


def _query(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ContextError('loginctl session query unavailable') from None
    if result.returncode:
        raise ContextError('loginctl session query failed')
    return result.stdout


def resolve_context():
    """Read logind and selected /proc metadata; never install or change permissions."""
    uid = os.getuid()
    sessions = []
    for line in _query(['loginctl', 'list-sessions', '--no-legend', '--no-pager']).splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[1] != str(uid):
            continue
        sid = fields[0]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', sid):
            raise ContextError('invalid logind session identifier')
        properties = ('Id', 'User', 'Active', 'Remote', 'Type', 'Class', 'State', 'Scope', 'Display')
        argv = ['loginctl', 'show-session', sid, '--no-pager']
        for key in properties:
            argv.extend(['-p', key])
        session = dict(line.split('=', 1) for line in _query(argv).splitlines() if '=' in line)
        session['Id'] = sid
        sessions.append(session)
    processes = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != uid:
                continue
            name = (directory / 'comm').read_text().strip()
            if name not in ('gnome-shell', 'gnome-session-b'):
                continue
            processes.append(dict(uid=uid, name=name,
                                  cgroup=(directory / 'cgroup').read_text(),
                                  environment=gui_environment((directory / 'environ').read_bytes())))
        except (OSError, UnicodeError):
            # Processes can exit while being inspected. No context means failure below.
            continue
    env = select_context(sessions, processes, uid)
    try:
        runtime = Path(env['XDG_RUNTIME_DIR']).stat()
        authority = Path(env['XAUTHORITY']).stat()
        display = env['DISPLAY'][1:].split('.')[0]
        x11 = Path('/tmp/.X11-unix/X' + display).stat()
        bus = Path(env['XDG_RUNTIME_DIR'], 'bus').stat()
        if (runtime.st_uid != uid or not stat.S_ISDIR(runtime.st_mode)
                or authority.st_uid != uid or not stat.S_ISREG(authority.st_mode)
                or not os.access(env['XAUTHORITY'], os.R_OK)
                or not stat.S_ISSOCK(x11.st_mode) or not stat.S_ISSOCK(bus.st_mode)
                or bus.st_uid != uid):
            raise ContextError('desktop endpoints are not ready for this user')
    except OSError:
        raise ContextError('desktop endpoints are unavailable') from None
    return env
