#!/usr/bin/env python3
"""Find the newest release of every pinned piece of software and move the pins.

    python3 host/update-software.py check [line ...]   # report, change nothing
    python3 host/update-software.py apply [line ...]   # rewrite the pins

Lines default to every macOS line with a line.conf. The pins it reads and writes:

- images/<line>/line.conf: PYTHON_VERSION (the newest patch of the same minor
  that the newest pyenv release can build) and NVM_VERSION. Xcode and the Node
  major are reported only: a new Xcode needs its xip staged by hand, and a new
  Node major is a decision, not an update.
- images/<line>/seed.lock: the digest of the seed's tag.
- images/<line>/guest/unity.lock: the newest editor in the pinned LTS stream.
- guest/coding-agents.lock.json (one file, identical on every macOS line): each
  agent's version, and for vendor downloads its URL, sha256, bundle version and
  probe output, then `resolvedBefore`, the README table row and the agent's
  applications/<id>/PLAN.md.

Floating software (Homebrew, rustup, Codex, Pi, Claude Code, pnpm, the npx MCP
servers) has no pin: a rebuild installs the newest release.

How an agent's newest release is found, by convention first:

- npm, npm-node and uv agents: the registry's latest version.
- A download from github.com/<owner>/<repo>/releases/download/...: the newest
  published release that carries the same asset name with the new version.
- Anything else names its feed in the lock entry's `release` object:
    {"feed": "json" | "text" | "redirect" | "github" | "none",
     "url": <feed URL>,
     "pick": {<value>: <selector>, ...},   # read in order; may use earlier values
     "download": <URL template>,           # optional; also parses the old URL
     "expect": <template>}                 # optional; the probe's new output
  A json selector is a dotted path (`a.b.0.c`, `list[key=value].c`); a text or
  redirect selector is a regular expression whose named groups become values,
  and the match with the newest `version` wins. Every value except `url` and
  `sha256` is also replaced, old for new, in the entry's other strings (links,
  args, expect). A `none` feed carries a `reason`.

Every new download is fetched once into ~/.cache/pilot-images/downloads, hashed,
and read, never run: an archive must contain every link target, and an app
bundle must carry the lock's bundle id. Its CFBundleShortVersionString becomes
`bundleVersion`, and a VS Code fork's product.json commit becomes `commit`.
A probe output that no rule derives is kept and listed under "probe after the
rebuild": phase 85's verify prints the real output.
"""
import datetime
import hashlib
import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

REPO = pathlib.Path(__file__).resolve().parents[1]
LOCK_NAME = 'guest/coding-agents.lock.json'
CACHE = pathlib.Path(os.environ.get('XDG_CACHE_HOME', pathlib.Path.home() / '.cache')) / 'pilot-images/downloads'
UA = {'User-Agent': 'pilot-images-update-software'}


# --- versions --------------------------------------------------------------------

def vkey(version):
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'[.\-_+]', str(version))]


def newer(latest, have):
    return latest is not None and vkey(latest) > vkey(have)


def bare(version):
    return re.sub(r'^v(?=\d)', '', str(version))


# --- network ---------------------------------------------------------------------

def http(url, method='GET', redirect=True):
    request = urllib.request.Request(url, method=method, headers=UA)
    opener = urllib.request.build_opener() if redirect else urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=120) as response:
        return response.status, dict(response.headers), response.read()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def get_text(url):
    return http(url)[2].decode()


def get_json(url):
    return json.loads(get_text(url))


def location(url):
    try:
        http(url, redirect=False)
    except urllib.error.HTTPError as error:
        if error.code in (301, 302, 303, 307, 308):
            return error.headers['Location']
        raise
    raise SystemExit('%s: no redirect' % url)


