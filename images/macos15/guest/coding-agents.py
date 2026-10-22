#!/usr/bin/python3
"""Install and verify the coding agents pinned in coding-agents.lock.json.

Phase 85 runs `install`; checks/acceptance.zsh runs `verify`. Stdlib only, and
written for the system /usr/bin/python3 so that neither pyenv nor Homebrew
decides which interpreter provisions the image.

Every agent is pinned: an exact npm or PyPI version, or a download URL with its
sha256. Homebrew is not used: its formula metadata comes from whatever API cache
the image holds, so a formula version cannot be pinned. Nothing here
signs in, and no agent is started except to print its version, with stdin
closed so a prompt cannot wait for an answer.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HOME = pathlib.Path.home()
LOCAL_BIN = HOME / '.local/bin'
AGENTS_ROOT = HOME / '.local/share/pilot-agents'
DOWNLOADS = pathlib.Path('/var/tmp/pilot-agents-download')
ZSHENV = HOME / '.zshenv'
ENV_MARK = '# pilot-coding-agents'


def log(message):
    print('[agents] ' + message, flush=True)


def expand(path):
    return pathlib.Path(os.path.expanduser(path))


def run(argv, env=None, check=True, timeout=1800):
    merged = dict(os.environ)
    merged.update(env or {})
    result = subprocess.run(argv, env=merged, timeout=timeout,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    if check and result.returncode != 0:
        raise SystemExit('command failed (%d): %s\n%s' % (result.returncode, ' '.join(argv), result.stdout[-4000:]))
    return result


def agent_env(lock):
    """Every agent's updater switch that is an environment variable."""
    result = {}
    for agent in lock['agents']:
        for action in agent.get('updates', []):
            result.update(action.get('env', {}))
    return result


def bounded(argv, env, timeout):
    """Run a version probe in its own process group and kill whatever it left."""
    merged = dict(os.environ)
    merged.update(env)
    merged['CI'] = merged.get('CI', '1')
    merged['NO_COLOR'] = '1'
    with tempfile.TemporaryFile() as out:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                   env=merged, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        out.seek(0)
        return code, out.read(16384).decode(errors='replace')


# --- updater switches ------------------------------------------------------------

def deep_merge(target, values):
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def deep_contains(target, values):
    for key, value in values.items():
        if key not in target:
            return False
        if isinstance(value, dict):
            if not isinstance(target[key], dict) or not deep_contains(target[key], value):
                return False
        elif target[key] != value:
            return False
    return True


def read_json(path):
    if not path.exists():
        return {}
    text = path.read_text()
    if not text.strip():
        return {}
    # VS Code settings allow comments; the image writes none, so plain JSON is enough.
    return json.loads(text)


def toml_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


def toml_lines(table, values):
    return ([] if table is None else ['[' + table + ']']) + [k + ' = ' + toml_value(v) for k, v in values.items()]


def write_toml(path, table, values):
    """Set keys in one table of a small TOML file without a TOML library."""
    lines = path.read_text().splitlines() if path.exists() else []
    header = None if table is None else '[' + table + ']'
    for key, value in values.items():
        wanted = key + ' = ' + toml_value(value)
        start = 0
        if header is not None:
            if header not in lines:
                lines += ([''] if lines else []) + [header]
            start = lines.index(header) + 1
        end = len(lines)
        for i in range(start, len(lines)):
            if lines[i].startswith('['):
                end = i
                break
        for i in range(start, end):
            if re.match(r'\s*' + re.escape(key) + r'\s*=', lines[i]):
                lines[i] = wanted
                break
        else:
            lines.insert(end if header is not None else 0, wanted)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')


def toml_contains(path, table, values):
    if not path.exists():
        return False
    current = None
    found = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith('['):
            current = line.strip('[]').strip()
            continue
        if current == table and '=' in line:
            key, _, value = line.partition('=')
            found[key.strip()] = value.strip()
    return all(found.get(k) == toml_value(v) for k, v in values.items())


def write_env(lock):
    """One marked block in ~/.zshenv carries every env-var updater switch."""
    lines = ZSHENV.read_text().splitlines() if ZSHENV.exists() else []
    lines = [l for l in lines if not l.endswith(ENV_MARK)]
    for key, value in sorted(agent_env(lock).items()):
        lines.append('export %s=%s %s' % (key, value, ENV_MARK))
    ZSHENV.write_text('\n'.join(lines) + '\n')


