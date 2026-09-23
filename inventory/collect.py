#!/usr/bin/env python3
"""Extract installed metadata, never install or launch applications.

Runner accepts argv and returns stdout text (raising on failure). `which` and
application roots are injectable; tests need not inspect the host. Only direct
.app children and direct Utilities children are scanned, not nested helper apps.
Null versions deduplicate with null only: null versus a known version is a
conflict, rather than guessing that two observations describe the same version.
Coverage excludes arbitrary copied binaries and non-global npm installations.
"""
import argparse
import datetime
import json
import os
import pathlib
import platform
import plistlib
import shutil
import subprocess
import sys

MAX_BYTES = 4 * 1024 * 1024
MAX_APPS = 20000


class ExtractionError(ValueError):
    pass


# Exact ECMAScript whitespace set; Python strip/isspace differ (NEL, FEFF).
_TEXT_WHITESPACE = frozenset('\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')


def text(value, limit, field):
    if (not isinstance(value, str) or not any(c not in _TEXT_WHITESPACE for c in value) or len(value) > limit
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise ExtractionError('invalid ' + field)
    return value


def record(source, identifier, name, version):
    if version is not None:
        text(version, 256, 'version')
    return dict(id=text(source + ':' + identifier, 128, 'id'),
                name=text(name, 256, 'name'), aliases=[], version=version)


def json_object(raw):
    try:
        def pairs(items):
            obj = {}
            for key, value in items:
                if key in obj:
                    raise ExtractionError('duplicate JSON key')
                obj[key] = value
            return obj
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, TypeError) as exc:
        raise ExtractionError('malformed JSON') from exc
    if not isinstance(value, dict):
        raise ExtractionError('expected JSON object')
    return value


def parse_dpkg(raw):
    result = []
    for line in raw.splitlines():
        parts = line.split('\t')
        if len(parts) != 3:
            raise ExtractionError('malformed dpkg record')
        status, name, version = parts
        if status == 'installed':
            result.append(record('dpkg', name, name, version))
        elif status not in {'not-installed', 'config-files', 'half-installed',
                            'unpacked', 'half-configured', 'triggers-awaited',
                            'triggers-pending'}:
            raise ExtractionError('unknown dpkg status')
    return result


def parse_snap(raw):
    lines = raw.splitlines()
    if not lines or lines[0].split() != ['Name', 'Version', 'Rev', 'Tracking', 'Publisher', 'Notes']:
        raise ExtractionError('malformed snap header')
    result = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 6:
            raise ExtractionError('malformed snap record')
        result.append(record('snap', fields[0], fields[0], fields[1]))
    return result


def parse_brew(raw):
    data = json_object(raw)
    result = []
    for group, key in [('formulae', 'name'), ('casks', 'token')]:
        entries = data.get(group)
        if not isinstance(entries, list):
            raise ExtractionError('malformed brew entries')
        for entry in entries:
            if not isinstance(entry, dict) or 'installed' not in entry:
                raise ExtractionError('malformed brew entry')
            identifier = text(entry.get(key), 128, 'brew identifier')
            installed = entry['installed']
            if group == 'formulae':
                if not isinstance(installed, list):
                    raise ExtractionError('malformed brew installed list')
                for item in installed:
                    if not isinstance(item, dict):
                        raise ExtractionError('malformed brew installed version')
                    result.append(record('brew-formula', identifier, identifier,
                                         text(item.get('version'), 256, 'version')))
            else:
                # cask `version` is available metadata, NOT installed state.
                if installed is not None:
                    result.append(record('brew-cask', identifier, identifier,
                                         text(installed, 256, 'installed cask version')))
    return result


def parse_npm(raw):
    data = json_object(raw)
    if data.get('error') or data.get('problems'):
        raise ExtractionError('npm reported errors')
    dependencies = data.get('dependencies', {})
    if not isinstance(dependencies, dict):
        raise ExtractionError('malformed npm dependencies')
    result = []
    for name, item in dependencies.items():
        if not isinstance(item, dict) or item.get('missing') or item.get('problems'):
            raise ExtractionError('malformed npm dependency')
        result.append(record('npm', name, name, item.get('version')))
    return result