def gh(path):
    result = subprocess.run(['gh', 'api', '--paginate', '--slurp', path], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('gh api %s: %s' % (path, result.stderr.strip()))
    pages = json.loads(result.stdout)
    return [item for page in pages for item in page] if pages and isinstance(pages[0], list) else pages[0]


def download(url):
    """Fetch once into the cache; return the path. The file is data, never run."""
    folder = CACHE / hashlib.sha256(url.encode()).hexdigest()[:24]
    target = folder / (urllib.parse.unquote(url.rsplit('/', 1)[-1]) or 'download')
    if not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.partial')
        request = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(request, timeout=600) as response, open(partial, 'wb') as out:
            shutil.copyfileobj(response, out, 1 << 20)
            expected = response.headers.get('Content-Length')
        # A dropped connection can end the read without an error (seen 2026-11-01).
        if expected is not None and partial.stat().st_size != int(expected):
            got = partial.stat().st_size
            partial.unlink()
            raise SystemExit('%s: got %d of %s bytes' % (url, got, expected))
        partial.rename(target)
    return target


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


# --- feeds -------------------------------------------------------------------------

def json_path(data, path, values):
    for part in (fill(p, values) for p in path.split('.')):
        filtered = re.fullmatch(r'(.*)\[(.+)=(.*)\]', part)
        if filtered:
            name, key, value = filtered.groups()
            data = data[name] if name else data
            data = next(item for item in data if str(item.get(key)) == value)
        elif isinstance(data, list):
            data = data[int(part)]
        else:
            data = data[part]
    return data


def fill(template, values):
    return template.format(**values) if template else None


def template_regex(template):
    parts = re.split(r'\{(\w+)\}', template)
    return '^' + ''.join(re.escape(p) if i % 2 == 0 else '(?P<%s>.+?)' % p for i, p in enumerate(parts)) + '$'


def parse(template, url):
    """The values a URL template held in an old URL, or {} when it does not fit."""
    if not template:
        return {}
    match = re.match(template_regex(template), url) or re.match(template_regex(template), urllib.parse.unquote(url))
    return match.groupdict() if match else {}


def regex_values(pattern, text):
    matches = [m.groupdict() for m in re.finditer(pattern, text, re.M)]
    if not matches:
        raise SystemExit('no match for %r' % pattern)
    return max(matches, key=lambda m: vkey(bare(m.get('version', ''))))


def normalized(values):
    out = dict(values)
    if 'version' in out:
        out['version'] = bare(out['version'])
    if out.get('sha256'):
        out['sha256'] = out['sha256'].removeprefix('sha256:')
    return out


def feed_json(release):
    data, values = get_json(release['url']), {}
    for name, path in release['pick'].items():
        values[name] = json_path(data, path, normalized(values))
    return values


def feed_text(release):
    text = get_text(release['url'])
    values = {}
    for pattern in release.get('pick', {'version': r'^\s*(?P<version>\S+)\s*$'}).values():
        values.update(regex_values(pattern, text))
    return values


def feed_redirect(release):
    url = location(release['url'])
    values = {'url': url}
    for pattern in release['pick'].values():
        values.update(regex_values(pattern, url))
    return values


GITHUB_ASSET = re.compile(r'^https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/([^/]+)$')


def feed_github(release, agent):
    repo = release.get('repo') or GITHUB_ASSET.match(agent['url']).group(1)
    # Newest published first: a vendor that changed version schemes keeps its old tags.
    releases = sorted((r for r in gh('repos/%s/releases?per_page=100' % repo)
                       if not r['draft'] and not r['prerelease'] and re.match(r'v?\d', r['tag_name'])),
                      key=lambda r: r['published_at'] or '', reverse=True)
    if release.get('download'):
        tag = releases[0]['tag_name']
        commit = gh('repos/%s/commits/%s' % (repo, tag))['sha']
        return {'version': tag, 'tag': tag, 'commit': commit}
    _, old_tag, old_asset = GITHUB_ASSET.match(agent['url']).groups()
    for candidate in releases:
        version = bare(candidate['tag_name'])
        name = old_asset.replace(agent['version'], version)
        asset = next((a for a in candidate['assets'] if a['name'] == name), None)
        if asset:
            return {'version': version, 'url': asset['browser_download_url'], 'sha256': asset.get('digest')}
    raise SystemExit('%s: no release of %s carries an asset like %s' % (agent['id'], repo, old_asset))


def release_of(agent):
    if 'release' in agent:
        return agent['release']
    if GITHUB_ASSET.match(agent.get('url', '')):
        return {'feed': 'github'}
    return {'feed': 'none', 'reason': 'no release feed in the lock'}


def vendor_latest(agent):
    release = release_of(agent)
    feed = release['feed']
    if feed == 'none':
        return None
    if feed == 'github':
        return normalized(feed_github(release, agent))
    values = normalized({'json': feed_json, 'text': feed_text, 'redirect': feed_redirect}[feed](release))
    if 'version' not in values and release.get('download') and values.get('url'):
        values.update(normalized(parse(release['download'], values['url'])))
    return values


def npm_latest(package):
    data = get_json('https://registry.npmjs.org/' + package.replace('/', '%2F'))
    version = data['dist-tags']['latest']
    return {'version': version, 'published': data['time'][version]}


def pypi_latest(package):
    data = get_json('https://pypi.org/pypi/%s/json' % package)
    version = data['info']['version']
    return {'version': version, 'published': data['releases'][version][0]['upload_time_iso_8601'],
            'requires_python': data['info'].get('requires_python') or ''}


def python_allowed(minor, requires):
    """Whether Python <minor> (e.g. '3.13') meets a Requires-Python like '>=3.14,<3.15'."""
    have = vkey(minor)
    for clause in filter(None, (c.strip() for c in requires.split(','))):
        op, version = re.match(r'(~=|==|!=|>=|<=|>|<)\s*([\d.*]+)', clause).groups()
        if version.endswith('.*'):
            same = vkey(minor)[:len(vkey(version[:-2]))] == vkey(version[:-2])
            if (op == '==') != same:
                return False
            continue
        want = vkey('.'.join(version.split('.')[:2]))
        ok = {'>=': have >= want, '>': have > want or (have == want and version.count('.') > 1),
              '<=': have <= want, '<': have < want, '==': have == want, '!=': True,
              '~=': have >= want}[op]
        if not ok:
            return False
    return True


def python_for(current, requires):
    """The lock's python, moved to the oldest minor the release accepts when it no longer fits."""
    if python_allowed(current, requires):
        return current
    return next((m for m in ('3.%d' % n for n in range(10, 20)) if python_allowed(m, requires)), current)


def node_latest(major):
    release = next(r for r in get_json('https://nodejs.org/dist/index.json') if r['version'].startswith('v%s.' % major))
    version = bare(release['version'])
    name = 'node-v%s-darwin-arm64.tar.gz' % version
    sums = get_text('https://nodejs.org/dist/v%s/SHASUMS256.txt' % version)
    sha = next(line.split()[0] for line in sums.splitlines() if line.endswith(' ' + name))
    return {'version': version, 'url': 'https://nodejs.org/dist/v%s/%s' % (version, name), 'sha256': sha}


# --- rebasing a lock entry ----------------------------------------------------------

def replace_tokens(value, pairs):
    if isinstance(value, str):
        for old, new in pairs:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace_tokens(v, pairs) for v in value]
    if isinstance(value, dict):
        return {k: replace_tokens(v, pairs) for k, v in value.items()}
    return value


