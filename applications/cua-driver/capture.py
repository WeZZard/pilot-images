#!/usr/bin/env python3
"""Capture through the already-running driver; never start or repair it."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import os
import socket
import stat
import zlib


def png_dimensions(raw):
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('capture is not PNG')
    offset, dimensions, data = 8, None, bytearray()
    while offset + 12 <= len(raw):
        size = struct.unpack('>I', raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 8 + size
        if end + 4 > len(raw) or zlib.crc32(raw[offset + 4:end]) != struct.unpack('>I', raw[end:end + 4])[0]:
            raise ValueError('invalid PNG chunk')
        if kind == b'IHDR':
            if size != 13 or dimensions is not None:
                raise ValueError('invalid PNG header')
            dimensions = struct.unpack('>II', raw[offset + 8:offset + 16])
            if not all(dimensions) or max(dimensions) > 32768:
                raise ValueError('invalid PNG dimensions')
        if kind == b'IDAT':
            data.extend(raw[offset + 8:end])
        if kind == b'IEND':
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(bytes(data), 64 * 1024 * 1024)
            if size or end + 4 != len(raw) or dimensions is None or not decoded or not decoder.eof:
                raise ValueError('incomplete or oversized PNG')
            return dimensions
        offset = end + 4
    raise ValueError('missing PNG end')


def native_x11_ready(query=subprocess.check_output, uid=None):
    uid = os.getuid() if uid is None else uid
    sessions = query(['loginctl', 'list-sessions', '--no-legend', '--no-pager'], text=True, timeout=5)
    native = []
    for row in sessions.splitlines():
        fields = row.split()
        if len(fields) >= 3 and fields[1] == str(uid):
            raw = query(['loginctl', 'show-session', fields[0], '-p', 'Type', '-p', 'Active', '-p', 'Remote'], text=True, timeout=5)
            values = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
            if values.get('Type') == 'x11' and values.get('Active') == 'yes' and values.get('Remote') == 'no':
                native.append(fields[0])
    if len(native) > 1:
        raise RuntimeError('multiple active native X11 sessions; capture context is ambiguous')
    return bool(native)


def daemon_socket_ready(path=None, uid=None):
    path = Path.home() / '.cache/cua-driver/cua-driver.sock' if path is None else Path(path)
    uid = os.getuid() if uid is None else uid
    try:
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid:
            raise RuntimeError('capture endpoint is not a same-user Unix socket')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            probe.connect(str(path))
        return True
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
        return False


def capture_context_ready():
    return native_x11_ready() and daemon_socket_ready()


def wait_for_native_x11(check=capture_context_ready, clock=time.monotonic, pause=time.sleep, timeout=60):
    deadline = clock() + timeout
    while True:
        if check(): return
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError('native X11 session and capture daemon not ready within startup observation deadline')
        print('Waiting for native X11 session and capture daemon; no configuration changes made.', file=sys.stderr, flush=True)
        pause(min(1, remaining))


def main():
    if sys.platform == 'darwin':
        permissions = json.loads(subprocess.check_output(['cua-driver', 'permissions', 'status', '--json'], timeout=10))
        # Driver schema can contain nested attribution/permission observations.
        encoded = json.dumps(permissions)
        if 'driver-daemon' not in encoded or '"accessibility": true' not in encoded or '"screen_recording": true' not in encoded:
            raise RuntimeError('capture daemon is not independently TCC-authorized')
    else:
        # SSH readiness precedes desktop autologin on a fresh boot. Observe a
        # bounded startup window without starting a daemon or changing settings.
        wait_for_native_x11()
    with tempfile.TemporaryDirectory(prefix='pilot-capture-') as directory:
        output = Path(directory) / 'desktop.png'
        result = json.loads(subprocess.check_output(['cua-driver', 'call', 'get_desktop_state', '--json', json.dumps({'screenshot_out_file': str(output)})], timeout=40))
        if result.get('screenshot_file_path') != str(output) or output.is_symlink() or output.stat().st_size > 64 * 1024 * 1024:
            raise RuntimeError('capture returned an invalid artifact')
        raw = output.read_bytes()
        width, height = png_dimensions(raw)
        print(json.dumps(dict(width=width, height=height, sha256=hashlib.sha256(raw).hexdigest())))


if __name__ == '__main__':
    main()