def apply_updates(agent, env):
    for action in agent.get('updates', []):
        if 'json' in action:
            path = expand(action['json']['path'])
            data = read_json(path)
            deep_merge(data, action['json']['set'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + '\n')
        elif 'toml' in action:
            spec = action['toml']
            write_toml(expand(spec['path']), spec['table'], spec['set'])
        elif 'command' in action:
            result = run(action['command'], env=env, check=False, timeout=120)
            if result.returncode != 0:
                raise SystemExit('%s: %s failed:\n%s' % (agent['id'], ' '.join(action['command']), result.stdout[-2000:]))


def check_updates(agent, zshenv):
    """Yield (ok, description) for each updater switch the lock declares."""
    for action in agent.get('updates', []):
        if 'env' in action:
            for key, value in action['env'].items():
                yield ('export %s=%s %s' % (key, value, ENV_MARK)) in zshenv, '%s=%s in ~/.zshenv' % (key, value)
        elif 'json' in action:
            spec = action['json']
            try:
                ok = deep_contains(read_json(expand(spec['path'])), spec['set'])
            except ValueError:
                ok = False
            yield ok, '%s sets %s' % (spec['path'], json.dumps(spec['set'], sort_keys=True))
        elif 'toml' in action:
            spec = action['toml']
            yield toml_contains(expand(spec['path']), spec['table'], spec['set']), \
                '%s [%s] sets %s' % (spec['path'], spec['table'] or '', json.dumps(spec['set'], sort_keys=True))
        elif 'command' in action:
            # A command-written switch is verified by the file it leaves behind,
            # declared beside it, so acceptance never re-runs the agent's own CLI.
            for check in action.get('verify', []):
                path = expand(check['path'])
                ok = path.exists() and check['contains'] in path.read_text()
                yield ok, '%s contains %s' % (check['path'], check['contains'])


# --- downloads -----------------------------------------------------------------

def fetch(agent):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    name = agent['id'] + '-' + re.sub(r'[^A-Za-z0-9._-]', '_', agent['version']) + '.' + agent.get('format', 'download')
    path = DOWNLOADS / name
    for attempt in (1, 2):
        if not path.exists():
            log('downloading %s %s' % (agent['id'], agent['url']))
            run(['curl', '-fL', '--retry', '5', '--retry-delay', '10', '--retry-all-errors', '-sS',
                 '-o', str(path), agent['url']], timeout=3600)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
        if digest.hexdigest() == agent['sha256']:
            return path
        path.unlink()
        if attempt == 2:
            raise SystemExit('%s: sha256 mismatch for %s: %s != %s' % (agent['id'], agent['url'], digest.hexdigest(), agent['sha256']))


def link(name, target):
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    path = LOCAL_BIN / name
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to(target)


def install_archive(agent):
    archive = fetch(agent)
    root = AGENTS_ROOT / agent['id'] / agent['version']
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    if agent['format'] == 'binary':
        target = root / next(iter(agent['links'].values()))
        shutil.copyfile(archive, target)
    elif agent['format'] == 'zip':
        run(['ditto', '-x', '-k', str(archive), str(root)])
    else:
        run(['tar', '-xf', str(archive), '-C', str(root)])
    for name, relative in agent['links'].items():
        target = root / relative
        if not target.is_file():
            raise SystemExit('%s: %s is not in the archive' % (agent['id'], relative))
        target.chmod(target.stat().st_mode | 0o755)
        link(name, target)
    # Earlier pinned versions are removed so only the lock's version remains.
    for old in (AGENTS_ROOT / agent['id']).iterdir():
        if old.name != agent['version']:
            shutil.rmtree(old)


def install_script(agent, env):
    """A vendor installer, itself pinned by sha256, told which release to install."""
    script = fetch(agent)
    run(['bash', str(script)] + agent['args'], env={**env, **agent.get('installEnv', {})}, timeout=3600)
    for name, target in agent.get('links', {}).items():
        link(name, expand(target))


def install_npm_node(agent, env):
    """An npm package that needs a newer Node than the image's, with its own pinned Node."""
    root = AGENTS_ROOT / agent['id'] / agent['version']
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    node = fetch(dict(agent, url=agent['node']['url'], sha256=agent['node']['sha256'], format='tar',
                      version='node-' + agent['node']['version']))
    run(['tar', '-xf', str(node), '-C', str(root), '--strip-components', '1'])
    path = '%s:%s' % (root / 'bin', os.environ.get('PATH', ''))
    run([str(root / 'bin/npm'), 'install', '-g', '--prefix', str(root / 'prefix'),
         '%s@%s' % (agent['package'], agent['version'])], env={**env, 'PATH': path})
    entry = root / 'prefix/lib/node_modules' / agent['package'] / agent['entry']
    wrapper = root / ('bin-' + agent['bin'])
    wrapper.write_text('#!/bin/sh\n# %s runs on its own Node %s (the image runtime is older).\n'
                       'PATH="%s/bin:$PATH" exec "%s/bin/node" "%s" "$@"\n'
                       % (agent['name'], agent['node']['version'], root, root, entry))
    wrapper.chmod(0o755)
    link(agent['bin'], wrapper)
    for old in (AGENTS_ROOT / agent['id']).iterdir():
        if old.name != agent['version']:
            shutil.rmtree(old)


def npm_node_version(agent):
    package = AGENTS_ROOT / agent['id'] / agent['version'] / 'prefix/lib/node_modules' / agent['package'] / 'package.json'
    try:
        return json.loads(package.read_text()).get('version')
    except (OSError, ValueError):
        return None


def plist_value(app, key):
    result = run(['/usr/libexec/PlistBuddy', '-c', 'Print :' + key, str(app / 'Contents/Info.plist')], check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def install_app(agent):
    archive = fetch(agent)
    destination = pathlib.Path('/Applications') / agent['app']
    with tempfile.TemporaryDirectory(prefix='pilot-agent-') as work:
        work = pathlib.Path(work)
        mount = None
        try:
            if agent['format'] == 'dmg':
                mount = work / 'mount'
                mount.mkdir()
                run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', str(mount), str(archive)])
                source = mount / agent['app']
            else:
                run(['ditto', '-x', '-k', str(archive), str(work / 'expanded')])
                source = work / 'expanded' / agent['app']
            if not source.is_dir():
                raise SystemExit('%s: %s is not in the download' % (agent['id'], agent['app']))
            check = run(['codesign', '--verify', '--deep', '--strict', str(source)], check=False)
            if check.returncode != 0:
                raise SystemExit('%s: signature does not verify:\n%s' % (agent['id'], check.stdout))
            run(['sudo', 'rm', '-rf', str(destination)])
            run(['sudo', 'ditto', str(source), str(destination)])
        finally:
            if mount is not None:
                run(['hdiutil', 'detach', '-force', str(mount)], check=False)
    user = run(['id', '-un']).stdout.strip()
    run(['sudo', 'chown', '-R', user + ':admin', str(destination)])
    run(['sudo', 'xattr', '-dr', 'com.apple.quarantine', str(destination)], check=False)
    have = plist_value(destination, 'CFBundleIdentifier')
    if have != agent['bundleId']:
        raise SystemExit('%s: bundle id %s, expected %s' % (agent['id'], have, agent['bundleId']))
    version = plist_value(destination, 'CFBundleShortVersionString')
    if version != agent['bundleVersion']:
        raise SystemExit('%s: bundle version %s, expected %s' % (agent['id'], version, agent['bundleVersion']))
    for name, relative in agent['links'].items():
        target = destination / relative
        if not os.access(target, os.X_OK):
            raise SystemExit('%s: %s is not executable' % (agent['id'], target))
        link(name, target)


def npm_version(package):
    result = run(['npm', 'ls', '-g', '--json', '--depth=0', package], check=False)
    try:
        return json.loads(result.stdout).get('dependencies', {}).get(package, {}).get('version')
    except ValueError:
        return None


def npm_bin_dir():
    return pathlib.Path(run(['npm', 'prefix', '-g']).stdout.strip()) / 'bin'


def uv_version(package):
    result = run(['uv', 'tool', 'list'], check=False)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == package:
            return parts[1].lstrip('v')
    return None


def install(agent, env):
    method = agent['method']
    if method == 'npm':
        run(['npm', 'install', '-g', '%s@%s' % (agent['package'], agent['version'])], env={**env, **agent.get('installEnv', {})})
        have = npm_version(agent['package'])
        if have != agent['version']:
            raise SystemExit('%s: npm reports %s, expected %s' % (agent['id'], have, agent['version']))
        for name in agent.get('dropBins', []):
            path = npm_bin_dir() / name
            if path.is_symlink():
                path.unlink()
    elif method == 'uv':
        run(['uv', 'tool', 'install', '--force', '--python', agent['python'], agent['spec']], env=env)
        have = uv_version(agent['package'])
        if have != agent['version']:
            raise SystemExit('%s: uv reports %s, expected %s' % (agent['id'], have, agent['version']))
    elif method == 'archive':
        install_archive(agent)
    elif method == 'script':
        install_script(agent, env)
    elif method == 'npm-node':
        install_npm_node(agent, env)
    elif method == 'app':
        install_app(agent)
    else:
        raise SystemExit('%s: unknown method %s' % (agent['id'], method))
    apply_updates(agent, env)


def installed_version(agent):
    method = agent['method']
    if method == 'npm':
        return npm_version(agent['package'])
    if method == 'uv':
        return uv_version(agent['package'])
    if method == 'archive':
        root = AGENTS_ROOT / agent['id'] / agent['version']
        ok = root.is_dir() and all((LOCAL_BIN / n).resolve() == (root / r).resolve() for n, r in agent['links'].items())
        return agent['version'] if ok else None
    if method == 'app':
        return plist_value(pathlib.Path('/Applications') / agent['app'], 'CFBundleShortVersionString')
    if method == 'npm-node':
        return npm_node_version(agent)
    if method == 'script':
        # The installer's own record of what it installed is the version probe below.
        return agent['version'] if all(shutil.which(n) for n in [agent['bin']] + list(agent.get('links', {}))) else None


def expected_installed(agent):
    return agent['bundleVersion'] if agent['method'] == 'app' else agent['version']


def version_probe(agent, env):
    """The version invocation, stdin closed: a sign-in prompt is a timeout."""
    if agent.get('check') is None:
        return None
    code, output = bounded(agent['check'], env, agent.get('checkTimeout', 60))
    expect = agent.get('expect', agent['version'].split('+')[0] if agent['method'] != 'app' else agent['bundleVersion'])
    return code == 0 and expect in output, code, output


def verify(lock, env):
    failures = 0
    zshenv = ZSHENV.read_text() if ZSHENV.exists() else ''

    def report(ok, text):
        nonlocal failures
        print(('PASS  ' if ok else 'FAIL  ') + text, flush=True)
        failures += 0 if ok else 1

    for agent in lock['agents']:
        label = '%s %s' % (agent['name'], agent['version'])
        have = installed_version(agent)
        report(have == expected_installed(agent), '%s installed (%s: %s)' % (label, agent['method'], have))
        if agent['method'] == 'app':
            app = pathlib.Path('/Applications') / agent['app']
            report(plist_value(app, 'CFBundleIdentifier') == agent['bundleId'], '%s bundle id %s' % (label, agent['bundleId']))
            quarantined = run(['xattr', '-p', 'com.apple.quarantine', str(app)], check=False).returncode == 0
            report(not quarantined, '%s not quarantined' % label)
        for name in sorted(set(list(agent.get('links', {})) + ([agent['bin']] if agent['method'] in ('npm', 'uv', 'npm-node', 'script') else []))):
            report(shutil.which(name) is not None, '%s command %s on PATH' % (label, name))
        probe = version_probe(agent, env)
        if probe is not None:
            ok, code, output = probe
            tail = ' '.join(output.split())[-160:]
            report(ok, '%s prints its version without a prompt (%s -> %s: %s)' % (label, ' '.join(agent['check']), code, tail))
        for ok, text in check_updates(agent, zshenv):
            report(ok, '%s updater off: %s' % (label, text))
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['install', 'verify', 'list'])
    parser.add_argument('--lock', default=str(pathlib.Path(__file__).with_name('coding-agents.lock.json')))
    parser.add_argument('--only', action='append', default=[])
    args = parser.parse_args()
    lock = json.loads(pathlib.Path(args.lock).read_text())
    if args.only:
        lock = {**lock, 'agents': [a for a in lock['agents'] if a['id'] in args.only]}
    env = agent_env(json.loads(pathlib.Path(args.lock).read_text()))
    if args.command == 'list':
        for agent in lock['agents']:
            print(agent['id'], agent['method'], agent['version'])
        return 0
    if args.command == 'install':
        write_env(json.loads(pathlib.Path(args.lock).read_text()))
        for agent in lock['agents']:
            # A rerun (a resumed build, or host/refresh-base.zsh after its
            # `npm update -g`) reinstalls only what is not at the pinned version.
            if installed_version(agent) == expected_installed(agent):
                log('%s %s already installed' % (agent['id'], agent['version']))
                apply_updates(agent, env)
                continue
            log('installing %s %s (%s)' % (agent['id'], agent['version'], agent['method']))
            install(agent, env)
        shutil.rmtree(DOWNLOADS, ignore_errors=True)
        return 0
    return 1 if verify(lock, env) else 0


if __name__ == '__main__':
    sys.exit(main())
