#!/usr/bin/env python3
"""Read-only selected-environment bootstrap; the trusted machctl owns resolution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
EXPORTS = {
    'PILOT_REPO': 'imageRepository',
    'TART_HOME': 'tartHome',
    'MACHINE_SERVICE_STATE': 'serviceStateDir',
    'PILOT_IMAGES_STATE_DIR': 'imageStateDir',
    'VM_RELAY_STATE_DIR': 'relayStateDir',
    'VM_RELAY_URL': 'vmServiceUrl',
    'MACHCTL': 'machctlPath',
    'TART': 'tartPath',
}
IDENTITY_FIELDS = ('id', 'vmServiceUrl', 'imageRepository', 'tartHome',
                   'serviceStateDir', 'imageStateDir', 'relayStateDir')
SCHEMA_VERSION = 2
SCHEMA_REFUSAL = ('selected environment profile must be schemaVersion 2 with machctlPath; '
                  'a schemaVersion 1 profile or one carrying vmctlPath is refused: '
                  'rename vmctlPath to machctlPath and set schemaVersion 2')


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def require_schema(profile):
    """Refuse the vmctl-era profile shape with its fix; there is no fallback.

    The renamed field raised the profile to schemaVersion 2 (machine-service
    DC-41, DC-42): a version 1 profile, or any profile still carrying
    vmctlPath, names machctlPath and version 2 rather than being read the old way.
    """
    if not isinstance(profile, dict):
        raise ValueError('environment profile must be a JSON object')
    version = profile.get('schemaVersion')
    if (isinstance(version, bool) or not isinstance(version, (int, float))
            or version != SCHEMA_VERSION or 'vmctlPath' in profile or 'machctlPath' not in profile):
        raise ValueError(SCHEMA_REFUSAL)


def executable(value):
    if (not isinstance(value, str) or '\x00' in value or not Path(value).is_absolute()
            or not Path(value).is_file() or not os.access(value, os.X_OK)):
        raise ValueError('selected executable must be an absolute executable file')
    return str(Path(value).resolve())


def resolve(environ=None, repository=REPO):
    """Return whitelisted exports without creating directories or mutating env."""
    env = dict(os.environ if environ is None else environ)
    selector = env.get('VM_ENVIRONMENT_FILE')
    if selector is None:
        return {}
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError('VM_ENVIRONMENT_FILE must not be blank')
    selected = Path(selector).expanduser().resolve(strict=True)
    if not selected.is_file() or selected.stat().st_size > 65536:
        raise ValueError('environment profile must be a regular JSON file under 64 KiB')
    # Only this bootstrap field is interpreted locally. The user trusts this CLI.
    with selected.open('rb') as stream:
        content = stream.read(65537)
    if len(content) > 65536:
        raise ValueError('environment profile exceeds 64 KiB')
    bootstrap = decode(content.decode('utf-8'))
    require_schema(bootstrap)
    machctl = executable(bootstrap['machctlPath'])
    env['VM_ENVIRONMENT_FILE'] = str(selected)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([machctl, 'environment', '--json'], env=env,
                            check=True, text=True, capture_output=True, timeout=30)
    if len(result.stdout.encode('utf-8')) > 1024 * 1024:
        raise ValueError('environment resolver output exceeds bound')
    document = decode(result.stdout)
    if not isinstance(document, dict) or set(document) != {'profile', 'identity', 'environment'}:
        raise ValueError('invalid machctl environment response')
    profile, identity, exported = (document[k] for k in ('profile', 'identity', 'environment'))
    if not all(isinstance(value, dict) for value in (profile, identity, exported)):
        raise ValueError('invalid machctl environment objects')
    require_schema(profile)
    if profile.get('imageRepository') != str(Path(repository).resolve()):
        raise ValueError('selected imageRepository differs from this checkout; invoke that checkout\'s script')
    expected_identity = {key: profile[key] for key in IDENTITY_FIELDS}
    expected_identity['fingerprint'] = hashlib.sha256(json.dumps(
        profile, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    if identity != expected_identity:
        raise ValueError('inconsistent selected environment identity')
    if profile['machctlPath'] != machctl:
        raise ValueError('resolver changed the trusted machctl executable')
    executable(profile['tartPath'])
    url = urlsplit(profile['vmServiceUrl'])
    expected = {key: profile[field] for key, field in EXPORTS.items()}
    expected.update(VM_ENVIRONMENT_FILE=str(selected), VM_ENVIRONMENT_FINGERPRINT=identity['fingerprint'],
                    MACHINE_SERVICE_HOST=url.hostname, MACHINE_SERVICE_PORT=str(url.port))
    if exported != expected or any(not isinstance(v, str) or '\x00' in v for v in exported.values()):
        raise ValueError('inconsistent or non-whitelisted selected environment exports')
    return exported


def check_store_root(root):
    """Reject an explicit CLI root that would bypass the selected Tart store."""
    if os.environ.get('VM_ENVIRONMENT_FILE') and root is not None:
        expected = (Path(os.environ['TART_HOME']) / 'vms').resolve()
        if Path(root).expanduser().resolve() != expected:
            raise ValueError('--root differs from the selected Tart store')


def initialize():
    """Compose process configuration at command startup, never on import."""
    exported = resolve()
    os.environ.update(exported)
    return exported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', action='store_true')
    args = parser.parse_args()
    try:
        exported = resolve()
        if args.shell:
            for key, value in sorted(exported.items()):
                print('export ' + key + '=' + shlex.quote(value))
        else:
            print(json.dumps(exported, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'selected environment refused: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
