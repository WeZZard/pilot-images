#!/usr/bin/env python3
"""Check explicitly provisioned phase-00 commands and public CA resources."""
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile


LIMIT = 8192
TIMEOUT = 8
CA_BUNDLE = Path('/etc/ssl/certs/ca-certificates.crt')
CA_LIMIT = 4 * 1024 * 1024
# Every command is reviewed individually. There is no generic help fallback.
COMMANDS = (
    ('dpkg:curl', ('/usr/bin/curl', '--version'), r'(?m)^curl \d+\.'),
    ('dpkg:git', ('/usr/bin/git', '--version'), r'(?m)^git version \d+\.'),
    ('dpkg:gnupg', ('/usr/bin/gpg', '--version'), r'(?m)^gpg \(GnuPG\) \d+\.'),
    ('dpkg:lsb-release', ('/usr/bin/lsb_release', '-d'), r'(?m)^Description:\s+Ubuntu\b'),
    ('dpkg:net-tools', ('/usr/sbin/ifconfig', '--version'), r'(?im)^net-tools \d+\.'),
    ('dpkg:dconf-cli', ('/usr/bin/dconf', 'help'), r'(?is)\busage:.*\bdconf\b'),
    ('dpkg:x11-utils', ('/usr/bin/xdpyinfo', '-version'), r'(?m)^xdpyinfo \d+\.'),
    ('dpkg:fontconfig', ('/usr/bin/fc-list', '--version'), r'(?im)^fontconfig version \d+\.'),
    ('dpkg:unzip', ('/usr/bin/unzip', '-v'), r'(?m)^UnZip \d+\.'),
)


def check_command(inventory_id, argv, pattern):
    result = dict(inventoryId=inventory_id, argv=list(argv), status='fail')
    try:
        # Files bound memory even if a broken executable floods its output.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                run = subprocess.run(list(argv), stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, timeout=TIMEOUT,
                                     env=dict(os.environ, LC_ALL='C', LANG='C'),
                                     shell=False, check=False)
                result['returncode'] = run.returncode
            except (OSError, subprocess.SubprocessError) as error:
                result['error'] = str(error)[:LIMIT]
            truncated = False
            for name, stream in (('stdout', stdout), ('stderr', stderr)):
                stream.seek(0)
                data = stream.read(LIMIT + 1)
                truncated = truncated or len(data) > LIMIT
                result[name] = data[:LIMIT].decode('utf-8', errors='replace')
            result['truncated'] = truncated
        identified = bool(re.search(pattern, result['stdout'] + '\n' + result['stderr']))
        result['identified'] = identified
        if result.get('returncode') == 0 and identified and not truncated and 'error' not in result:
            result['status'] = 'pass'
    except OSError as error:
        result['error'] = str(error)[:LIMIT]
    return result


def check_certificates():
    result = dict(inventoryId='dpkg:ca-certificates', path=str(CA_BUNDLE), status='fail')
    try:
        # Read only the fixed public bundle, never a private-key directory.
        with CA_BUNDLE.open('rb') as stream:
            data = stream.read(CA_LIMIT + 1)
        if not data or len(data) > CA_LIMIT or b'PRIVATE KEY' in data:
            raise ValueError('Public CA bundle is empty, oversized, or contains private-key material')
        if b'-----BEGIN CERTIFICATE-----' not in data:
            raise ValueError('Public CA bundle has no PEM certificate')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=data.decode('ascii'))
        count = len(context.get_ca_certs())
        if not count:
            raise ValueError('Public CA bundle contains no usable CA certificates')
        result.update(status='pass', bytes=len(data), caCount=count)
    except (OSError, ValueError, UnicodeError) as error:
        result['error'] = str(error)[:LIMIT]
    return result


def main():
    checks = [check_command(*command) for command in COMMANDS]
    checks.append(check_certificates())
    passed = all(check['status'] == 'pass' for check in checks)
    print(json.dumps(dict(status='pass' if passed else 'fail', checks=checks)))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
