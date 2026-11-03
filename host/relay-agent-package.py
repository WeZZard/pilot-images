#!/usr/bin/env python3
"""The relay agent's archive, checked against the lock, and the promotion gate.

    relay-agent-package.py fetch --lock guest/relay-agent.lock.json \
        (--platform darwin-arm64 | --uname "Darwin arm64") --output OUT [--archive FILE]
    relay-agent-package.py record --observed FILE --output EVIDENCE/relay-agent.json
    relay-agent-package.py gate --lock guest/relay-agent.lock.json --receipt WORK_RECEIPT

The lock (guest/relay-agent.lock.json, identical on every line) pins one
vm-service release: its version, and for each platform the URL and SHA-256 of
the archive, relay-agent-<version>-<platform>.tar.gz, a gzipped tar that holds
the one executable `relay-agent`, and the SHA-256 of that executable
(docs/relay-agent.md RA-I1).

The lock also names the macOS executable's signature, `signing`: `developer-id`
for a release, or `adhoc`, which only a pre-release may carry (vm-service
DC-224). It never names the team: the team is the one the pinned executable's
own signature carries, which RELAY_AGENT_TEAM_ID, when set, must equal. `fetch`
reads the darwin executable's designated requirement with `codesign -dr -`
(reading, never running it) and puts the signature into its record: the kind,
the team, and the requirement phase 65 pins the agent's privacy grants to (the
full designated requirement of a Developer ID build, the identifier alone for an
ad hoc one).

`record` turns what the image's extraction read in the guest into the
evidence of which agent the image carries (RA-I7); `gate` refuses a promotion
unless that evidence, bound to the stopped work image, is the pinned release.

- A pinned lock: the archive is downloaded from the release, or read from
  --archive as an offline copy, and its SHA-256 must equal the pin.
- An unpinned lock (version null, before vm-service publishes a release):
  --archive is required, a local build from vm-service's
  rust/scripts/build-relay-agent.sh, and its SHA-256 is reported as `local`.

Either way the archive is read, never run: one regular executable file named
relay-agent, built for the platform, whose SHA-256 must equal the pin. Prints
the result as JSON on one line, which guest phase 62 keeps beside the agent.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
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
PIN_FIELDS = {'url', 'sha256', 'executableSha256'}
HEX64 = re.compile(r'[0-9a-f]{64}')
ASSET_HOSTS = ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?')
SIGNINGS = ('developer-id', 'adhoc')
IDENTIFIER = 'com.wezzard.relay-agent'
TEAM = re.compile(r'[A-Z0-9]{10}')
TEAM_VARIABLE = 'RELAY_AGENT_TEAM_ID'
# What follows the identifier in the designated requirement codesign makes for a
# Developer ID Application certificate (vm-service service_layout::signing).
DEVELOPER_ID_TAIL = (' and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] /* exists */'
                     ' and certificate leaf[field.1.2.840.113635.100.6.1.13] /* exists */ and certificate leaf[subject.OU] = ')
DESIGNATED = re.compile(r'identifier (?:"([^"]+)"|([A-Za-z0-9._-]+))' + re.escape(DEVELOPER_ID_TAIL) + r'(?:"([^"]+)"|([A-Za-z0-9]+))')


# --- the macOS executable's signature (vm-service DC-224) ------------------------------

def developer_id_requirement(team, identifier=IDENTIFIER):
    """The designated requirement of `identifier` signed with Developer ID by `team`."""
    return 'identifier "%s"%s"%s"' % (identifier, DEVELOPER_ID_TAIL, team)


def requirement(kind, team):
    """The requirement the agent's privacy grants are pinned to."""
    return developer_id_requirement(team) if kind == 'developer-id' else 'identifier "%s"' % IDENTIFIER


