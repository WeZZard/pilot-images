#!/usr/bin/env python3
"""Guest application acceptance. No shell initialization, downloads, or repair."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile


def load(path):
    return json.loads(Path(path).read_text())


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', value):
        raise ValueError('invalid application/image identifier')
    return value


def plan_digest(root, selection):
    """Hash the selected configuration, runner and all selected plan files."""
    h = hashlib.sha256()
    h.update(json.dumps(selection, sort_keys=True, separators=(',', ':')).encode())
    paths = [root / 'check.py', root / 'gui.py']
    if selection.get('sources'):
        paths.append(root / 'native.py')
    for app in sorted(selection['plans']):
        directory = root / identifier(app)
        paths.extend(sorted(directory.rglob('*')))
    for path in paths:
        if path.is_symlink():
            raise ValueError('symlink plan refused')
        if path.is_file() and path.suffix in ('.py', '.json', '.md'):
            h.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
    if selection.get('scope') == 'provisioned':
        for relative in sorted({v['path'] for v in selection['provisioning'].values()}):
            # macOS /tmp and /var are OS aliases. Canonicalize the staged
            # root, then reject links only inside the declared source tree.
            base = root.parent.resolve()
            path = base / relative
            current = base
            for part in Path(relative).parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError('symlink provisioning source inside staged tree')
            if not path.is_file():
                raise ValueError('missing provisioning source: ' + relative)
            h.update(relative.encode() + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def gui_module():
    # Load beside this runner, including when it is imported from a staged tree.
    spec = importlib.util.spec_from_file_location('pilot_gui_baselines', Path(__file__).with_name('gui.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(argv, timeout, startup=False, temporary_root=None):
    """Bound output on disk; terminate only this check's process group."""
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a or '\0' in a for a in argv):
        raise ValueError('invalid argv')
    parent = None
    if temporary_root is not None:
        if not isinstance(temporary_root, str) or not (temporary_root.startswith('~/') or Path(temporary_root).is_absolute()):
            raise ValueError('temporaryRoot must be an absolute or home-relative path')
        parent = Path(temporary_root).expanduser().resolve()
        if not parent.is_relative_to(Path.home().resolve()):
            raise ValueError('application temporaryRoot must remain inside the guest home')
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='pilot-app-', dir=parent) as temporary, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        argv = [a.replace('{temporary}', temporary) for a in argv]
        process = None
        try:
            environment = {**os.environ, 'LC_ALL': 'C', 'HOMEBREW_NO_AUTO_UPDATE': '1',
                           'HOMEBREW_NO_ANALYTICS': '1'}
            headless = any(a in ('--headless', '-headless') or a.startswith('--headless=') for a in argv[1:])
            if sys.platform.startswith('linux') and startup and not headless:
                gui = gui_module()
                try:
                    context = gui.resolve_context()
                except gui.ContextError as exc:
                    # Only fixed diagnostic messages are emitted, never environments.
                    raise OSError('GUI context unavailable: ' + str(exc)) from None
                for key in gui.CLEAR_KEYS:
                    environment.pop(key, None)
                environment.update(context)
            process = subprocess.Popen(argv, stdout=out, stderr=err, start_new_session=True, env=environment)
            try:
                code = process.wait(timeout=timeout)
                passed = code == 0 and not startup
                detail = 'exited' if not startup else 'exited before startup observation'
            except subprocess.TimeoutExpired:
                code = None
                passed = startup
                detail = 'running at startup observation' if startup else 'timeout'
            return_value = dict(status='pass' if passed else 'fail', argv=argv, exitCode=code, detail=detail)
        except OSError as exc:
            return_value = dict(status='fail', argv=argv, detail=str(exc))
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        return_value['temporaryDirectory'] = temporary
        if temporary_root is not None:
            return_value['temporaryRoot'] = temporary_root
        # Native package manifests can legitimately exceed the human-facing
        # command-log limit. Keep metadata bounded without cutting valid lists.
        metadata_query = (argv[0] == 'dpkg-query' and len(argv) > 1 and argv[1] in ('-W', '-L')) or (argv[0] == 'brew' and len(argv) > 1 and argv[1] in ('info', 'list')) or (argv[:2] == ['snap', 'list'])
        for name, stream in (('stdout', out), ('stderr', err)):
            limit = 2 * 1024 * 1024 if metadata_query and name == 'stdout' else 8192
            stream.seek(0)
            data = stream.read(limit + 1)
            return_value[name] = data[:limit].decode(errors='replace')
            return_value[name + 'Truncated'] = len(data) > limit
        return return_value


