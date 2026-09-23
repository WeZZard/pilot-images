#!/usr/bin/env python3
"""Acquire or extract the checksum-pinned official Linux capture archive.

This helper never executes downloaded files. Guest installation and runtime
acceptance are separate image-build steps. No upstream installer is executed.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import tarfile
import tempfile
import urllib.parse
import urllib.request

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXTRACTED = 256 * 1024 * 1024
REQUIRED = {'cua-driver', 'cua-cursor-theme', 'libcua_driver_sdk.so', 'cua_driver_node_runtime.node', 'cua_driver_abi.h'}


def read_lock(path):
    lock = json.loads(Path(path).read_text())
    fields = {'schemaVersion', 'version', 'os', 'architecture', 'url', 'sha256', 'sourceCommit', 'checksumUrl', 'upstreamStatus'}
    if set(lock) != fields or lock['schemaVersion'] != 1 or lock['os'] != 'linux' or lock['architecture'] != 'arm64':
        raise ValueError('invalid Linux arm64 capture lock')
    if not re.fullmatch(r'\d+\.\d+\.\d+', lock['version']) or not re.fullmatch(r'[0-9a-f]{64}', lock['sha256']) or not re.fullmatch(r'[0-9a-f]{40}', lock['sourceCommit']):
        raise ValueError('invalid capture version or digest')
    release = 'https://github.com/trycua/cua/releases/download/cua-driver-rs-v' + lock['version'] + '/'
    expected = release + 'cua-driver-rs-' + lock['version'] + '-linux-arm64-binary.tar.gz'
    if lock['url'] != expected or lock['checksumUrl'] != release + 'checksums.txt':
        raise ValueError('capture lock is not an official pinned release URL')
    return lock


def inspect_archive(data, lock):
    if len(data) > MAX_ARCHIVE or hashlib.sha256(data).hexdigest() != lock['sha256']:
        raise ValueError('capture archive SHA256 mismatch or size exceeded')
    archive = tarfile.open(fileobj=io.BytesIO(data), mode='r:gz')
    names = set()
    total = 0
    for member in archive:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or str(path) != member.name or '\\' in member.name or any(ord(c) < 32 for c in member.name):
            raise ValueError('unsafe archive path')
        if member.name in names or not (member.isfile() or member.isdir()):
            raise ValueError('duplicate, linked or special archive entry')
        names.add(member.name)
        total += member.size
        if len(names) > 100 or total > MAX_EXTRACTED:
            raise ValueError('capture extraction exceeds bounds')
    if not REQUIRED <= names:
        raise ValueError('capture archive lacks required companion files')
    for name in ('cua-driver', 'cua-cursor-theme', 'libcua_driver_sdk.so', 'cua_driver_node_runtime.node'):
        stream = archive.extractfile(name)
        header = stream.read(20) if stream else b''
        if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != 183:
            raise ValueError('capture binary is not native ELF64 AArch64: ' + name)
    return archive


def fetch(lock_path, output, local_archive=None, opener=urllib.request.urlopen):
    lock = read_lock(lock_path)
    if local_archive:
        with Path(local_archive).open('rb') as stream:
            data = stream.read(MAX_ARCHIVE + 1)
    else:
        request = urllib.request.Request(lock['url'], headers={'User-Agent': 'pilot-images-pinned-capture'})
        with opener(request, timeout=120) as stream:
            final = urllib.parse.urlsplit(stream.geturl())
            if final.scheme != 'https' or final.hostname not in ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
                raise ValueError('capture download redirected outside official HTTPS asset hosts')
            data = stream.read(MAX_ARCHIVE + 1)
    with inspect_archive(data, lock):
        pass
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
    return lock


def extract(lock_path, source, destination):
    lock = read_lock(lock_path)
    with Path(source).open('rb') as stream:
        data = stream.read(MAX_ARCHIVE + 1)
    # Build in a new directory. Never extract over existing paths or follow links.
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('capture extraction destination must be new')
    with inspect_archive(data, lock) as archive:
        destination.mkdir(parents=True, mode=0o755)
        try:
            for member in archive:
                target = destination / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source_stream, target.open('xb') as output:
                        shutil.copyfileobj(source_stream, output)
                    target.chmod(0o755 if member.name in ('cua-driver', 'cua-cursor-theme', 'wayland-helper/install.sh') else 0o644)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return lock


def main():
    # This verifier is also staged alone into the guest. Host composition is
    # required only when a host profile was explicitly selected.
    if 'VM_ENVIRONMENT_FILE' in os.environ:
        from environment import initialize
        initialize()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fetch', 'extract'))
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.action == 'fetch':
        result = fetch(args.lock, args.output, args.archive)
    else:
        if not args.archive:
            parser.error('extract requires --archive')
        result = extract(args.lock, args.archive, args.output)
    print(json.dumps({'version': result['version'], 'sha256': result['sha256'], 'architecture': result['architecture'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