def token_pairs(old, new):
    pairs = []
    for name in sorted(set(old) & set(new) - {'url', 'sha256'}, key=lambda n: -len(str(old[n]))):
        a, b = str(old[name]), str(new[name])
        if a != b:
            pairs += [(a, b), (urllib.parse.quote(a), urllib.parse.quote(b))]
    return pairs


def archive_members(path, agent):
    if agent['format'] == 'binary':
        return {path.name}
    if agent['format'] == 'zip':
        with zipfile.ZipFile(path) as archive:
            return {n.rstrip('/') for n in archive.namelist()}
    with tarfile.open(path) as archive:
        return {re.sub(r'^\./', '', n) for n in archive.getnames()}


def read_app(path, agent):
    """Info.plist and product.json of the app in a dmg or zip, read without running it."""
    with tempfile.TemporaryDirectory(prefix='pilot-update-') as work:
        work = pathlib.Path(work)
        if agent['format'] == 'dmg':
            mount = work / 'mount'
            mount.mkdir()
            subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', str(mount), str(path)],
                           check=True, capture_output=True)
            try:
                return app_facts(mount, agent)
            finally:
                subprocess.run(['hdiutil', 'detach', '-force', str(mount)], capture_output=True)
        subprocess.run(['ditto', '-x', '-k', str(path), str(work / 'expanded')], check=True, capture_output=True)
        return app_facts(work / 'expanded', agent)


def app_facts(root, agent):
    apps = sorted(p.name for p in root.iterdir() if p.suffix == '.app')
    name = agent['app'] if agent['app'] in apps else (apps[0] if len(apps) == 1 else None)
    if name is None:
        raise SystemExit('%s: no %s in the download (found %s)' % (agent['id'], agent['app'], apps))
    app = root / name
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    product = app / 'Contents/Resources/app/product.json'
    facts = {'app': name, 'bundleId': info['CFBundleIdentifier'], 'bundleVersion': info['CFBundleShortVersionString'],
             'missing': [r for r in agent['links'].values() if not (app / r).exists()]}
    if product.exists():
        facts['commit'] = json.loads(product.read_text()).get('commit')
    return facts


