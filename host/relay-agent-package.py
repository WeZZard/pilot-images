#!/usr/bin/env python3
"""Acquire the relay agent archive for one guest platform, checked against the lock.

    relay-agent-package.py fetch --lock guest/relay-agent.lock.json \
        (--platform darwin-arm64 | --uname "Darwin arm64") --output OUT [--archive FILE]

The lock (guest/relay-agent.lock.json, identical on every line) pins one
vm-service release: its version, and the URL and SHA-256 of each platform's
archive, relay-agent-<version>-<platform>.tar.gz, a gzipped tar that holds the
one executable `relay-agent` (docs/relay-agent.md RA-I1).

- A pinned lock: the archive is downloaded from the release, or read from
  --archive as an offline copy, and its SHA-256 must equal the pin.
- An unpinned lock (version null, before vm-service publishes a release):
  --archive is required, a local build from vm-service's
  rust/scripts/build-relay-agent.sh, and its SHA-256 is reported as `local`.

Either way the archive is read, never run: one regular executable file named
relay-agent, built for the platform. Prints the result as JSON.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import tarfile
import tempfile
import urllib.parse
import urllib.request

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXECUTABLE = 128 * 1024 * 1024
PLATFORMS = ('darwin-arm64', 'linux-arm64', 'linux-x86_64')
UNAMES = {('Darwin', 'arm64'): 'darwin-arm64', ('Linux', 'aarch64'): 'linux-arm64',
          ('Linux', 'arm64'): 'linux-arm64', ('Linux', 'x86_64'): 'linux-x86_64'}
ELF_MACHINE = {'linux-arm64': 183, 'linux-x86_64': 62}
MACHO_ARM64 = 0x0100000C
ASSET_HOSTS = ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')


def release_url(repository, version, platform):
    return 'https://github.com/%s/releases/download/v%s/relay-agent-%s-%s.tar.gz' % (repository, version, version, platform)


def platform_of(uname):
    """The platform of `uname -sm` output, such as 'Darwin arm64'."""
    parts = tuple(uname.split())
    if parts not in UNAMES:
        raise ValueError('no relay agent platform for %r' % uname)
    return UNAMES[parts]


def read_lock(path):
    lock = json.loads(Path(path).read_text())
    if set(lock) != {'schemaVersion', 'repository', 'version', 'platforms'} or lock['schemaVersion'] != 1:
        raise ValueError('invalid relay agent lock fields')
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', lock['repository']):
        raise ValueError('invalid relay agent repository')
    if set(lock['platforms']) != set(PLATFORMS) or any(set(p) != {'url', 'sha256'} for p in lock['platforms'].values()):
        raise ValueError('the relay agent lock must name url and sha256 for exactly %s' % ', '.join(PLATFORMS))
    if lock['version'] is None:
        if any(v is not None for p in lock['platforms'].values() for v in p.values()):
            raise ValueError('an unpinned relay agent lock carries no url or sha256')
        return lock
    if not re.fullmatch(r'\d+\.\d+\.\d+', lock['version']):
        raise ValueError('invalid relay agent version')
    for platform, pin in lock['platforms'].items():
        if pin['url'] != release_url(lock['repository'], lock['version'], platform):
            raise ValueError('relay agent %s URL is not the pinned release asset' % platform)
        if not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'] or ''):
            raise ValueError('invalid relay agent %s SHA-256' % platform)
    return lock


def check_executable(header, platform):
    if platform in ELF_MACHINE:
        if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != ELF_MACHINE[platform]:
            raise ValueError('relay-agent is not a %s ELF64 executable' % platform)
    elif len(header) < 8 or struct.unpack('<II', header[:8]) != (0xFEEDFACF, MACHO_ARM64):
        raise ValueError('relay-agent is not a Mach-O arm64 executable')


def inspect_archive(data, platform):
    """Raise unless the archive holds exactly one executable regular file, relay-agent, for the platform."""
    if len(data) > MAX_ARCHIVE:
        raise ValueError('relay agent archive exceeds %d bytes' % MAX_ARCHIVE)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        if [m.name for m in members] != ['relay-agent'] or not members[0].isfile():
            raise ValueError('the relay agent archive must hold only the regular file relay-agent')
        member = members[0]
        if member.size > MAX_EXECUTABLE or not member.mode & 0o100:
            raise ValueError('relay-agent is too large or not executable')
        check_executable(archive.extractfile(member).read(20), platform)


def download(url, opener):
    request = urllib.request.Request(url, headers={'User-Agent': 'pilot-images-relay-agent'})
    with opener(request, timeout=120) as stream:
        final = urllib.parse.urlsplit(stream.geturl())
        if final.scheme != 'https' or final.hostname not in ASSET_HOSTS:
            raise ValueError('relay agent download redirected outside the release asset hosts')
        return stream.read(MAX_ARCHIVE + 1)


def fetch(lock_path, platform, output, local_archive=None, opener=urllib.request.urlopen):
    lock = read_lock(lock_path)
    if platform not in PLATFORMS:
        raise ValueError('unknown relay agent platform %s' % platform)
    pin = lock['platforms'][platform]
    if local_archive:
        with Path(local_archive).open('rb') as stream:
            data = stream.read(MAX_ARCHIVE + 1)
    elif lock['version'] is None:
        raise ValueError('no relay agent release is pinned in %s; set RELAY_AGENT_ARCHIVE to a local '
                         'relay-agent-<version>-%s.tar.gz from vm-service rust/scripts/build-relay-agent.sh' % (lock_path, platform))
    else:
        data = download(pin['url'], opener)
    digest = hashlib.sha256(data).hexdigest()
    if lock['version'] is not None and digest != pin['sha256']:
        raise ValueError('relay agent %s archive hashes to %s, the lock pins %s' % (platform, digest, pin['sha256']))
    inspect_archive(data, platform)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
        staged = Path(temporary.name)
    try:
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    return {'version': lock['version'], 'platform': platform, 'sha256': digest,
            'source': 'pinned' if lock['version'] is not None else 'local'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('fetch',))
    parser.add_argument('--lock', required=True, type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument('--platform', choices=PLATFORMS)
    which.add_argument('--uname', help='the guest\'s `uname -sm` output')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    platform = args.platform or platform_of(args.uname)
    print(json.dumps(fetch(args.lock, platform, args.output, args.archive)))


if __name__ == '__main__':
    main()