def test_application(directory, kind, architecture, execute=command):
    manifest = load(directory / 'manifest.json')
    if set(manifest) != {'schemaVersion', 'id', 'inventoryIds', 'platforms'} or manifest['schemaVersion'] != 1 or manifest['id'] != directory.name:
        raise ValueError('invalid manifest identity/fields')
    config = manifest['platforms'].get(kind)
    result = dict(id=manifest['id'], inventoryIds=manifest['inventoryIds'], baseline=[], extensions=[])
    if config is None:
        result.update(status='not-applicable', reason='unsupported OS')
        return result
    required = {'architectures', 'executable', 'launch', 'version', 'timeoutSeconds', 'extensions', 'optional'}
    if not required <= config.keys() or set(config) - required - {'temporaryRoot'} or type(config['optional']) is not bool:
        raise ValueError('invalid baseline configuration')
    if 'temporaryRoot' in config and not isinstance(config['temporaryRoot'], str):
        raise ValueError('temporaryRoot must be text')
    if architecture not in config['architectures']:
        result.update(status='not-applicable', reason='unsupported architecture')
        return result
    timeout = config['timeoutSeconds']
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise ValueError('invalid timeout')
    executable = os.path.expanduser(config['executable'])
    available = shutil.which(executable) is not None
    result['baseline'].append(dict(check='availability', status='pass' if available else 'fail', executable=executable))
    if not available and config['optional']:
        result['baseline'][-1]['status'] = 'not-applicable'
        result.update(status='not-applicable', reason='optional executable absent')
        return result
    if available:
        version = config['version']
        if version is None:
            result['baseline'].append(dict(check='version', status='not-applicable', reason='no version invocation declared'))
        else:
            result['baseline'].append(dict(check='version', **execute([executable, *version], timeout)))
        launch = config['launch']
        if set(launch) != {'args', 'mode'} or launch['mode'] not in ('command', 'process'):
            raise ValueError('invalid launch check')
        temporary = {} if 'temporaryRoot' not in config else {'temporary_root': config['temporaryRoot']}
        result['baseline'].append(dict(check='launch', **execute([executable, *launch['args']], timeout, startup=launch['mode'] == 'process', **temporary)))
    # Extensions never replace baseline, and can only select a local Python file.
    for extension in config['extensions']:
        if not re.fullmatch(r'[a-z][a-z0-9-]*\.py', extension):
            raise ValueError('invalid extension filename')
        path = directory / extension
        if not path.is_file() or path.is_symlink():
            raise ValueError('missing or symlink extension')
        result['extensions'].append(dict(check=extension, **execute([sys.executable, str(path)], timeout)))
    result['status'] = 'pass' if all(c['status'] != 'fail' for c in result['baseline'] + result['extensions']) else 'fail'
    return result


def native_module(root):
    spec = importlib.util.spec_from_file_location('pilot_native_baselines', root / 'native.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_selection(selection):
    required = {'schemaVersion', 'image', 'plans', 'dependencies'}
    if not required <= set(selection) or set(selection) - required - {'sources', 'scope', 'provisioning'} or selection['schemaVersion'] != 1:
        raise ValueError('invalid image selection')
    identifier(selection['image'])
    if not isinstance(selection['plans'], list) or any(not isinstance(p, str) for p in selection['plans']) or len(set(selection['plans'])) != len(selection['plans']):
        raise ValueError('invalid or duplicate plan selection')
    sources = selection.get('sources', [])
    if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources) or len(set(sources)) != len(sources):
        raise ValueError('invalid native source selection')
    if not selection['plans'] and not sources:
        raise ValueError('empty plan selection')
    if not isinstance(selection['dependencies'], dict):
        raise ValueError('invalid dependencies')
    if 'scope' in selection or 'provisioning' in selection:
        if selection.get('scope') != 'provisioned' or sources:
            raise ValueError('provisioned scope requires explicit plans without source-wide expansion')
        provenance = selection.get('provisioning')
        if not isinstance(provenance, dict) or set(provenance) != set(selection['plans']):
            raise ValueError('every provisioned application plan requires a source reference')
        for entry in provenance.values():
            if not isinstance(entry, dict) or set(entry) != {'path', 'reason'} or not isinstance(entry['reason'], str) or not entry['reason'].strip():
                raise ValueError('invalid provisioning reference')
            path = entry['path']
            if not isinstance(path, str) or not path.startswith('images/' + selection['image'] + '/guest/') or any(part in ('', '.', '..') for part in path.split('/')) or '\\' in path:
                raise ValueError('provisioning reference must be inside the image guest sources')