def rebase(agent, values):
    """The lock entry moved to the release `values` describe, and what still needs a probe."""
    release = release_of(agent)
    old = {'version': agent['version'], **parse(release.get('download'), agent['url'])}
    url = values.get('url') or fill(release.get('download'), values) or replace_tokens(agent['url'], token_pairs(old, values))
    path = download(url)
    digest = sha256_of(path)
    if values.get('sha256') and values['sha256'] != digest:
        raise SystemExit('%s: %s hashes to %s, the feed says %s' % (agent['id'], url, digest, values['sha256']))
    keep = {k: v for k, v in agent.items() if k not in ('url', 'sha256', 'release', 'source')}
    entry = {**agent, **replace_tokens(keep, token_pairs(old, values)), 'version': values['version'], 'url': url, 'sha256': digest}
    if agent['method'] == 'app':
        facts = read_app(path, entry)
        if facts['bundleId'] != agent['bundleId']:
            raise SystemExit('%s: bundle id is now %s' % (agent['id'], facts['bundleId']))
        if facts['missing']:
            raise SystemExit('%s: %s missing from %s' % (agent['id'], facts['missing'], facts['app']))
        entry.update(app=facts['app'], bundleVersion=facts['bundleVersion'])
        values = {**values, **({'commit': facts['commit']} if facts.get('commit') and 'commit' not in values else {})}
    elif agent['method'] == 'archive':
        members = archive_members(path, entry)
        moved = set(entry.get('moves', {}).values())
        missing = [r for r in entry['links'].values() if r not in members and r not in moved]
        if missing:
            raise SystemExit('%s: %s missing from %s' % (agent['id'], missing, url))
    probe = None
    if 'expect' in agent:
        if release.get('expect'):
            entry['expect'] = fill(release['expect'], values)
        elif entry['expect'] == agent['expect']:
            probe = agent['expect']
    return entry, probe


# --- the coding-agents lock -----------------------------------------------------------

def agent_update(agent, apply_changes):
    """(newest version or None, the new entry or None, its publish time, a probe to redo).

    A check reads only the feeds; the downloads are fetched when applying."""
    method = agent['method']
    if method in ('npm', 'npm-node', 'uv'):
        latest = (pypi_latest if method == 'uv' else npm_latest)(agent['package'])
        entry = dict(agent, version=latest['version'])
        if method == 'uv':
            entry['spec'] = '%s==%s' % (agent['package'], latest['version'])
            entry['python'] = python_for(agent['python'], latest['requires_python'])
        if 'expect' in agent:
            entry['expect'] = agent['expect'].replace(agent['version'], latest['version'])
        if method == 'npm-node':
            node = node_latest(agent['node']['version'].split('.')[0])
            entry['node'] = node
            changed = newer(latest['version'], agent['version']) or node['version'] != agent['node']['version']
        else:
            changed = newer(latest['version'], agent['version'])
        probe = agent['expect'] if 'expect' in agent and entry['expect'] == agent['expect'] and changed else None
        return latest['version'], (entry if changed else None), latest['published'], probe
    values = vendor_latest(agent)
    if values is None:
        return None, None, None, None
    if not newer(values['version'], agent['version']):
        return values['version'], None, None, None
    if not apply_changes:
        return values['version'], dict(agent, version=values['version']), None, None
    entry, probe = rebase(agent, values)
    return values['version'], entry, None, probe


def lock_paths(lines):
    return [REPO / 'images' / line / LOCK_NAME for line in lines if (REPO / 'images' / line / LOCK_NAME).exists()]


def update_lock(apply_changes):
    every_line = sorted(p.name for p in (REPO / 'images').iterdir() if (p / LOCK_NAME).exists())
    paths = lock_paths(every_line)
    lock = json.loads(paths[0].read_text())
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda a: (a, *safe(agent_update, a, apply_changes)), lock['agents']))
    rows, agents, published, probes = [], [], [], []
    for agent, latest, entry, when, probe in results:
        status = ('error: %s' % latest) if isinstance(latest, Failure) else \
                 ('no feed: %s' % release_of(agent).get('reason', '')) if latest is None else \
                 'update' if entry else 'current'
        rows.append(('agents', agent['name'], agent['version'], '' if latest is None or isinstance(latest, Failure) else latest, status))
        agents.append(entry or agent)
        if entry and when:
            published.append(when)
        if probe:
            probes.append('%s (%s)' % (agent['name'], probe))
    changed = [(a, b) for a, b in zip(lock['agents'], agents) if a != b]
    if apply_changes and changed:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        newest = max([now] + [datetime.datetime.fromisoformat(p.replace('Z', '+00:00')) for p in published])
        lock = dict(lock, agents=agents, resolvedBefore=newest.strftime('%Y-%m-%dT%H:%M:%SZ'))
        text = json.dumps(lock, indent=1, ensure_ascii=False) + '\n'
        for path in paths:
            path.write_text(text)
        for old, new in changed:
            write_agent_docs(old, new)
    return rows, probes


