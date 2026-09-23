"""Read installed native metadata before deciding whether a launch is applicable.

No package name heuristics and no generic --help/--version execution: only the
small reviewed invocation table below may launch discovered command entry points.
GUI bundles use their declared executable for a bounded startup observation.
Unknown CLI invocations require an isolated explicit manifest, not an exemption.
"""
import json
import hashlib
import configparser
import shlex
import shutil
import os
from pathlib import Path
import plistlib
import re
import struct
from xml.parsers.expat import ExpatError

SOURCES = frozenset({'bundle', 'dpkg', 'brew-formula', 'brew-cask', 'npm', 'snap'})
# These options only report versions; in particular no service, package-manager,
# maintenance, interpreter-input, plugin-loading or shell default is executed.
SAFE_COMMANDS = {
    'python3': ['-I', '-S', '--version'], 'python': ['-I', '-S', '--version'],
    'node': ['--version'], 'git': ['--version'], 'jq': ['--version'],
    'rg': ['--version'], 'fd': ['--version'], 'ffmpeg': ['-version'],
    'ffprobe': ['-version'], 'gcc': ['--version'], 'g++': ['--version'],
    'clang': ['--version'], 'clang++': ['--version'], 'cmake': ['--version'],
    'ninja': ['--version'], 'rustc': ['--version'],
    'autoconf': ['--version'], 'autoheader': ['--version'], 'autom4te': ['--version'],
    'autoreconf': ['--version'], 'autoscan': ['--version'], 'autoupdate': ['--version'],
    'ifnames': ['--version'], 'aws': ['--version'], 'brotli': ['--version'],
    'curl': ['--version'], 'gh': ['--version'], 'git-lfs': ['version'],
    'gitlab-runner': ['--version'], 'gettext': ['--version'], 'lame': ['--version'],
    'lz4': ['--version'], 'm4': ['--version'], 'mise': ['--version'],
    'mpg123': ['--version'], 'npm': ['--version'], 'npx': ['--version'],
    'openssl': ['version'], 'pkg-config': ['--version'], 'pkgconf': ['--version'],
    'pyenv': ['--version'], 'rbenv': ['--version'], 'ruby-build': ['--version'],
    'sqlite3': ['--version'], 'unzip': ['-v'], 'usage': ['--version'],
    'uv': ['--version'], 'uvx': ['--version'], 'wget': ['--version'],
    'x264': ['--version'], 'x265': ['--version'], 'xz': ['--version'],
    'yq': ['--version'], 'zip': ['--version'], 'zstd': ['--version'],
}

# Reviewed informational entry points of standard GNU command-line suites.
for _name in ('arch b2sum base32 base64 basename basenc cat chcon chgrp chmod chown chroot cksum comm cp csplit cut date dd df dir dircolors dirname du echo env expand expr factor false fmt fold groups head hostid id install join link ln logname ls md5sum mkdir mkfifo mknod mktemp mv nice nl nohup nproc numfmt od paste pathchk pinky pr printenv printf ptx pwd readlink realpath rm rmdir runcon seq sha1sum sha224sum sha256sum sha384sum sha512sum shred shuf sleep sort split stat stdbuf stty sum sync tac tail tee test timeout touch tr true truncate tsort tty uname unexpand uniq unlink users vdir wc who whoami yes').split():
    SAFE_COMMANDS.setdefault(_name, ['--version'])
    SAFE_COMMANDS.setdefault('g' + _name, ['--version'])
SAFE_COMMANDS.update({name: ['--version'] for name in ('grep','egrep','fgrep','sed','find','xargs','tar','gzip','gunzip','bzip2','bunzip2','diff','cmp','patch','dpkg','dpkg-query','apt','apt-get','apt-cache','apt-config','apt-mark','perl','bash','zsh','man','less','getfacl','setfacl','systemctl','systemd','systemd-analyze','gpg','gpgv','gpgsm','gpg-agent','gpgconf')})