def expected_plan_inventory_ids(root, selection, inventory):
    """Pure deterministic plan-ID -> inventory-ID mapping, without guest I/O.

    Explicit plans/dependencies take precedence. Native plan IDs are the literal
    'native:' prefix followed by the inventory ID, sorted after explicit plans.
    Unknown sources receive failed native reports, not silent exemptions.
    """
    validate_selection(selection)
    mapping, covered = {}, set()
    for app in selection['plans']:
        manifest = load(root / identifier(app) / 'manifest.json')
        ids = manifest['inventoryIds']
        if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids) or len(ids) != len(set(ids)) or covered.intersection(ids):
            raise ValueError('duplicate or invalid inventory mapping')
        mapping[app] = list(ids)
        covered.update(ids)
    for dependency, entry in selection['dependencies'].items():
        if set(entry) != {'plan', 'reason'} or entry['plan'] not in mapping or not isinstance(entry['reason'], str) or not entry['reason'].strip() or dependency in covered:
            raise ValueError('invalid dependency coverage')
        mapping[entry['plan']].append(dependency)
        covered.add(dependency)
    if selection.get('sources'):
        for app in sorted({a['id'] for a in inventory['applications']} - covered):
            mapping['native:' + app] = [app]
    return mapping


def expected_plan_ids(root, selection, inventory):
    """Return deterministic report IDs. Does not launch or inspect guest files."""
    return list(expected_plan_inventory_ids(root, selection, inventory))


def expected_application_ids(root, selection, inventory):
    """Host-facing alias: deterministic explicit and native report IDs."""
    return expected_plan_ids(Path(root), selection, inventory)