def parse_designated(output):
    """(kind, identifier, team) from `codesign -dr -` output: ('adhoc', None, None) for code hashes,
    ('developer-id', identifier, team) for the Developer ID form; any other form is refused."""
    lines = [line.strip().removeprefix('# ').strip() for line in output.splitlines()]
    found = [line.removeprefix('designated => ') for line in lines if line.startswith('designated => ')]
    if not found:
        raise ValueError('no designated requirement in the codesign output')
    text = found[0]
    if all(re.fullmatch(r'cdhash H"[0-9a-f]+"', part) for part in text.split(' or ')):
        return 'adhoc', None, None
    match = DESIGNATED.fullmatch(text)
    if not match or not TEAM.fullmatch(match.group(3) or match.group(4)):
        raise ValueError('the designated requirement %r is neither ad hoc nor Developer ID' % text)
    return 'developer-id', match.group(1) or match.group(2), match.group(3) or match.group(4)


def read_designated(executable):
    """`codesign -dr -` output for the executable bytes, read from a temporary file and never run."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'relay-agent'
        path.write_bytes(executable)
        try:
            result = subprocess.run(['/usr/bin/codesign', '-d', '-r-', str(path)], capture_output=True, text=True)
        except FileNotFoundError:
            raise ValueError('reading the macOS relay agent\'s signature needs /usr/bin/codesign') from None
        if result.returncode != 0:
            raise ValueError('the macOS relay agent is not signed: %s' % result.stderr.strip())
        return result.stderr + result.stdout


def signing_of(designated, team=None):
    """The package record's `signing` from `codesign -dr -` output, refused unless it carries the
    identifier and, when `team` is configured, that team."""
    kind, identifier, signed_team = parse_designated(designated)
    if kind == 'developer-id' and identifier != IDENTIFIER:
        raise ValueError('the macOS relay agent is signed with the identifier %s, not %s' % (identifier, IDENTIFIER))
    if kind == 'developer-id' and team and signed_team != team:
        raise ValueError('the macOS relay agent is signed by another team than %s names' % TEAM_VARIABLE)
    return {'kind': kind, 'team': signed_team, 'requirement': requirement(kind, signed_team)}


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
    if set(lock) != {'schemaVersion', 'repository', 'version', 'signing', 'platforms'} or lock['schemaVersion'] != 1:
        raise ValueError('invalid relay agent lock fields')
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', lock['repository']):
        raise ValueError('invalid relay agent repository')
    if set(lock['platforms']) != set(PLATFORMS) or any(set(p) != PIN_FIELDS for p in lock['platforms'].values()):
        raise ValueError('the relay agent lock must name url, sha256 and executableSha256 for exactly %s' % ', '.join(PLATFORMS))
    if lock['version'] is None:
        if lock['signing'] is not None or any(v is not None for p in lock['platforms'].values() for v in p.values()):
            raise ValueError('an unpinned relay agent lock carries no url, sha256 or signing')
        return lock
    if not VERSION.fullmatch(lock['version']):
        raise ValueError('invalid relay agent version')
    if lock['signing'] not in SIGNINGS:
        raise ValueError('the relay agent lock must name its macOS signing, %s' % ' or '.join(SIGNINGS))
    if lock['signing'] == 'adhoc' and '-' not in lock['version']:
        raise ValueError('relay agent %s is a release, which must be signed with Developer ID; only a pre-release '
                         'may be ad hoc (vm-service DC-224)' % lock['version'])
    for platform, pin in lock['platforms'].items():
        if pin['url'] != release_url(lock['repository'], lock['version'], platform):
            raise ValueError('relay agent %s URL is not the pinned release asset' % platform)
        if not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'] or ''):
            raise ValueError('invalid relay agent %s SHA-256' % platform)
        if not re.fullmatch(r'[0-9a-f]{64}', pin['executableSha256'] or ''):
            raise ValueError('invalid relay agent %s executable SHA-256' % platform)
    return lock


def check_executable(header, platform):
    if platform in ELF_MACHINE:
        if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != ELF_MACHINE[platform]:
            raise ValueError('relay-agent is not a %s ELF64 executable' % platform)
    elif len(header) < 8 or struct.unpack('<II', header[:8]) != (0xFEEDFACF, MACHO_ARM64):
        raise ValueError('relay-agent is not a Mach-O arm64 executable')


def inspect_archive(data, platform, content=False):
    """The SHA-256 of the archive's executable (with its bytes when `content`); raise unless the archive
    holds exactly one executable regular file, relay-agent, for the platform."""
    if len(data) > MAX_ARCHIVE:
        raise ValueError('relay agent archive exceeds %d bytes' % MAX_ARCHIVE)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        if [m.name for m in members] != ['relay-agent'] or not members[0].isfile():
            raise ValueError('the relay agent archive must hold only the regular file relay-agent')
        member = members[0]
        if member.size > MAX_EXECUTABLE or not member.mode & 0o100:
            raise ValueError('relay-agent is too large or not executable')
        executable = archive.extractfile(member).read(MAX_EXECUTABLE + 1)
        if len(executable) != member.size:
            raise ValueError('relay-agent is shorter than its tar header says')
        check_executable(executable[:20], platform)
        digest = hashlib.sha256(executable).hexdigest()
        return (digest, executable) if content else digest


def download(url, opener):
    request = urllib.request.Request(url, headers={'User-Agent': 'pilot-images-relay-agent'})
    with opener(request, timeout=120) as stream:
        final = urllib.parse.urlsplit(stream.geturl())
        if final.scheme != 'https' or final.hostname not in ASSET_HOSTS:
            raise ValueError('relay agent download redirected outside the release asset hosts')
        return stream.read(MAX_ARCHIVE + 1)


def fetch(lock_path, platform, output, local_archive=None, opener=urllib.request.urlopen, designated=read_designated,
          team=None):
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
    executable, content = inspect_archive(data, platform, content=True)
    if lock['version'] is not None and executable != pin['executableSha256']:
        raise ValueError('relay agent %s executable hashes to %s, the lock pins %s' % (platform, executable, pin['executableSha256']))
    signing = None
    if platform == 'darwin-arm64':
        signing = signing_of(designated(content), team)
        if lock['version'] is not None and signing['kind'] != lock['signing']:
            raise ValueError('relay agent %s is signed %s, the lock pins %s' % (lock['version'], signing['kind'], lock['signing']))
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
    return {'version': lock['version'], 'platform': platform, 'sha256': digest, 'executableSha256': executable,
            'source': 'pinned' if lock['version'] is not None else 'local', 'signing': signing}


# --- the evidence of the installed agent, and the promotion gate (RA-I7) ---------------

def parse_package(text):
    """The record `fetch` printed, as guest phase 62 keeps it beside the agent."""
    package = json.loads(text)
    if type(package) is not dict or set(package) != {'version', 'platform', 'sha256', 'executableSha256', 'source', 'signing'}:
        raise ValueError('the relay agent package record has other fields')
    signing = package['signing']
    if package['platform'] != 'darwin-arm64':
        if signing is not None:
            raise ValueError('only the macOS relay agent package names a signing')
    elif type(signing) is not dict or set(signing) != {'kind', 'team', 'requirement'} or signing['kind'] not in SIGNINGS \
            or (signing['kind'] == 'developer-id') != bool(TEAM.fullmatch(signing['team'] or '')) \
            or signing['requirement'] != requirement(signing['kind'], signing['team']):
        raise ValueError('invalid relay agent package signing')
    if package['platform'] not in PLATFORMS or package['source'] not in ('pinned', 'local'):
        raise ValueError('invalid relay agent package platform or source')
    if not (HEX64.fullmatch(package['sha256'] or '') and HEX64.fullmatch(package['executableSha256'] or '')):
        raise ValueError('invalid relay agent package SHA-256')
    if (package['version'] is None) != (package['source'] == 'local') or \
            (package['version'] is not None and not VERSION.fullmatch(package['version'])):
        raise ValueError('a relay agent package is pinned with a version, or local without one')
    return package


def record(observed, output):
    """Write the evidence of the installed relay agent from what the extraction read in the guest: three
    lines, `uname -sm`, the package record phase 62 kept, and the SHA-256 of the installed executable."""
    lines = Path(observed).read_text().splitlines()
    if len(lines) != 3:
        raise ValueError('the relay agent observation has %d lines, not uname, package and SHA-256' % len(lines))
    uname, package, installed = lines
    platform = platform_of(uname)
    package = parse_package(package)
    if package['platform'] != platform:
        raise ValueError('the relay agent package is for %s, the guest is %s' % (package['platform'], platform))
    if not HEX64.fullmatch(installed):
        raise ValueError('no SHA-256 of the installed relay agent executable')
    signing = package['signing'] and {k: package['signing'][k] for k in ('kind', 'team')}
    value = {'schemaVersion': 1, 'platform': platform, 'archive': {k: package[k] for k in ('version', 'source', 'sha256')},
             'archiveExecutableSha256': package['executableSha256'], 'installedSha256': installed, 'signing': signing}
    # Exclusive creation, as for the image checks' results: evidence is never rewritten.
    with Path(output).open('x') as stream:
        stream.write(json.dumps(value, indent=1) + '\n')
    return value


def gate(lock_path, receipt_path):
    """Refuse, with the reason, unless the relay agent in the work image's bound evidence is the pinned
    release's executable for its platform; return the evidence."""
    lock = read_lock(lock_path)
    receipt = json.loads(Path(receipt_path).read_text())
    bound = receipt.get('relayAgent') if type(receipt) is dict else None
    if type(bound) is not dict or set(bound) != {'path', 'sha256'}:
        raise ValueError('the work image has no relay agent evidence; extract it again (host/extract-work-inventory.zsh) '
                         'so the extraction records the installed agent')
    data = Path(bound['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != bound['sha256']:
        raise ValueError('the relay agent evidence %s changed after it was bound to the work image' % bound['path'])
    evidence = json.loads(data)
    platform, archive = evidence['platform'], evidence['archive']
    installed = 'relay agent %s (%s, archive %s)' % (archive['version'] or 'local build', platform, archive['sha256'])
    if lock['version'] is None:
        raise ValueError('%s: the lock pins no release, so no base can be promoted; pin a vm-service release '
                         '(host/update-software.py --apply), rebuild phase 62 and extract again' % installed)
    pin = lock['platforms'][platform]
    if archive['source'] != 'pinned' or archive['version'] != lock['version'] or archive['sha256'] != pin['sha256']:
        raise ValueError('%s is not the release the lock pins, %s (archive %s); rebuild phase 62 without '
                         'RELAY_AGENT_ARCHIVE or with a copy of the pinned archive' % (installed, lock['version'], pin['sha256']))
    if platform == 'darwin-arm64' and (evidence.get('signing') or {}).get('kind') != lock['signing']:
        raise ValueError('%s is signed %s, the lock pins %s; rebuild phase 62' % (
            installed, (evidence.get('signing') or {}).get('kind'), lock['signing']))
    if evidence['installedSha256'] != pin['executableSha256']:
        raise ValueError('the installed relay agent executable hashes to %s, the lock pins %s for %s %s; '
                         'rebuild phase 62' % (evidence['installedSha256'], pin['executableSha256'], lock['version'], platform))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('fetch', 'record', 'gate'))
    parser.add_argument('--lock', type=Path)
    which = parser.add_mutually_exclusive_group()
    which.add_argument('--platform', choices=PLATFORMS)
    which.add_argument('--uname', help='the guest\'s `uname -sm` output')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--observed', type=Path, help='record: what the extraction read in the guest')
    parser.add_argument('--receipt', type=Path, help='gate: the work image\'s acceptance receipt')
    args = parser.parse_args()
    try:
        if args.action == 'fetch':
            if not (args.lock and args.output and (args.platform or args.uname)):
                parser.error('fetch needs --lock, --output and --platform or --uname')
            platform = args.platform or platform_of(args.uname)
            team = os.environ.get(TEAM_VARIABLE) or None
            if team and not TEAM.fullmatch(team):
                parser.error('%s must be a team ID of ten capital letters and digits' % TEAM_VARIABLE)
            print(json.dumps(fetch(args.lock, platform, args.output, args.archive, team=team)))
        elif args.action == 'record':
            if not (args.observed and args.output):
                parser.error('record needs --observed and --output')
            record(args.observed, args.output)
        else:
            if not (args.lock and args.receipt):
                parser.error('gate needs --lock and --receipt')
            evidence = gate(args.lock, args.receipt)
            print('relay agent %s %s: the pinned release' % (evidence['archive']['version'], evidence['platform']))
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.exit('relay agent: %s' % error)


if __name__ == '__main__':
    main()