# These exact public interfaces were reviewed against the Ubuntu application
# failure report and probed in the isolated Ubuntu 24.04 work guest. Every
# invocation below exited successfully with version text on 2026-09-16.
# This is deliberately not a suffix/prefix rule or a fallback for unknown tools.
# Daemons use their version-only exit paths, never their default startup paths.
SAFE_COMMANDS.update({name: ['--version'] for name in (
    'appstreamcli', 'aspell', 'bc', 'bpftrace', 'bwrap', 'cpio', 'cryptsetup',
    'dbus-daemon', 'dc', 'dirmngr', 'dmidecode', 'dnsmasq', 'ed', 'ethtool',
    'fdisk', 'file', 'gawk', 'groff', 'hostname', 'install-info', 'kmod',
    'logrotate', 'mdadm', 'mount', 'nano', 'nft', 'nmcli', 'numactl', 'openvpn',
    'parted', 'pinentry-curses', 'pinentry-gnome3', 'pipewire', 'pipewire-pulse',
    'pkexec', 'pkaction', 'rsync', 'screen', 'strace', 'tcpdump', 'time',
    'udevadm', 'ufw', 'upower', 'usbmuxd', 'whiptail', 'wireplumber',
    'avahi-daemon', 'col', 'logger', 'lsblk', 'uuidgen', 'free', 'pstree',
    'getconf', 'gencat', 'sprof', 'mmcli', 'mbimcli', 'qmicli', 'lspci',
    'lsusb', 'rfkill', 'fc-list', 'dtc', 'fusermount3', 'gs', 'vim.basic',
    'vim.tiny', 'iwconfig', 'netstat', 'thin_check', 'ghostscript', 'btrfs',
    'apparmor_parser', 'apt-ftparchive', 'dbus-uuidgen', 'run-parts',
    'desktop-file-validate', 'eject', 'inetutils-telnet', 'ldd',
    'gdk-pixbuf-csource', 'glib-compile-schemas', 'notify-send', 'mtr',
    'pkcon', 'rtkitctl', 'sssd', 'resolvectl', 'oomctl',
    'aarch64-linux-gnu-cpp-13', 'aarch64-linux-gnu-cpp', 'gpgtar',
    'gpg-wks-client', 'grub-install',
)})
SAFE_COMMANDS.update({
    'dig': ['-v'], 'host': ['-V'], 'e2fsck': ['-V'],
    'gdb': ['-nx', '--version'],  # Do not load user or project init scripts.
    'hdparm': ['-V'], 'ip': ['-Version'], 'ping': ['-V'], 'tracepath': ['-V'],
    'mawk': ['-W', 'version'], 'ssh': ['-V'], 'sshd': ['-V'],
    'pdfinfo': ['-v'], 'rsyslogd': ['-v'], 'socat': ['-V'], 'tmux': ['-V'],
    'xxd': ['-v'], 'wpa_supplicant': ['-v'], 'mksquashfs': ['-version'],
    'iostat': ['-V'], 'dumpimage': ['-V'], 'enchant-2': ['-v'], 'tic': ['-V'],
    'update-mime-database': ['-v'], 'pygmentize': ['-V'], 'lvm': ['version'],
})


# Additional public CLI interfaces from the remaining Ubuntu baseline failures.
# These exact argv returned identifying output and exit 0 in the isolated
# relay-acceptance-20260916 guest. Query commands do not change configuration.
# Do not infer success for related daemons, hardware access or other subcommands.
SAFE_COMMANDS.update({name: ['--version'] for name in (
    'adduser', 'aptdcon', 'bluetoothctl', 'boltctl', 'cloud-init', 'cpp', 'cpp-13',
    'dhcpcd', 'efibootmgr', 'gamemoded', 'gjs', 'grub-probe', 'gst-inspect-1.0',
    'iptables-nft', 'ntfs-3g', 'iscsiadm', 'pybabel-python3', 'chardet',
    'jsonschema', 'rpcgen', 'scanimage', 'sbverify', 'speech-dispatcher',
    'sudo', 'tracker3', 'xdg-dbus-proxy', 'xdg-open', 'amixer',
    'file2brl', 'mimetype', 'ubuntu-advantage', 'sg_inq', 'mtdinfo',
    'markdown-it', 'jsonpointer', 'jsonpatch', 'twist3', 'tart-guest-agent',
)})
SAFE_COMMANDS.update({
    'anacron': ['-V'], 'apg': ['-v'], 'lsof': ['-v'],
    'powerprofilesctl': ['version'], 'xauth': ['-V'],
    'xfs_repair': ['-V'], 'gnome-keyring': ['version'], 'mscompress': ['-V'],
    'pastebinit': ['-v'], 'netplan': ['info'],
})