def validate_results(root, selection, inventory, report):
    """Validate coverage, source selection, plan hash, evidence and status.

    Returns None or raises ValueError. Structurally valid failures are allowed;
    acceptance callers MUST additionally require report['status'] == 'pass'.
    Does not inspect the guest or execute commands. Build/inventory provenance,
    timestamp freshness and artifact integrity remain the host's responsibility.
    """
    if not isinstance(report, dict):
        raise ValueError('application report must be an object')
    root = Path(root)
    expected = expected_plan_inventory_ids(root, selection, inventory)
    if report.get('planSha256') != plan_digest(root, selection):
        raise ValueError('stale application plan hash')
    for field, value in (('schemaVersion', 1), ('image', selection['image']),
                         ('os', inventory['os']), ('architecture', inventory['architecture']),
                         ('dependencies', selection['dependencies'])):
        if report.get(field) != value:
            raise ValueError('application report mismatch: ' + field)
    if report.get('scope') != selection.get('scope'):
        raise ValueError('application acceptance scope mismatch')
    if report.get('sources', []) != selection.get('sources', []):
        raise ValueError('application report source selection mismatch')
    installed_ids = [a['id'] for a in inventory['applications']]
    if len(installed_ids) != len(set(installed_ids)):
        raise ValueError('duplicate installed inventory ID')
    installed = set(installed_ids)
    results = report.get('applications')
    if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
        raise ValueError('invalid application results')
    ids = [r.get('id') for r in results]
    if any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError('application report IDs do not match expected plans')
    sources = selection.get('sources', [])
    native = native_module(root) if sources else None
    if native is not None and set(sources) - native.SOURCES:
        raise ValueError('unsupported native source selection')
    covered = set()
    for result in results:
        validate_baseline_report(result)
        app = result['id']
        owns_installed = installed.intersection(expected[app])
        if app.startswith('native:'):
            source = result['adapter']
            if source in sources:
                covered.update(expected[app])
                availability = next(c for c in result['baseline'] if c['check'] == 'availability')
                if 'availableEntryPoints' in availability:
                    candidates = availability['availableEntryPoints']
                    if not isinstance(candidates, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in candidates):
                        raise ValueError('invalid public entry point list')
                    package_name = app[len('native:'):].partition(':')[2]
                    selected = native.select_entry_points(package_name, candidates, availability)
                    if availability['entryPoints'] != selected:
                        raise ValueError('package baseline entry point selection mismatch')
                    if availability.get('untestedEntryPoints') != sorted(set(candidates) - set(selected)):
                        raise ValueError('untested auxiliary entry points are not disclosed accurately')
                    for launch in availability.get('desktopLaunchMetadata', []):
                        if launch['terminal']:
                            safe = native.safe_arguments(Path(launch['argv'][0]).name)
                            if safe is None or launch['declaredArgv'] != [launch['argv'][0]] or launch['argv'] != [launch['argv'][0], *safe]:
                                raise ValueError('terminal shortcut did not use its reviewed CLI probe')
                        elif launch['argv'] != launch['declaredArgv']:
                            raise ValueError('GUI launch differs from declared desktop invocation')
                desktop_variants = {}
                for launch in availability.get('guiLaunchEntries', []):
                    variants = desktop_variants.setdefault(launch['argv'][0], [])
                    if launch['argv'] not in variants:
                        variants.append(launch['argv'])
                for check in result['baseline']:
                    if check['check'] == 'launch' and check['status'] == 'pass':
                        for invocation in check['invocations']:
                            argv = invocation['argv']
                            if argv[0] in desktop_variants:
                                if not desktop_variants[argv[0]] or argv != desktop_variants[argv[0]].pop(0) or invocation.get('detail') != 'running at startup observation':
                                    raise ValueError('native desktop variant order or startup evidence mismatch')
                            elif argv[0] in availability.get('guiCommands', {}):
                                if argv != availability['guiCommands'][argv[0]] or invocation.get('detail') != 'running at startup observation' or not any(p.endswith('.desktop') for p in availability['inspectedFiles']):
                                    raise ValueError('native desktop launch lacks declared argv and startup observation')
                            elif argv[0] in availability.get('guiEntries', []):
                                if len(argv) != 1 or not re.search(r'\.app/Contents/MacOS/[^/]+$', argv[0]) or invocation.get('detail') != 'running at startup observation':
                                    raise ValueError('native GUI launch lacks a bounded startup observation')
                            else:
                                args = native.safe_arguments(Path(argv[0]).name)
                                if args is None or argv[1:] != args:
                                    raise ValueError('native launch was not a reviewed safe invocation')
                        if any(desktop_variants.values()):
                            raise ValueError('native desktop variants were not all tested')
            elif result['status'] != 'fail':
                raise ValueError('unsupported source cannot pass')
        else:
            manifest = load(root / identifier(app) / 'manifest.json')
            if result['inventoryIds'] != manifest['inventoryIds']:
                raise ValueError('explicit inventory mapping mismatch')
            covered.update(expected[app])
            config = manifest['platforms'].get(inventory['os'])
            supported = config is not None and inventory['architecture'] in config['architectures']
            if result['status'] == 'pass':
                if not supported:
                    raise ValueError('unsupported platform cannot pass')
                baseline = {c['check']: c for c in result['baseline']}
                if baseline['availability']['status'] != 'pass' or baseline['launch']['status'] != 'pass':
                    raise ValueError('explicit application skipped availability or launch')
                version_status = 'not-applicable' if config['version'] is None else 'pass'
                if baseline['version']['status'] != version_status:
                    raise ValueError('explicit version check mismatch')
                if 'temporaryRoot' in config:
                    launch = baseline['launch']
                    if launch.get('temporaryRoot') != config['temporaryRoot'] or not isinstance(launch.get('temporaryDirectory'), str) or not Path(launch['temporaryDirectory']).is_absolute():
                        raise ValueError('application-specific temporary root evidence missing')
                executable = config['executable']
                if executable.startswith('~/'):
                    guest_home = report.get('guestHome')
                    if not isinstance(guest_home, str) or not guest_home.startswith('/') or guest_home == '/' or '..' in guest_home.split('/') or '\\' in guest_home or any(ord(c)<32 for c in guest_home) or str(Path(guest_home)) != guest_home:
                        raise ValueError('home-relative executable requires a normalized observed guest home')
                    executable = str(Path(guest_home) / executable[2:])
                if baseline['availability'].get('executable') != executable:
                    raise ValueError('explicit executable mismatch')
                for name, args in [('launch', config['launch']['args']), ('version', config['version'])]:
                    if args is None:
                        continue
                    actual = baseline[name].get('argv')
                    planned = [executable, *args]
                    if not isinstance(actual, list) or len(actual) != len(planned):
                        raise ValueError('explicit invocation evidence absent')
                    for observed, wanted in zip(actual, planned):
                        pattern = re.escape(wanted).replace(re.escape('{temporary}'), r'.+')
                        if not isinstance(observed, str) or re.fullmatch(pattern, observed) is None:
                            raise ValueError('explicit invocation mismatch')
                if [e['check'] for e in result['extensions']] != config['extensions'] or any(e['status'] != 'pass' for e in result['extensions']):
                    raise ValueError('isolated extension evidence mismatch')
            if result['status'] == 'not-applicable':
                optional_absent = supported and config['optional'] and result.get('reason') == 'optional executable absent'
                if supported and not optional_absent:
                    raise ValueError('required application cannot be skipped')
        if owns_installed and result['status'] == 'not-applicable':
            raise ValueError('installed application cannot be skipped')
    not_tested = sorted(installed - covered)
    unclassified = [] if selection.get('scope') == 'provisioned' else not_tested
    if selection.get('scope') == 'provisioned' and report.get('notTestedInventoryIds') != not_tested:
        raise ValueError('out-of-scope inventory must be reported without claiming a test pass')
    if report.get('unclassified') != unclassified:
        raise ValueError('installed ID coverage mismatch')
    status = 'pass' if not unclassified and all(r['status'] in ('pass', 'not-applicable') for r in results) else 'fail'
    if report.get('status') != status:
        raise ValueError('aggregate application status mismatch')