class Failure(str):
    pass


def safe(function, *args):
    try:
        return function(*args)
    except (Exception, SystemExit) as error:  # one vendor's outage must not stop the others
        return Failure(str(error)), None, None, None


def write_agent_docs(old, new):
    readme = REPO / 'README.md'
    text = readme.read_text()
    row = re.compile(r'^(\| %s \|.*\| )%s( \|)$' % (re.escape(old['name']), re.escape(old['version'])), re.M)
    readme.write_text(row.sub(lambda m: m.group(1) + new['version'] + m.group(2), text, count=1))
    plan = REPO / 'applications' / old['id'] / 'PLAN.md'
    if plan.exists():
        plan.write_text(plan.read_text().replace(old['version'], new['version']))


# --- line pins -----------------------------------------------------------------------

def conf_value(text, key):
    match = re.search(r'^%s="(?:\$\{\w+:-)?([^"}]*)\}?"' % key, text, re.M)
    return match.group(1) if match else None


def set_conf(text, key, value):
    return re.sub(r'^(%s=")((?:\$\{\w+:-)?)[^"}]*(\}?")' % key, lambda m: m.group(1) + m.group(2) + value + m.group(3),
                  text, count=1, flags=re.M)


def pyenv_python(minor):
    tag = gh('repos/pyenv/pyenv/releases/latest')['tag_name']
    names = [e['name'] for e in gh('repos/pyenv/pyenv/contents/plugins/python-build/share/python-build?ref=' + tag)]
    return max((n for n in names if re.fullmatch(r'%s\.\d+' % re.escape(minor), n)), key=vkey), tag


def nvm_latest():
    return bare(gh('repos/nvm-sh/nvm/releases/latest')['tag_name'])


def xcode_latest(major):
    releases = [x['version'] for x in get_json('https://xcodereleases.com/data.json')
                if x.get('version', {}).get('release', {}).get('release')]
    return max((v['number'] for v in releases if v['number'].split('.')[0] == major), key=vkey, default=None)


def node_lts():
    return next(r for r in get_json('https://nodejs.org/dist/index.json') if r['lts'])['version'].lstrip('v').split('.')[0]


