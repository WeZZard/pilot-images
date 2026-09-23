#!/usr/bin/env python3
"""Inspect the installed content interfaces and conditional monitor policy."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path('/snap/mesa-2404/current')
UNIT = 'snap.mesa-2404.component-monitor.service'
CONNECT = '#!bin/sh\nset -xeu\n\nsnapctl start --enable ${SNAP_INSTANCE_NAME}.component-monitor\n'
DISCONNECT = '#!bin/sh\nset -xeu\n\nrm --force --verbose ${COMPONENT_TARGET}/${COMPONENT_SENTINEL_PATH##*/}\nsnapctl stop --disable ${SNAP_INSTANCE_NAME}.component-monitor\nfind ${COMPONENT_TARGET} -mindepth 1 -delete\n'


def evaluate(connections, state, connect_hook, disconnect_hook):
    if connect_hook != CONNECT or disconnect_hook != DISCONNECT:
        raise ValueError('installed conditional hook policy changed; review is required')
    rows = [line.split() for line in connections.splitlines()[1:] if line.strip()]
    if any(len(row) != 4 for row in rows):
        raise ValueError('unsupported snap connections output')
    kernel = [row for row in rows if row[1] == 'mesa-2404:kernel-gpu-2404']
    if len(kernel) != 1 or kernel[0][0] not in ('content', 'content[kernel-gpu-2404]'):
        raise ValueError('kernel content interface is missing or ambiguous')
    firefox = [row for row in rows if row[1] == 'firefox:gpu-2404']
    if len(firefox) != 1 or firefox[0][0] != 'content[gpu-2404]' or firefox[0][2] != 'mesa-2404:gpu-2404':
        raise ValueError('Firefox gpu-2404 is not linked to installed Mesa content')
    connected = kernel[0][2] != '-'
    expected = dict(LoadState='loaded', Result='success')
    if connected:
        expected.update(ActiveState='active', SubState='running')
        healthy = all(state.get(k) == v for k, v in expected.items()) and state.get('MainPID', '').isdigit() and int(state['MainPID']) > 0
        monitor = dict(check='component-monitor', status='pass' if healthy else 'fail',
                       reason='connected kernel content requires a running monitor', systemd=state)
    else:
        expected.update(ActiveState='inactive', SubState='dead', MainPID='0', UnitFileState='disabled')
        healthy = all(state.get(k) == v for k, v in expected.items())
        monitor = dict(check='component-monitor', status='not-applicable' if healthy else 'fail',
                       reason='kernel-gpu-2404 is disconnected; installed disconnect hook disables this daemon; no daemon launch is claimed', systemd=state)
    return dict(status='pass' if healthy else 'fail', subchecks=[
        dict(check='installed-hook-policy', status='pass',
             connectSha256=hashlib.sha256(connect_hook.encode()).hexdigest(),
             disconnectSha256=hashlib.sha256(disconnect_hook.encode()).hexdigest()),
        dict(check='content-linkage', status='pass', firefox=firefox[0], kernel=kernel[0]),
        monitor])


def installed_metadata(root, listing):
    rows = listing.splitlines()
    fields = rows[1].split() if len(rows) == 2 else []
    if len(fields) != 6 or fields[0] != 'mesa-2404' or root.resolve().name != fields[2]:
        raise ValueError('installed Mesa revision does not match mounted content')
    raw = (root / 'meta/snap.yaml').read_text()
    for pattern in (
        r'^name: mesa-2404$',
        r'^apps:\n  component-monitor:\n    command: bin/component-monitor\n    restart-delay: 3s\n    daemon: simple\n    restart-condition: always\n(?=[^ \n])',
        r'^  COMPONENT_INTERFACE: kernel-gpu-2404$',
        r'^  COMPONENT_SENTINEL_PATH: \$\{SNAP\}/kernel-gpu-2404/kernel-gpu-2404-sentinel$',
        r'^  COMPONENT_TARGET: \$\{SNAP_DATA\}/kernel-gpu-2404$',
        r'^plugs:\n  kernel-gpu-2404:\n    interface: content\n    target: \$SNAP/kernel-gpu-2404$',
        r'^slots:\n  gpu-2404:\n    interface: content\n    read:\n    - \$SNAP\n    - \$SNAP_DATA/kernel-gpu-2404$',
    ):
        if len(re.findall(pattern, raw, re.MULTILINE)) != 1:
            raise ValueError('installed Mesa metadata policy changed; review is required')
    if not (root / 'bin/component-monitor').is_file():
        raise ValueError('declared monitor binary is missing')
    return dict(check='installed-metadata', status='pass', version=fields[1], revision=fields[2],
                metadataSha256=hashlib.sha256(raw.encode()).hexdigest())


def main():
    try:
        def query(argv):
            return subprocess.check_output(argv, text=True, timeout=6,
                                           env=dict(os.environ, LC_ALL='C', LANG='C'))
        metadata = installed_metadata(ROOT, query(['snap', 'list', 'mesa-2404']))
        connections = query(['snap', 'connections', 'mesa-2404'])
        raw = query(['systemctl', 'show', UNIT, '--no-pager',
                     '--property=LoadState,ActiveState,SubState,MainPID,Result,UnitFileState'])
        state = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        hooks = ROOT / 'meta/hooks'
        result = evaluate(connections, state,
                          (hooks / 'connect-plug-kernel-gpu-2404').read_text(),
                          (hooks / 'disconnect-plug-kernel-gpu-2404').read_text())
        result['subchecks'].insert(0, metadata)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = dict(status='fail', error=str(error))
    print(json.dumps(result))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