def validate_baseline_report(result):
    """Raise ValueError on malformed per-plan evidence; return None on success.

    Failed checks are valid report structures. This does not establish freshness
    or accept a failed report; host policy must separately require passing status.
    """
    if not isinstance(result, dict) or not isinstance(result.get('id'), str):
        raise ValueError('invalid application report')
    if result.get('status') not in ('pass', 'fail', 'not-applicable'):
        raise ValueError('invalid application status')
    if not isinstance(result.get('inventoryIds'), list) or any(not isinstance(i, str) for i in result['inventoryIds']):
        raise ValueError('invalid inventory report IDs')
    baseline, extensions = result.get('baseline'), result.get('extensions')
    if not isinstance(baseline, list) or not isinstance(extensions, list):
        raise ValueError('invalid baseline or extension checks')
    for check in baseline + extensions:
        if not isinstance(check, dict) or not isinstance(check.get('check'), str) or check.get('status') not in ('pass', 'fail', 'not-applicable'):
            raise ValueError('invalid check result')
    names = [c['check'] for c in baseline]
    if len(names) != len(set(names)):
        raise ValueError('duplicate baseline checks')
    native = result['id'].startswith('native:')
    if native:
        owned = result['id'][len('native:'):]
        if result['inventoryIds'] != [owned] or result.get('adapter') != owned.partition(':')[0] or extensions:
            raise ValueError('invalid native identity or extensions')
    if native or result['status'] == 'pass':
        if set(names) != {'availability', 'version', 'launch'}:
            raise ValueError('incomplete baseline')
    if result['status'] == 'pass' and any(c['status'] == 'fail' for c in baseline + extensions):
        raise ValueError('passing report contains failed checks')
    if native:
        checks = {c['check']: c for c in baseline}
        if result['status'] == 'not-applicable':
            raise ValueError('native plans cannot be skipped')
        if checks['availability']['status'] == 'not-applicable' or checks['version']['status'] == 'not-applicable':
            raise ValueError('native installation/version cannot be exempted')
        if checks['launch']['status'] == 'not-applicable':
            evidence = checks['launch'].get('evidence', {})
            if not isinstance(evidence, dict) or not checks['launch'].get('reason') or not evidence.get('metadata') or not evidence.get('inspectedFiles') or checks['availability'].get('entryPoints') != [] or evidence.get('metadata') != checks['availability'].get('metadata') or evidence.get('inspectedFiles') != checks['availability'].get('inspectedFiles'):
                raise ValueError('resource-only launch requires inspected file evidence')
        if checks['availability']['status'] == 'pass':
            available = checks['availability']
            if not isinstance(available.get('metadata'), str) or not available['metadata'] or not isinstance(available.get('entryPoints'), list) or not isinstance(available.get('inspectedFiles'), list) or not available['inspectedFiles']:
                raise ValueError('native availability lacks file evidence')
            if 'inspectedFileCount' in available or 'inspectedFilesSha256' in available:
                count, digest = available.get('inspectedFileCount'), available.get('inspectedFilesSha256')
                if type(count) is not int or count < len(available['inspectedFiles']) or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    raise ValueError('invalid bounded file inspection evidence')
                if checks['launch']['status'] == 'not-applicable':
                    evidence = checks['launch']['evidence']
                    if evidence.get('inspectedFileCount') != count or evidence.get('inspectedFilesSha256') != digest:
                        raise ValueError('resource-only inspection proof mismatch')
            desktop_entries = available.get('guiLaunchEntries', [])
            if not isinstance(desktop_entries, list):
                raise ValueError('invalid desktop launch entries')
            for launch in desktop_entries:
                if not isinstance(launch, dict) or set(launch) != {'desktop', 'argv'} or not isinstance(launch['desktop'], str) or launch['desktop'] not in available['inspectedFiles'] or not launch['desktop'].endswith('.desktop') or not isinstance(launch['argv'], list) or not launch['argv'] or launch['argv'][0] not in available['entryPoints'] or any(not isinstance(a, str) or '\0' in a for a in launch['argv']):
                    raise ValueError('invalid desktop launch evidence')
            metadata = available.get('desktopLaunchMetadata', [])
            terminal_entries = available.get('terminalLaunchEntries', [])
            if not isinstance(metadata, list) or not isinstance(terminal_entries, list):
                raise ValueError('invalid desktop classification metadata')
            gui_expected, terminal_expected = [], []
            for launch in metadata:
                if not isinstance(launch, dict) or set(launch) != {'desktop', 'argv', 'declaredArgv', 'terminal', 'public', 'declaredExec'} or type(launch['terminal']) is not bool or type(launch['public']) is not bool:
                    raise ValueError('invalid desktop classification fields')
                if not isinstance(launch['desktop'], str) or launch['desktop'] not in available['inspectedFiles'] or not launch['desktop'].endswith('.desktop') or not isinstance(launch['declaredExec'], str) or not launch['declaredExec'] or '\0' in launch['declaredExec']:
                    raise ValueError('desktop classification lacks retained file metadata')
                for key in ('argv', 'declaredArgv'):
                    args = launch[key]
                    if not isinstance(args, list) or not args or any(not isinstance(a, str) or '\0' in a for a in args) or args[0] not in available.get('availableEntryPoints', available['entryPoints']):
                        raise ValueError('desktop classification has invalid arguments')
                (terminal_expected if launch['terminal'] else gui_expected).append({'desktop': launch['desktop'], 'argv': launch['argv']})
            if 'desktopLaunchMetadata' in available and (gui_expected != desktop_entries or terminal_expected != terminal_entries):
                raise ValueError('desktop classification and launch evidence disagree')
            commands = available.get('guiCommands', {})
            if not isinstance(commands, dict) or any(p not in available['entryPoints'] or not isinstance(args, list) or not args or args[0] != p or any(not isinstance(a, str) or '\0' in a for a in args) for p, args in commands.items()):
                raise ValueError('native desktop commands must match declared entry points')
            gui = available.get('guiEntries', [])
            if not isinstance(gui, list) or any(p not in available['entryPoints'] or not re.search(r'\.app/Contents/MacOS/[^/]+$', p) for p in gui):
                raise ValueError('native GUI entries must be declared bundle executables')
            if any(not isinstance(p, str) or not Path(p).is_absolute() for p in available['entryPoints'] + available['inspectedFiles']):
                raise ValueError('native file evidence requires absolute paths')
        if checks['version']['status'] == 'pass' and (not isinstance(checks['version'].get('observed'), str) or not checks['version']['observed'] or checks['version']['observed'] != checks['version'].get('expected')):
            raise ValueError('native version lacks matching evidence')
        if checks['launch']['status'] == 'pass':
            invocations = checks['launch'].get('invocations')
            entries = checks['availability'].get('entryPoints', [])
            if not isinstance(invocations, list) or not entries or len(invocations) != len(entries) or any(not isinstance(i, dict) or i.get('status') != 'pass' or not isinstance(i.get('argv'), list) or not i['argv'] or i['argv'][0] != entry for i, entry in zip(invocations, entries)):
                raise ValueError('native launch lacks successful entry-point invocations')


