#!/usr/bin/env python3
"""Opt-in application checks on a fresh credential-free vm-service clone.

The default source is base. Work acceptance holds the image maintenance lock,
uses only vm-service's configured work source, and publishes a receipt only
after release, unchanged plans, and stopped-source revalidation.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import re
import hashlib

import inventory

REPO = Path(__file__).resolve().parents[1]


def acceptance_module():
    spec = importlib.util.spec_from_file_location('application_acceptance', REPO / 'host/application-acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_clone(image, evidence, invoke=subprocess.run, *, source='base', work=None, stopped=None):
    """The injected boundary is only for tests; production always uses vmctl."""
    if source not in ('base', 'work'):
        raise ValueError('unsupported clone source')
    acceptance = acceptance_module()
    plan = acceptance.checks.plan_digest(REPO / 'applications',
        acceptance.checks.load(REPO / 'images' / image / 'application-tests.json'))
    if source == 'work':
        if work is None or stopped is None:
            raise ValueError('work acceptance requires maintenance ownership and stopped checks')
        # The CLI verifies the inherited lock before calling this boundary.
        # Injected lifecycle tests supply their own stopped-state boundary.
        inventory.invalidate(work['receipt'])
        acceptance = acceptance_module()
        stopped()
        before = acceptance.fresh_inputs(work['association'], work['portable'], image,
            work['root'], work['vm'], work['kind'])
        plan = acceptance.checks.plan_digest(REPO / 'applications',
            acceptance.checks.load(REPO / 'images' / image / 'application-tests.json'))
    vm = None
    sequence = 0
    # tempfile suffixes may contain underscores, which the VM purpose rejects.
    purpose = ('accept-' + re.sub('[^a-z0-9-]', '-', image.lower())[:30] + '-' + hashlib.sha256(evidence.name.encode()).hexdigest()[:12])

    def call(*args, allow_failure=False, command_timeout=None):
        nonlocal sequence
        sequence += 1
        options = {}
        if source == 'work' and os.environ.get('PILOT_MAINTENANCE_FD'):
            options['pass_fds'] = (int(os.environ['PILOT_MAINTENANCE_FD']),)
        argv = [os.environ['VMCTL'] if os.environ.get('VM_ENVIRONMENT_FILE') else 'vmctl', *map(str, args)]
        if command_timeout is not None:
            if args[0] != 'exec':
                raise ValueError('command timeout applies only to exec')
            at = argv.index('--')
            argv[at:at] = ['--timeout', str(command_timeout)]
        result = invoke(argv, text=True, capture_output=True, timeout=max(1200, (command_timeout or 0) + 60), **options)
        (evidence / f'{sequence:02d}.json').write_text(json.dumps(dict(argv=argv,
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2) + '\n')
        if result.returncode and not allow_failure:
            raise RuntimeError(f'vmctl {args[0]} failed; see {evidence}')
        return result

    try:
        source_args = []
        if source == 'work':
            expected = evidence / 'expected-source-fingerprint.json'
            expected.write_bytes(inventory.encode(before['base']))
            source_args = ['--expected-source-fingerprint', expected]
        lease = json.loads(call('acquire', '--purpose', purpose, '--image', image, '--source', source,
            '--env', 'none', '--ttl-hours', '4', *source_args).stdout)
        returned_vm = inventory.key(lease['vm'])
        if source == 'work' and returned_vm == work['vm']:
            raise ValueError('vm-service returned work VM instead of an owned clone; refusing release')
        vm = returned_vm
        (evidence / 'lease.json').write_text(json.dumps(lease, indent=2) + '\n')
        if source == 'work' and (lease.get('source') != 'work' or lease.get('source_vm') != work['vm']
                or lease.get('source_fingerprint') != before['base'] or vm == work['vm']):
            raise ValueError('vm-service returned an incorrect work source')
        remote = '/tmp/' + evidence.name
        call('exec', vm, '--', 'mkdir', '-p', remote)
        call('push', vm, REPO / 'applications', remote + '/applications')
        call('exec', vm, '--', 'mkdir', '-p', remote + '/images/' + image)
        call('push', vm, REPO / 'images' / image / 'guest', remote + '/images/' + image + '/guest')
        call('push', vm, REPO / 'inventory', remote + '/inventory')
        call('push', vm, REPO / 'images' / image / 'application-tests.json', remote + '/selection.json')
        # Collection alone may need manager discovery. Execution checks never
        # source a shell profile, nvm, or change PATH.
        call('exec', vm, '--', 'python3', '-c',
             'import subprocess,sys; f=open(sys.argv[1],"wb"); subprocess.run([sys.executable,*sys.argv[2:]],stdout=f,check=True)',
             remote + '/installed.json', remote + '/inventory/collect.py', '--aliases', remote + '/inventory/aliases.json')
        raw = evidence / 'inventory.json'
        call('pull', vm, remote + '/installed.json', raw)
        inventory.validate(inventory.read_json(raw), lease['image_kind'])
        result = call('exec', vm, '--', 'python3', remote + '/applications/check.py', '--selection', remote + '/selection.json',
                      '--inventory', remote + '/installed.json', '--build-id', evidence.name, '--output', remote + '/report.json', allow_failure=True, command_timeout=3600)
        call('pull', vm, remote + '/report.json', evidence / 'applications.json')
        if result.returncode:
            raise RuntimeError(f'clone application acceptance failed; see {evidence}')
        report = acceptance.validate_report(evidence / 'applications.json', None, image,
            acceptance.raw_document(raw))
        if report['planSha256'] != plan:
            raise ValueError('application plan changed during clone acceptance')
    finally:
        if vm is not None:
            # Keep every command and pulled report even when cleanup fails.
            call('release', vm)
    if plan != acceptance.checks.plan_digest(REPO / 'applications',
            acceptance.checks.load(REPO / 'images' / image / 'application-tests.json')):
        raise ValueError('application plan changed during clone acceptance')
    if source == 'work':
        stopped()
        if before != acceptance.fresh_inputs(work['association'], work['portable'], image,
                work['root'], work['vm'], work['kind']):
            raise ValueError('work association changed during clone test')
        acceptance.seal_fresh(evidence, work['association'], work['portable'], work['receipt'],
            image, work['root'], work['vm'], work['kind'], plan)
    return report


def main():
    from environment import initialize
    initialize()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--source', choices=('base', 'work'), default='base')
    args = parser.parse_args()
    image = inventory.key(args.image)
    if not (REPO / 'images' / image / 'application-tests.json').is_file():
        parser.error('image has no application selection')
    work = None
    stopped = None
    if args.source == 'work':
        lock = REPO / 'host/maintenance-lock.py'
        if not os.environ.get('PILOT_MAINTENANCE_FD'):
            os.execv(sys.executable, [sys.executable, str(lock), 'acquire', image,
                sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
        fd = int(os.environ['PILOT_MAINTENANCE_FD'])
        subprocess.run([sys.executable, str(lock), 'check', image], check=True, pass_fds=(fd,))
        # Read the trusted image configuration, not caller-supplied VM paths.
        config = subprocess.run(['zsh', '-c', 'source "$1"; printf "%s\\n%s\\n" "$WORK_VM" "$LINE_KIND"',
            'check-clone', str(REPO / 'images' / image / 'line.conf')], check=True, text=True, capture_output=True)
        vm, kind = config.stdout.splitlines()
        inventory.key(vm)
        def stopped():
            listing = subprocess.run([os.environ['TART'] if os.environ.get('VM_ENVIRONMENT_FILE') else 'tart', 'list'], check=True, text=True, capture_output=True)
            states = [row.split()[-1] for row in listing.stdout.splitlines()
                if len(row.split()) >= 3 and row.split()[1] == vm]
            if states != ['stopped']:
                raise ValueError('work source must be known stopped')
    root = Path(os.environ.get('TART_HOME', str(Path.home() / '.tart'))) / 'vms'
    if args.source == 'work':
        state = inventory.state_directory(root)
        work = dict(root=root, vm=vm, kind=kind, association=state / 'work' / (image + '.json'),
            portable=state / 'pending' / (image + '.json'),
            receipt=state / 'acceptance/fresh-work' / (image + '.json'))
    attempts = inventory.state_directory(root) / 'extracted'
    attempts.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix='accept-' + image + '-', dir=attempts))
    print(evidence, flush=True)
    check_clone(image, evidence, source=args.source, work=work, stopped=stopped)


if __name__ == '__main__':
    main()
