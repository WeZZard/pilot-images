# GUI baseline readiness

## Scope

- Linux startup observations resolve the running desktop before launching a headed application.
- Commands without `startup=True` keep their existing environment behavior.
- Startup commands with `--headless`, `--headless=…`, or `-headless` do not discover or modify the desktop context.
- macOS startup commands keep their existing environment behavior.

## Session selection

The resolver requires exactly one active, local, same-user graphical session reported by logind. That session must use X11. An SSH session, a greeter, a different user's desktop, a Wayland session, or multiple active graphical sessions cannot supply the context.

The resolver reads only same-user GNOME shell or GNOME session process metadata. A process must belong to the selected session scope or the same user's exact `org.gnome.Shell@x11.service` unit. The latter supports GNOME's systemd user service layout, where the shell is outside the logind session scope. An exported session ID must agree with logind. Conflicting complete process contexts fail rather than selecting one arbitrarily.

The resolver obtains `DISPLAY` from the desktop process. It never guesses `:0`. It requires a local X11 display, the current user's `/run/user/<uid>` runtime directory and local session bus, an absolute readable same-user Xauthority file, and existing X11 and session-bus sockets. Endpoint checks establish prerequisites, not proof that an application rendered successfully.

## Environment and failure behavior

- Only `DISPLAY`, `XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`, `XDG_CURRENT_DESKTOP`, `XDG_SESSION_DESKTOP`, `XDG_SESSION_TYPE`, and `DESKTOP_SESSION` are copied into the child environment.
- `XDG_SESSION_ID` is inspected for consistency but is not copied into the child environment.
- Stale inherited desktop variables and Wayland or toolkit backend overrides are removed for headed startup operations only.
- The existing caller environment remains otherwise unchanged. The resolver does not copy desktop process secrets, `PATH`, agent sockets, or arbitrary environment entries.
- The resolver never prints or persists complete process environments. It reads only the Xauthority file's metadata and access permissions, not its cookies.
- Missing or ambiguous context produces a failed command result whose detail starts with `GUI context unavailable:`. The application is not launched.
- Discovery uses read-only `loginctl` and `/proc` inspection. It does not install software, create a desktop session, change permissions, modify configuration, or repair authentication.
- A successful launch still means only that the process remained alive through the bounded startup observation. The existing startup evidence contract is unchanged.

## Packaging and progress

`gui.py` is loaded relative to `check.py`, so a staged application tree does not depend on the working directory or an installed Python package. The plan digest includes `gui.py`. Deployment must copy it with the application tree.

Library callers can pass `progress(name, status)` to `run()`. The callback runs once after each explicit or native application completes. An installed but unsupported application is converted to failure before notification. The default is silent. The command-line runner writes only the JSON-quoted application name and final status to stderr and flushes each line. It does not print arguments, process output, desktop context, or secrets in progress messages.

## Verification

Run the fixture tests without accessing a VM:

```sh
python3 -m unittest discover -s tests -p test_gui_baseline.py -v
```

The tests cover session selection, ambiguity and unknown contexts, environment allowlisting, visible pre-launch failures, headless and macOS isolation, relative staged imports, digest sensitivity, and optional flushed progress output.

The resolver was also checked through read-only metadata queries against the isolated acceptance work VM selected by `$HOME/.local/state/vm-environments/relay-acceptance-20260916/environment.json`. It resolved the active GNOME X11 context successfully. No application launch or VM lifecycle operation was needed for this check.