def run(root, selection, inventory, build_id, execute=command, *, observe_native=None, progress=None):
    mapping = expected_plan_inventory_ids(root, selection, inventory)
    installed = {app['id'] for app in inventory['applications']}

    def completed(result):
        if result['status'] == 'not-applicable' and installed.intersection(mapping[result['id']]):
            result.update(status='fail', reason='installed application or dependency is not testable on this platform')
        if progress is not None:
            progress(result['id'], result['status'])
        return result

    results = [completed(test_application(root / identifier(app), inventory['os'], inventory['architecture'], execute)) for app in selection['plans']]
    covered = {}
    for result in results:
        for app in result['inventoryIds']:
            if app in covered:
                raise ValueError('duplicate inventory mapping')
            covered[app] = result['id']
    for dependency, entry in selection['dependencies'].items():
        if set(entry) != {'plan', 'reason'} or entry['plan'] not in selection['plans'] or not entry['reason'].strip() or dependency in covered:
            raise ValueError('invalid dependency coverage')
        covered[dependency] = entry['plan']
    installed = {app['id'] for app in inventory['applications']}
    if selection.get('sources'):
        native = native_module(root)
        if set(selection['sources']) - native.SOURCES:
            raise ValueError('unsupported native source selection')
        for record in sorted(inventory['applications'], key=lambda app: app['id']):
            if record['id'] in covered:
                continue
            kwargs = {} if observe_native is None else {'observer': observe_native}
            result = native.baseline(record, selection['sources'], execute, **kwargs)
            results.append(completed(result))
            if record['id'].partition(':')[0] in selection['sources']:
                covered[record['id']] = result['id']
    not_tested = sorted(installed - covered.keys())
    unclassified = [] if selection.get('scope') == 'provisioned' else not_tested
    # Installed software may not evade acceptance as optional/unsupported.
    for result in results:
        owns = {app for app, owner in covered.items() if owner == result['id']}
        if result['status'] == 'not-applicable' and installed & owns:
            result.update(status='fail', reason='installed application or dependency is not testable on this platform')
    return dict(schemaVersion=1, image=selection['image'], buildId=build_id, guestHome=str(Path.home()),
                observedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                planSha256=plan_digest(root, selection),
                os=inventory['os'], architecture=inventory['architecture'],
                status='pass' if not unclassified and all(r['status'] in ('pass', 'not-applicable') for r in results) else 'fail',
                applications=results, unclassified=unclassified, dependencies=selection['dependencies'],
                **({'scope': 'provisioned', 'notTestedInventoryIds': not_tested} if selection.get('scope') == 'provisioned' else {}),
                **({'sources': selection['sources']} if 'sources' in selection else {}))


def cli_progress(name, status):
    # JSON string quoting prevents an inventory name from injecting terminal controls.
    print(f'{json.dumps(name, ensure_ascii=True)} {status}', file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', required=True, type=Path)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--build-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    inventory = load(args.inventory)
    actual_os = 'macos' if sys.platform == 'darwin' else 'linux'
    actual_arch = {'aarch64': 'arm64', 'AMD64': 'x86_64'}.get(platform.machine(), platform.machine())
    if inventory['os'] != actual_os or inventory['architecture'] != actual_arch:
        parser.error('inventory platform does not match execution guest')
    report = run(Path(__file__).parent, load(args.selection), inventory, args.build_id, progress=cli_progress)
    report['inventorySha256'] = hashlib.sha256(args.inventory.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, separators=(',', ':')) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
