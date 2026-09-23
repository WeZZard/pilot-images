#!/usr/bin/env python3
"""Observe the existing scheduler without starting or repairing it."""
import json
import os
import subprocess


UNIT = 'snap.cups.cupsd.service'


def evaluate(scheduler, state):
    errors = []
    if scheduler.strip() != 'scheduler is running':
        errors.append('lpstat did not report scheduler is running')
    if any(state.get(k) != v for k, v in {
        'LoadState': 'loaded', 'ActiveState': 'active',
        'SubState': 'running', 'Result': 'success',
    }.items()):
        errors.append('cupsd is not loaded, active/running with Result=success')
    if not state.get('MainPID', '').isdigit() or int(state['MainPID']) <= 0:
        errors.append('cupsd has no positive MainPID')
    return dict(status='fail' if errors else 'pass', unit=UNIT,
                scheduler=scheduler.strip(), systemd=state, errors=errors)


def main():
    try:
        env = dict(os.environ, LC_ALL='C', LANG='C')
        scheduler = subprocess.check_output(['/snap/bin/cups.lpstat', '-r'],
                                            text=True, timeout=8, env=env)
        raw = subprocess.check_output([
            'systemctl', 'show', UNIT, '--no-pager',
            '--property=LoadState,ActiveState,SubState,MainPID,Result',
        ], text=True, timeout=5, env=env)
        result = evaluate(scheduler, dict(line.split('=', 1) for line in raw.splitlines() if '=' in line))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        result = dict(status='fail', unit=UNIT, error=str(error))
    print(json.dumps(result))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