def safe_arguments(name):
    """Return a reviewed read-only invocation, or None; never guess --help."""
    if re.fullmatch(r'python3(?:\.\d+)?', name):
        return ['-I', '-S', '--version']
    if re.fullmatch(r'(?:gcc|g\+\+|clang|clang\+\+)(?:-\d+)?', name):
        return ['--version']
    return SAFE_COMMANDS.get(name)


def owned_tree(root):
    files = []
    for path in root.rglob('*'):
        if path.is_file() or path.is_symlink():
            files.append(str(path))
            if len(files) > 20000:
                raise ValueError('owned-file inspection limit exceeded')
    return sorted(files)


def query(execute, argv):
    result = execute(argv, 20)
    if result.get('status') != 'pass' or result.get('stdoutTruncated'):
        raise ValueError('metadata command failed or truncated: ' + repr(argv))
    if not isinstance(result.get('stdout'), str):
        raise ValueError('metadata command returned no text: ' + repr(argv))
    return result['stdout']


def bundle_info(path):
    with (path / 'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    name = info.get('CFBundleExecutable')
    if not isinstance(name, str) or not name or '/' in name or name in ('.', '..'):
        raise ValueError('invalid bundle executable metadata')
    return info, path / 'Contents/MacOS' / name


def bundle_metadata(name, roots):
    found = {}
    for root in map(Path, roots):
        if not root.is_dir():
            raise ValueError('bundle search root absent: ' + str(root))
        for directory in (root, root / 'Utilities'):
            if not directory.exists():
                continue
            for path in sorted(directory.glob('*.app')):
                metadata = path / 'Contents/Info.plist'
                if not metadata.is_file():
                    continue
                with metadata.open('rb') as stream:
                    info = plistlib.load(stream)
                if info.get('CFBundleIdentifier') == name:
                    info, executable = bundle_info(path)
                    found[str(path.resolve())] = (info, executable, metadata)
    if len(found) != 1:
        raise ValueError('bundle identifier did not resolve uniquely')
    info, executable, metadata = next(iter(found.values()))
    return dict(version=info.get('CFBundleShortVersionString', info.get('CFBundleVersion')),
                files=[str(metadata), str(executable)], entries=[str(executable)],
                metadata=str(metadata), guiEntries=[str(executable)])


def dpkg_owned_files(raw):
    files = []
    previous_path = False
    notice = re.compile(r'(?:diverted by [a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)? to|package diverts others to|locally diverted to): /[^\x00\r\n]+')
    for line in raw.splitlines():
        if line.startswith('/') and '\x00' not in line:
            files.append(line)
            previous_path = True
        elif previous_path and notice.fullmatch(line):
            # This annotates the preceding path; it never replaces or excuses it.
            previous_path = False
        else:
            raise ValueError('unsupported dpkg owned-file line: ' + line)
    return files


def snap_app_names(raw, name):
    # Read the block mapping emitted in installed meta/snap.yaml, not snapcraft
    # build instructions. Unrelated scalars may contain {}, *, &, or shell text.
    # Do not interpret command strings or YAML aliases as runnable commands.
    key_pattern = r'(?:([A-Za-z0-9][A-Za-z0-9-]*)|\"([A-Za-z0-9][A-Za-z0-9-]*)\"|\'([A-Za-z0-9][A-Za-z0-9-]*)\'):[ ]*(.*)'
    sections = {}
    current = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if '\t' in line[:len(line) - len(line.lstrip())]:
            raise ValueError('unsupported snap metadata indentation')
        if line.startswith(' '):
            if current is None:
                raise ValueError('unsupported snap metadata layout')
            sections[current][1].append(line)
            continue
        match = re.fullmatch(key_pattern, line)
        if not match:
            # Indentless sequences are commonly emitted by YAML serializers.
            if line.startswith('- ') and current not in (None, 'name', 'apps'):
                sections[current][1].append(line)
                continue
            raise ValueError('unsupported snap metadata layout; isolated manifest required')
        current = next(value for value in match.groups()[:3] if value is not None)
        if current in sections:
            raise ValueError('duplicate snap metadata key: ' + current)
        sections[current] = [match[4], []]
    scalar = r'(?:' + re.escape(name) + r'|\"' + re.escape(name) + r'\"|\'' + re.escape(name) + r'\')[ ]*(?:#.*)?'
    if 'name' not in sections or sections['name'][1] or not re.fullmatch(scalar, sections['name'][0]):
        raise ValueError('unsupported snap metadata identity')
    if 'apps' not in sections:
        return []
    value, lines = sections['apps']
    if re.fullmatch(r'\{[ ]*\}[ ]*(?:#.*)?', value) and not lines:
        return []
    if not re.fullmatch(r'(?:#.*)?', value) or not lines:
        raise ValueError('unsupported snap apps layout; isolated manifest required')
    indent = len(lines[0]) - len(lines[0].lstrip(' '))
    apps = []
    for line in lines:
        width = len(line) - len(line.lstrip(' '))
        if width < indent:
            raise ValueError('unsupported snap apps indentation')
        if width > indent:
            continue
        match = re.fullmatch(key_pattern, line[indent:])
        if not match or not re.fullmatch(r'(?:\{[ ]*\}[ ]*)?(?:#.*)?', match[4]):
            raise ValueError('unsupported snap apps layout; isolated manifest required')
        app = next(value for value in match.groups()[:3] if value is not None)
        if app in apps:
            raise ValueError('duplicate snap app: ' + app)
        apps.append(app)
    return apps


def installed_metadata(source, name, execute, roots):
    if not name or name.startswith('-') or any(c.isspace() for c in name) or '\x00' in name:
        raise ValueError('invalid native identifier')
    if source == 'bundle':
        return bundle_metadata(name, roots)
    if source == 'dpkg':
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?', name):
            raise ValueError('invalid dpkg identifier')
        raw = query(execute, ['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', name]).strip().split('\t')
        if len(raw) != 2 or raw[0] != 'installed':
            raise ValueError('dpkg package is not installed')
        files = dpkg_owned_files(query(execute, ['dpkg-query', '-L', name]))
        return dict(version=raw[1], files=files, metadata='dpkg-query installed record and owned files')
    if source in ('brew-formula', 'brew-cask'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.@-]*', name):
            raise ValueError('invalid brew identifier')
        flag = '--formula' if source == 'brew-formula' else '--cask'
        data = json.loads(query(execute, ['brew', 'info', '--json=v2', flag, name]))
        rows = data['formulae' if source == 'brew-formula' else 'casks']
        if len(rows) != 1 or rows[0].get('name' if source == 'brew-formula' else 'token') != name:
            raise ValueError('brew identity mismatch')
        row = rows[0]
        versions = [v['version'] for v in row['installed']] if source == 'brew-formula' else [row['installed']]
        if len(versions) != 1 or not versions[0]:
            raise ValueError('brew installed version absent or ambiguous')
        files = query(execute, ['brew', 'list', flag, '--verbose', name]).splitlines()
        return dict(version=versions[0], files=files, metadata='brew installed metadata and owned files')
    if source == 'npm':
        if not re.fullmatch(r'(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+', name) or any(p in ('.', '..') for p in name.split('/')):
            raise ValueError('invalid npm identifier')
        root = Path(query(execute, ['npm', 'root', '--global']).strip())
        if not root.is_absolute():
            raise ValueError('npm root is not absolute')
        package = root / name
        data = json.loads((package / 'package.json').read_text())
        if data.get('name') != name:
            raise ValueError('npm identity mismatch')
        bins = data.get('bin', {})
        if isinstance(bins, str):
            bins = {name.split('/')[-1]: bins}
        if not isinstance(bins, dict):
            raise ValueError('invalid npm bin metadata')
        entries = []
        for relative in bins.values():
            target = (package / relative).resolve()
            if not target.is_relative_to(package.resolve()):
                raise ValueError('npm bin escapes package')
            entries.append(str(target))
        files = owned_tree(package)
        return dict(version=data.get('version'), files=files, entries=entries,
                    metadata=str(package / 'package.json'))
    if source == 'snap':
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
            raise ValueError('invalid snap identifier')
        lines = query(execute, ['snap', 'list', name]).splitlines()
        fields = lines[1].split() if len(lines) == 2 else []
        if len(fields) != 6 or fields[0] != name:
            raise ValueError('snap installed record mismatch')
        root = Path('/snap') / name / 'current'
        if root.resolve().name != fields[2]:
            raise ValueError('snap current mount does not match installed revision')
        metadata = root / 'meta/snap.yaml'
        raw = metadata.read_text()
        apps = snap_app_names(raw, name)
        # Snap's apps mapping is the authoritative exported interface. Base and
        # content snaps may contain an entire filesystem, not standalone apps.
        # Verify the mounted revision and manifest instead of treating every
        # bundled runtime executable or theme file as a public application.
        files = [str(metadata)]
        entries = ['/snap/bin/' + (name if app == name else name + '.' + app) for app in apps]
        return dict(version=fields[1], files=files, entries=entries,
                    metadata=str(metadata), requiresLaunch=bool(apps))
    raise ValueError('unsupported native source: ' + source)


def shared_library(path):
    """ELF shared objects without an interpreter are not command entry points."""
    if path.suffix == '.dylib':
        with path.open('rb') as stream:
            header = stream.read(16)
        if len(header) == 16 and header[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce'):
            return struct.unpack_from('<I' if header[0] in (0xcf, 0xce) else '>I', header, 12)[0] in (6, 9)
        return False
    if not re.search(r'\.so(?:\.|$)', path.name):
        return False
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) < 64 or header[:4] != b'\x7fELF' or header[4] not in (1, 2) or header[5] not in (1, 2):
            return False
        order = '<' if header[5] == 1 else '>'
        if struct.unpack_from(order + 'H', header, 16)[0] != 3:
            return False
        wide = header[4] == 2
        offset = struct.unpack_from(order + ('Q' if wide else 'I'), header, 32 if wide else 28)[0]
        size, count = struct.unpack_from(order + 'HH', header, 54 if wide else 42)
        if count > 1024 or size < 4:
            return False
        for index in range(count):
            stream.seek(offset + index * size)
            data = stream.read(4)
            if len(data) != 4 or struct.unpack(order + 'I', data)[0] == 3:
                return False
        return True


def desktop_launch(path):
    """Read desktop metadata without executing wrappers or supplying input."""
    if path.stat().st_size > 256 * 1024:
        raise ValueError('desktop entry exceeds metadata bound')
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(path.read_text())
    entry = parser['Desktop Entry']
    if entry.get('Type') != 'Application':
        raise ValueError('desktop entry requires a non-application plan')
    terminal = entry.get('Terminal', 'false').lower() == 'true'
    public = not any(entry.get(key, 'false').lower() == 'true' for key in ('NoDisplay', 'Hidden'))
    tokens = shlex.split(entry['Exec'])
    if any(token in ('%f', '%F', '%u', '%U') for token in tokens) and (not public or entry.get('MimeType')):
        raise ValueError('desktop document/handler input requires an isolated application manifest')
    args = []
    for token in tokens:
        if token in ('%f', '%F', '%u', '%U', '%i'):
            continue
        if token == '%c':
            args.append(entry.get('Name', path.stem)); continue
        if token == '%k':
            args.append(str(path)); continue
        token = token.replace('%%', '\0')
        if '%' in token:
            raise ValueError('unsupported desktop field code')
        args.append(token.replace('\0', '%'))
    if not args or Path(args[0]).name in ('sh', 'bash', 'zsh', 'dash', 'env', 'sudo', 'pkexec'):
        raise ValueError('desktop shell or privilege wrapper requires an isolated plan')
    executable = shutil.which(args[0])
    if not executable:
        raise ValueError('desktop executable unavailable')
    args[0] = executable
    declared = list(args)
    if terminal:
        reviewed = safe_arguments(Path(executable).name)
        if len(args) != 1 or reviewed is None:
            raise ValueError('terminal shortcut has no reviewed direct CLI probe; isolated application manifest required')
        args = [executable, *reviewed]
    return dict(desktop=str(path), argv=args, declaredArgv=declared,
                terminal=terminal, public=public, declaredExec=entry['Exec'])


def desktop_command(path):
    return desktop_launch(path)['argv']


def select_entry_points(name, entries, metadata):
    """Select basic launch scope; shared with the report validator."""
    desktops = metadata.get('guiLaunchEntries', [])
    if any(launch['public'] and not launch['terminal'] for launch in metadata.get('desktopLaunchMetadata', [])):
        declared = {launch['argv'][0] for launch in desktops}
        declared.update(metadata.get('guiEntries', []))
        # Preserve every desktop variant, not just the first successful one.
        return [entry for entry in entries if entry in declared]
    if entries and not desktops and not metadata.get('guiEntries'):
        package_name = name.split(':')[0].split('@')[0]
        named = [p for p in entries if Path(p).name == package_name]
        safe = [p for p in entries if safe_arguments(Path(p).name) is not None]
        if named:
            return [named[0]]
        if safe:
            return [safe[0]]
    return list(entries)


def inspect_files(metadata):
    files = metadata['files']
    if not isinstance(files, list) or not files or len(files) > 100000:
        raise ValueError('owned files absent or exceed inspection limit')
    regular, inferred = [], []
    explicit = metadata.get('entries')
    metadata['inspectionScope'] = 'public entry points and sampled resources; not package integrity verification'
    metadata['declaredFileCount'] = len(files)
    for value in files:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError('owned path is not absolute: ' + value)
        private_tree = any(part in ('doc', 'man', 'examples', 'tests', 'node_modules', 'libexec', 'src') for part in path.parts[:-1])
        in_bin = path.parent.name in ('bin', 'sbin') and not private_tree and not any(part in ('share', 'lib', 'lib32', 'lib64') for part in path.parts[:-1])
        desktop = path.suffix == '.desktop' and path.parent.name == 'applications' and not private_tree
        bundle = path.suffix == '.app' and not private_tree
        required = value in (explicit or []) or (explicit is None and (in_bin or desktop or bundle)) or value == metadata['metadata']
        # Package manifests also list optional documentation, protected runtime
        # state, and masked units. Their absence is not a failed application
        # launch. Inspect public entry points and a bounded resource sample.
        if not required and len(regular) >= 32:
            continue
        try:
            if not path.exists():
                if required: raise ValueError('owned public entry point missing or broken symlink: ' + value)
                continue
            if path.is_dir():
                if bundle:
                    _, executable = bundle_info(path)
                    plist = path / 'Contents/Info.plist'
                    for owned in (plist, executable):
                        if not owned.is_file():
                            raise ValueError('bundle owned file missing: ' + str(owned))
                        regular.append(str(owned))
                    inferred.append(str(executable))
                    metadata.setdefault('guiEntries', []).append(str(executable))
                continue
            if not path.is_file():
                if required: raise ValueError('public entry point is not a regular file: ' + value)
                continue
        except PermissionError:
            if required: raise
            continue
        regular.append(value)
        if explicit is None and desktop:
            if re.search(r'^Exec=', path.read_text(), re.MULTILINE):
                launch = desktop_launch(path)
                key = 'terminalLaunchEntries' if launch['terminal'] else 'guiLaunchEntries'
                metadata.setdefault(key, []).append(dict(desktop=value, argv=launch['argv']))
                metadata.setdefault('desktopLaunchMetadata', []).append(launch)
                inferred.append(launch['argv'][0])
        elif explicit is None and in_bin:
            inferred.append(value)
    # npm bin and snap apps are authoritative public entry-point declarations;
    # executable build scripts and runtime files inside them are not public CLIs.
    entries = sorted(set(inferred if explicit is None else explicit))
    desktops = metadata.get('guiLaunchEntries', [])
    commands = {}
    for entry in entries:
        variants = []
        for launch in desktops:
            if launch['argv'][0] == entry and launch['argv'] not in variants:
                variants.append(launch['argv'])
        if len(variants) == 1:
            commands[entry] = variants[0]
    if desktops:
        metadata['guiCommands'] = commands
        # One launch per distinct argv; identical desktop aliases share evidence.
        entries = [entry for entry in entries for _ in range(max(1, len({tuple(d['argv']) for d in desktops if d['argv'][0] == entry})))]
    if not regular and not entries:
        raise ValueError('package has no inspectable files; needs explicit override')
    return regular, entries


def file_evidence(files, entries, metadata):
    required = set(entries)
    required.update(launch['desktop'] for key in ('guiLaunchEntries', 'terminalLaunchEntries') for launch in metadata.get(key, []))
    required.add(metadata['metadata'])
    sample = [path for index, path in enumerate(files) if index < 32 or path in required or path.endswith(('.desktop', '/Contents/Info.plist'))]
    return dict(inspectedFiles=sample, inspectedFileCount=len(files),
                inspectedFilesSha256=hashlib.sha256(json.dumps(files, separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest())


def baseline(record, selected_sources, execute, *, roots=('/Applications', '/System/Applications'), observer=installed_metadata):
    inventory_id = record['id']
    source, separator, name = inventory_id.partition(':')
    result = dict(id='native:' + inventory_id, inventoryIds=[inventory_id], adapter=source,
                  baseline=[], extensions=[], status='fail')
    checks = result['baseline']
    try:
        if not separator or source not in selected_sources or source not in SOURCES:
            raise ValueError('unsupported or unselected native source: ' + source)
        metadata = observer(source, name, execute, roots)
        files, entries = inspect_files(metadata)
        candidates = list(entries)
        entries = select_entry_points(name, entries, metadata)
        evidence = file_evidence(files, entries, metadata)
        checks.append(dict(check='availability', status='pass', metadata=metadata['metadata'],
                           **evidence, inspectionScope=metadata['inspectionScope'], declaredFileCount=metadata['declaredFileCount'], availableEntryPoints=candidates, launchScope='basic package/application launch; not exhaustive subcommand verification', entryPoints=entries, guiEntries=metadata.get('guiEntries', []),
                           guiCommands=metadata.get('guiCommands', {}), guiLaunchEntries=metadata.get('guiLaunchEntries', []),
                           terminalLaunchEntries=metadata.get('terminalLaunchEntries', []),
                           desktopLaunchMetadata=metadata.get('desktopLaunchMetadata', []),
                           untestedEntryPoints=sorted(set(candidates) - set(entries))))
        version = metadata.get('version')
        checks.append(dict(check='version', status='pass' if isinstance(version, str) and bool(version) and version == record.get('version') else 'fail',
                           observed=version, expected=record.get('version')))
        if not entries and not metadata.get('requiresLaunch'):
            checks.append(dict(check='launch', status='not-applicable',
                               reason='installed metadata declares no public application entry points; resource availability is not full package integrity',
                               evidence=dict(metadata=metadata['metadata'], **evidence)))
        else:
            launches = []
            desktop_commands = {}
            for launch in metadata.get('guiLaunchEntries', []):
                variants = desktop_commands.setdefault(launch['argv'][0], [])
                if launch['argv'] not in variants:
                    variants.append(launch['argv'])
            for entry in entries:
                path = Path(entry)
                args = safe_arguments(path.name)
                if not path.is_file() or not os.access(path, os.X_OK):
                    launches.append(dict(status='fail', executable=entry, detail='entry point missing or not executable'))
                elif entry in desktop_commands:
                    launches.append(execute(desktop_commands[entry].pop(0), 3, startup=True))
                elif entry in metadata.get('guiCommands', {}):
                    launches.append(execute(metadata['guiCommands'][entry], 3, startup=True))
                elif entry in metadata.get('guiEntries', []):
                    launches.append(execute([entry], 3, startup=True))
                elif args is None or path.suffix == '.desktop':
                    launches.append(dict(status='fail', executable=entry, detail='no reviewed safe invocation; add an isolated application manifest'))
                else:
                    launches.append(execute([entry, *args], 10))
            checks.append(dict(check='launch', status='pass' if launches and all(v.get('status') == 'pass' for v in launches) else 'fail', invocations=launches))
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, ExpatError, configparser.Error) as exc:
        failed_check = 'launch' if checks else 'availability'
        checks.append(dict(check=failed_check, status='fail', detail=str(exc)))
    # Even metadata failures retain all three concrete baseline outcomes.
    for check in ('availability', 'version', 'launch'):
        if not any(c['check'] == check for c in checks):
            checks.append(dict(check=check, status='fail', detail='native metadata inspection failed; check could not run'))
    result['status'] = 'pass' if all(c['status'] in ('pass', 'not-applicable') for c in checks) else 'fail'
    return result
