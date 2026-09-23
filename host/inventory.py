#!/usr/bin/env python3
"""Pilot-owned publication writer (stdlib only).

Wire contract: ../mcp-vm-relay/docs/search-contract.md and vm-service's documented
publication schema. This is an independent producer, not an imported/vendored
backend. Fixture compatibility tests should accompany any schema change.
Commands never collect locally or boot VMs. Shell callers must establish stopped
state and exclusive maintenance ownership before bind/verify; stat is not a lock.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

LIMIT = 4 * 1024 * 1024


def state_directory(root, environ=None):
    """Shared with vm-service: canonical UTF-8 store path, full SHA-256 namespace."""
    env = os.environ if environ is None else environ
    home = Path(env.get('HOME', str(Path.home()))).expanduser()
    state = env.get('PILOT_IMAGES_STATE_DIR') or str(Path(env.get('XDG_STATE_HOME') or home / '.local/state') / 'pilot-images')
    canonical = str(Path(root).expanduser().resolve())
    return Path(state).expanduser().absolute() / 'stores' / hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def safe(path):
    path = Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink path refused')
    return path


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('invalid image/base key')
    return value


def read_json(path):
    path = safe(path)
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > LIMIT:
        raise ValueError('unsafe or oversized JSON')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate JSON key')
            result[k] = v
        return result
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('oversized JSON')
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def fields(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('invalid fields')


# Exact ECMAScript whitespace set; Python strip/isspace differ (NEL, FEFF).
_TEXT_WHITESPACE = frozenset('\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')


def text(value, limit=256):
    if type(value) is not str or not 0 < len(value) <= limit or not any(c not in _TEXT_WHITESPACE for c in value) or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError('invalid text')


def validate(value, kind):
    fields(value, ('schemaVersion', 'os', 'architecture', 'collectedAt', 'sources', 'applications'))
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['os'] != kind or kind not in ('macos', 'linux') or value['architecture'] not in ('arm64', 'x86_64'):
        raise ValueError('unsupported inventory platform/schema')
    stamp = value['collectedAt']
    text(stamp, 64)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', stamp) or datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('invalid timestamp')
    sources = value['sources']
    if type(sources) is not list or not 1 <= len(sources) <= 16:
        raise ValueError('invalid sources')
    seen = set()
    for source in sources:
        fields(source, ('id', 'status'), ('command', 'roots'))
        text(source['id'], 128)
        if source['id'] in seen or source['status'] not in ('available', 'unavailable'):
            raise ValueError('invalid/duplicate source')
        seen.add(source['id'])
        provenance = set(source) & {'command', 'roots'}
        if len(provenance) > 1 or (provenance and source['status'] != 'available'):
            raise ValueError('invalid provenance')
        for field in provenance:
            items = source[field]
            if type(items) is not list or not 1 <= len(items) <= 32:
                raise ValueError('invalid provenance list')
            for item in items:
                if type(item) is not str or not 0 < len(item) <= 4096 or '\x00' in item or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                    raise ValueError('invalid provenance text')
    apps = value['applications']
    if type(apps) is not list or len(apps) > 20000:
        raise ValueError('invalid applications')
    seen = set()
    for app in apps:
        fields(app, ('id', 'name', 'aliases', 'version'))
        text(app['id'], 128)
        text(app['name'])
        if app['version'] is not None:
            text(app['version'])
        if app['id'] in seen or type(app['aliases']) is not list or len(app['aliases']) > 16:
            raise ValueError('duplicate application or invalid aliases')
        seen.add(app['id'])
        for alias in app['aliases']:
            text(alias)
    return value


def fingerprint(root, vm, kind):
    directory = safe(Path(root).expanduser() / key(vm))
    if kind not in ('macos', 'linux') or not directory.is_dir():
        raise ValueError('invalid base')
    files = {}
    for name in ('config.json', 'disk.img', 'nvram.bin'):
        path = directory / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            if name == 'nvram.bin' and kind == 'linux':
                continue
            raise
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('nonregular base file')
        files[name] = {k: getattr(info, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')}
    return dict(base_vm=vm, path=str(directory.resolve()), files=files)


def invalidate(output):
    path = safe(output)
    path.unlink(missing_ok=True)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def hash_value(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('invalid SHA256')


def validate_portable(document, image, kind):
    fields(document, ('schemaVersion', 'image', 'inventory', 'provenance'))
    if type(document['schemaVersion']) is not int or document['schemaVersion'] != 1 or document['image'] != key(image):
        raise ValueError('portable identity mismatch')
    validate(document['inventory'], kind)
    provenance = document['provenance']
    fields(provenance, ('extractionMode', 'evidenceId', 'rawSha256', 'collectorSha256', 'aliasesSha256'))
    if provenance['extractionMode'] not in ('disposable-clone', 'work', 'base-maintenance'):
        raise ValueError('invalid extraction mode')
    key(provenance['evidenceId'])
    for name in ('rawSha256', 'collectorSha256', 'aliasesSha256'):
        hash_value(provenance[name])
    return document


def read_bytes(path):
    path = safe(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
        raise ValueError('unsafe or oversized file')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('oversized file')
    return raw


def portable_bytes(path, image, kind):
    raw = read_bytes(path)
    # read_json also rejects duplicate keys and non-finite JSON. Check replacement.
    validate_portable(read_json(path), image, kind)
    if raw != read_bytes(path):
        raise ValueError('portable changed during validation')
    return raw


def validate_association(document, image):
    fields(document, ('schemaVersion', 'image', 'base', 'inventorySha256'))
    if type(document['schemaVersion']) is not int or document['schemaVersion'] != 2 or document['image'] != key(image):
        raise ValueError('association identity mismatch')
    hash_value(document['inventorySha256'])
    base = document['base']
    fields(base, ('base_vm', 'path', 'files'))
    key(base['base_vm'])
    text(base['path'], 4096)
    if not Path(base['path']).is_absolute() or type(base['files']) is not dict or set(base['files']) not in ({'config.json', 'disk.img'}, {'config.json', 'disk.img', 'nvram.bin'}):
        raise ValueError('invalid base fingerprint')
    for values in base['files'].values():
        fields(values, ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'))
        for name, value in values.items():
            if type(value) is not int or not -(2**63) <= value < 2**64 or (name != 'st_mtime_ns' and value < 0):
                raise ValueError('invalid base stat')
    return document


def verify(document, root, vm, image, kind, portable):
    validate_association(document, image)
    raw = portable_bytes(portable, image, kind)
    before = fingerprint(root, vm, kind)
    if document['inventorySha256'] != digest(raw) or document['base'] != before:
        raise ValueError('inventory no longer matches stopped image')
    if raw != read_bytes(portable) or before != fingerprint(root, vm, kind):
        raise ValueError('pair changed during verification')
    return document


def atomic_write(output, encoded):
    if len(encoded) > LIMIT:
        raise ValueError('publication exceeds byte budget')
    output = safe(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def encode(document):
    return (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def observation(raw, image, kind, mode, evidence_id, collector, aliases):
    original = read_bytes(raw)
    inventory = validate(read_json(raw), kind)
    if original != read_bytes(raw):
        raise ValueError('raw changed during validation')
    document = dict(schemaVersion=1, image=key(image), inventory=inventory,
                    provenance=dict(extractionMode=mode, evidenceId=evidence_id,
                                    rawSha256=digest(original), collectorSha256=digest(read_bytes(collector)),
                                    aliasesSha256=digest(read_bytes(aliases))))
    return validate_portable(document, image, kind)


def bind(raw, output, root, vm, image, kind, previous=None, *, portable,
         mode=None, evidence_id=None, collector=None, aliases=None):
    # The association is invalidated BEFORE any validation and published LAST.
    invalidate(output)
    before = fingerprint(root, vm, kind)
    if previous is not None:
        encoded = portable_bytes(raw, image, kind)
        old = validate_association(read_json(previous), image)
        if old['inventorySha256'] != digest(encoded) or old['base']['files'] != before['files']:
            raise ValueError('renamed image differs from recorded work')
    else:
        encoded = encode(observation(raw, image, kind, mode, evidence_id, collector, aliases))
    document = dict(schemaVersion=2, image=key(image), base=before, inventorySha256=digest(encoded))
    try:
        if before != fingerprint(root, vm, kind):
            raise ValueError('base changed during association')
        atomic_write(portable, encoded)
        if before != fingerprint(root, vm, kind):
            raise ValueError('base changed before association publication')
        atomic_write(output, encode(document))
        if before != fingerprint(root, vm, kind) or encoded != read_bytes(portable):
            raise ValueError('pair changed after publication')
    except BaseException:
        invalidate(output)
        raise
    return document


def main():
    from environment import initialize, check_store_root
    initialize()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('state-path', 'invalidate', 'bind', 'verify'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--root', type=Path, default=Path(os.environ['TART_HOME']) / 'vms' if os.environ.get('VM_ENVIRONMENT_FILE') else Path.home() / '.tart/vms')
    parser.add_argument('--vm')
    parser.add_argument('--image')
    parser.add_argument('--os', choices=('linux', 'macos'))
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--portable', type=Path)
    parser.add_argument('--mode', choices=('disposable-clone', 'work', 'base-maintenance'))
    parser.add_argument('--evidence-id')
    parser.add_argument('--collector', type=Path)
    parser.add_argument('--aliases', type=Path)
    args = parser.parse_args()
    try:
        check_store_root(args.root)
        if args.action == 'state-path':
            print(state_directory(args.root))
            return
        if args.output is None:
            raise ValueError('--output is required')
        if args.action == 'invalidate':
            invalidate(args.output)
        elif args.action == 'verify':
            verify(read_json(args.output), args.root, args.vm, args.image, args.os, args.portable)
        else:
            bind(args.raw, args.output, args.root, args.vm, args.image, args.os, args.previous,
                 portable=args.portable, mode=args.mode, evidence_id=args.evidence_id,
                 collector=args.collector, aliases=args.aliases)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, 'inventory: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