def seed_digest(oci):
    name, tag = oci.removeprefix('ghcr.io/').rsplit(':', 1)
    token = get_json('https://ghcr.io/token?scope=repository:%s:pull' % name)['token']
    request = urllib.request.Request('https://ghcr.io/v2/%s/manifests/%s' % (name, tag), method='HEAD', headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.headers['Docker-Content-Digest']


def unity_latest(version):
    stream = version.rsplit('.', 1)[0]
    query = 'stream=LTS&platform=MAC_OS&architecture=ARM64&limit=25&order=RELEASE_DATE_DESC'
    latest = next(r for r in get_json('https://services.api.unity.com/unity/editor/release/v1/releases?' + query)['results']
                  if r['version'].startswith(stream + '.'))
    editor = next(d for d in latest['downloads'] if d['architecture'] == 'ARM64')
    webgl = next(m for m in editor['modules'] if m['id'] == 'webgl')
    md5 = lambda item: item['integrity'].removeprefix('md5-')
    return latest, {
        'UNITY_VERSION': latest['version'], 'UNITY_CHANGESET': latest['shortRevision'],
        'UNITY_EDITOR_URL': editor['url'], 'UNITY_EDITOR_BYTES': str(editor['downloadSize']['value']),
        'UNITY_EDITOR_MD5_B64': md5(editor),
        'UNITY_WEBGL_URL': webgl['url'], 'UNITY_WEBGL_BYTES': str(webgl['downloadSize']['value']),
        'UNITY_WEBGL_MD5_B64': md5(webgl)}


def update_line(line, apply_changes, today):
    folder = REPO / 'images' / line
    rows, conf_path = [], folder / 'line.conf'
    conf = conf_path.read_text()
    python = conf_value(conf, 'PYTHON_VERSION')
    if python:
        latest, tag = pyenv_python(python.rsplit('.', 1)[0])
        rows.append((line, 'Python (pyenv %s)' % tag, python, latest, 'update' if newer(latest, python) else 'current'))
        if newer(latest, python):
            conf = set_conf(conf, 'PYTHON_VERSION', latest)
    nvm = conf_value(conf, 'NVM_VERSION')
    if nvm:
        latest = nvm_latest()
        rows.append((line, 'nvm', bare(nvm), latest, 'update' if newer(latest, bare(nvm)) else 'current'))
        if newer(latest, bare(nvm)):
            conf = set_conf(conf, 'NVM_VERSION', 'v' + latest)
    node = conf_value(conf, 'NODE_MAJOR')
    if node:
        lts = node_lts()
        rows.append((line, 'Node major', node, lts, 'report: newest LTS line' if newer(lts, node) else 'current'))
    xcode = conf_value(conf, 'XCODE_VERSION')
    if xcode:
        latest = xcode_latest(xcode.split('.')[0])
        rows.append((line, 'Xcode', xcode, latest or '', 'report: stage the new xip' if newer(latest, xcode) else 'current'))
    if apply_changes:
        conf_path.write_text(conf)

    seed_path = folder / 'seed.lock'
    if seed_path.exists():
        seed = seed_path.read_text()
        oci, have = re.search(r'^SEED_OCI=(\S+)', seed, re.M).group(1), re.search(r'^SEED_DIGEST=(\S+)', seed, re.M).group(1)
        latest = seed_digest(oci)
        rows.append((line, 'seed ' + oci, have[7:19], latest[7:19], 'update' if latest != have else 'current'))
        if apply_changes and latest != have:
            seed = re.sub(r'^SEED_DIGEST=\S+', 'SEED_DIGEST=' + latest, seed, flags=re.M)
            seed = re.sub(r'Recorded \S+', 'Recorded ' + today, seed)
            seed_path.write_text(seed)

    unity_path = folder / 'guest/unity.lock'
    if unity_path.exists():
        unity = unity_path.read_text()
        have = conf_value(unity, 'UNITY_VERSION')
        release, pins = unity_latest(have)
        rows.append((line, 'Unity editor', have, pins['UNITY_VERSION'], 'update' if newer(pins['UNITY_VERSION'], have) else 'current'))
        if apply_changes and newer(pins['UNITY_VERSION'], have):
            for key, value in pins.items():
                unity = set_conf(unity, key, value)
            unity = unity.replace(have, pins['UNITY_VERSION'])
            unity = re.sub(r'read \d{4}-\d{2}-\d{2}', 'read ' + today[:10], unity)
            unity = re.sub(r'\(%s released \d{4}-\d{2}-\d{2}\)' % re.escape(pins['UNITY_VERSION']),
                           '(%s released %s)' % (pins['UNITY_VERSION'], release['releaseDate'][:10]), unity)
            unity_path.write_text(unity)
    return rows


# --- main ----------------------------------------------------------------------------

def macos_lines():
    return sorted(p.parent.name for p in (REPO / 'images').glob('macos*/line.conf'))


def main(argv):
    if not argv or argv[0] not in ('check', 'apply'):
        raise SystemExit(__doc__)
    apply_changes, lines = argv[0] == 'apply', argv[1:] or macos_lines()
    today = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    rows = [row for line in lines for row in update_line(line, apply_changes, today)]
    agent_rows, probes = update_lock(apply_changes)
    rows += agent_rows
    width = [max(len(str(r[i])) for r in rows) for i in range(4)]
    for row in rows:
        print('  '.join(str(c).ljust(w) for c, w in zip(row, width)) + '  ' + row[4])
    updates = [r for r in rows if r[4] == 'update']
    print('\n%d %s, %d reported, %d without a feed, %d errors' % (
        len(updates), 'updated' if apply_changes else 'to update', sum(r[4].startswith('report') for r in rows),
        sum(r[4].startswith('no feed') for r in rows), sum(r[4].startswith('error') for r in rows)))
    if probes:
        print('probe after the rebuild (phase 85 verify prints the real output): ' + '; '.join(probes))
    return 1 if any(r[4].startswith('error') for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