def scan_bundles(roots):
    result = []
    for root in roots:
        root = pathlib.Path(root)
        if not root.is_dir():
            raise ExtractionError('required application root unavailable: ' + str(root))
        directories = [root]
        if (root / 'Utilities').exists():
            directories.append(root / 'Utilities')
        for directory in directories:
            for app in sorted(directory.iterdir()):
                if app.suffix != '.app' or not app.is_dir():
                    continue
                try:
                    with (app / 'Contents' / 'Info.plist').open('rb') as stream:
                        info = plistlib.load(stream)
                    if not isinstance(info, dict):
                        raise ExtractionError('invalid bundle metadata')
                    identifier = text(info.get('CFBundleIdentifier'), 128, 'bundle identifier')
                    name = info.get('CFBundleDisplayName') or info.get('CFBundleName') or app.stem
                    version = info.get('CFBundleShortVersionString', info.get('CFBundleVersion'))
                    result.append(record('bundle', identifier, name, version))
                except (OSError, ValueError, TypeError, OverflowError) as exc:
                    raise ExtractionError('invalid bundle: ' + str(app)) from exc
    return result


def normalize(observations, mappings):
    if not isinstance(mappings, dict):
        raise ExtractionError('aliases must be an object')
    for key, mapping in mappings.items():
        text(key, 128, 'mapping key')
        if ':' not in key or not isinstance(mapping, dict) or set(mapping) != {'id', 'name', 'aliases'}:
            raise ExtractionError('invalid alias mapping')
        text(mapping['id'], 128, 'mapped id')
        text(mapping['name'], 256, 'mapped name')
        if not isinstance(mapping['aliases'], list) or len(mapping['aliases']) > 16:
            raise ExtractionError('invalid aliases')
        for alias in mapping['aliases']:
            text(alias, 256, 'alias')
    result = {}
    for observation in observations:
        app = dict(observation)
        if app['id'] in mappings:
            app.update(mappings[app['id']])
        previous = result.get(app['id'])
        if previous is not None and previous != app:
            raise ExtractionError('conflicting observations for ' + app['id'])
        result[app['id']] = app
        if len(result) > MAX_APPS:
            raise ExtractionError('too many applications')
    return sorted(result.values(), key=lambda app: app['id'])


def run_command(argv):
    return subprocess.run(argv, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=120,
                          env={**os.environ, 'LC_ALL': 'C'}).stdout


def encode(document):
    data = (json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ExtractionError('inventory exceeds 4 MiB')
    return data


def collect(os_name, architecture, *, runner=run_command, which=shutil.which,
            roots=('/Applications', '/System/Applications'), mappings=None, now=None):
    if os_name not in {'linux', 'macos'} or architecture not in {'arm64', 'x86_64'}:
        raise ExtractionError('unsupported platform')
    observations, sources = [], []

    def manager(name, args, parser, required=False):
        executable = which(name)
        if not executable:
            if required:
                raise ExtractionError('required manager unavailable: ' + name)
            sources.append({'id': name, 'status': 'unavailable'})
            return
        try:
            observations.extend(parser(runner([executable] + args)))
        except Exception as exc:
            raise ExtractionError('extraction failed: ' + name) from exc
        sources.append({'id': name, 'status': 'available', 'command': [name] + args})

    if os_name == 'linux':
        manager('dpkg-query', ['-W', '-f=${db:Status-Status}\t${binary:Package}\t${Version}\n'], parse_dpkg, True)
        manager('snap', ['list'], parse_snap)
    else:
        try:
            observations.extend(scan_bundles(roots))
        except OSError as exc:
            raise ExtractionError('bundle extraction failed') from exc
        sources.append({'id': 'bundles', 'status': 'available', 'roots': [str(p) for p in roots]})
        manager('brew', ['info', '--json=v2', '--installed'], parse_brew)
    manager('npm', ['list', '--global', '--json', '--depth=0'], parse_npm)
    instant = now or datetime.datetime.now(datetime.timezone.utc)
    if instant.tzinfo is None:
        raise ExtractionError('collection timestamp must be timezone aware')
    document = dict(schemaVersion=1, os=os_name, architecture=architecture,
                    collectedAt=instant.astimezone(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
                    sources=sources, applications=normalize(observations, {} if mappings is None else mappings))
    encode(document)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aliases', type=pathlib.Path, default=pathlib.Path(__file__).with_name('aliases.json'))
    args = parser.parse_args()
    try:
        mappings = json_object(args.aliases.read_text(encoding='utf-8'))
        os_name = {'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system())
        architecture = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x86_64'}.get(platform.machine())
        sys.stdout.buffer.write(encode(collect(os_name, architecture, mappings=mappings)))
    except (ExtractionError, OSError) as exc:
        print('inventory extraction error: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
