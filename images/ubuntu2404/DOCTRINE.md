# Ubuntu line (ubuntu2404) — GUI VM doctrine

Authoritative spec for the `ubuntu2404` image line. Moved verbatim from
`~/CLAUDE.md` on 2026-08-12 as part of adopting the line into this repo;
CLAUDE.md now keeps a pointer here. The guest scripts and checks in this
directory implement this doctrine.

## GUI Virtual Machine Baseline

This Mac mini is the designated local Linux/Tart host. Maintain one canonical
credential-free Ubuntu golden image named `pilot-ubuntu-base`. Create
purpose-specific instances as local copy-on-write clones named
`pilot-<purpose>`; for example, `pilot-x-reference`.

- Put common Ubuntu packages and operating-system, desktop, network, browser,
  and HiDPI defaults in `pilot-ubuntu-base` first.
- The common GUI image MUST include `fonts-noto-cjk`,
  `fonts-noto-cjk-extra`, and `fonts-noto-color-emoji`, refresh the font cache
  after installation, and verify that both `Noto Sans CJK SC` and
  `Noto Sans CJK TC` resolve before the image is accepted.
- On the Apple Silicon ARM64 Ubuntu image, use Mozilla's Firefox snap as the
  primary compatibility/reference browser and Canonical's Chromium snap as the
  secondary automation/diagnostic browser. Do not substitute the x86-64 Google
  Chrome Linux package or add emulation to the golden image.
- The common GUI image also carries generic browser-automation tooling, in the
  same category as the fonts and browser snaps above and never role-specific:
  Node.js, `socat`, a pinned `@playwright/mcp` with its Chromium and
  Firefox browser builds pre-fetched (added 2026-09-05; see
  `.handoff/2026-09-05-ubuntu-browser-automation-tooling.md` and its
  addendum), and a pinned `@playwright/cli` bundling the same Playwright
  (added 2026-09-06; see `.handoff/2026-09-06-ubuntu-playwright-cli.md`).
  Purpose clones for browser lanes are driven from the Mac over SSH as
  `admin` in a non-interactive shell; `sshd` stays enabled in the base, as it
  is today. The line between the base and a purpose clone's additions: the
  base carries the runtime, the browsers, and the two Playwright fronts, all
  pinned and idle; a clone adds, at run time and never to the base, its port
  forwarders, output directories, session names, environment variables, and
  any agent configuration such as skill files.
- The base also carries a C toolchain (`gcc` + `linux-libc-dev`) and a
  pre-built `hwcap_mask` getauxval shim at `/usr/lib/hwcap_mask.so`, in the
  same generic-tooling category as the fonts and snaps: on M4/M5 hosts Apple
  Virtualization.framework advertises ARMv9 (SVE/SME) HWCAP bits it cannot
  execute, which intermittently SIGILLs Chromium (V8, Skia, BoringSSL,
  libjpeg-turbo, zlib); preloading the shim masks those bits to the ARMv8
  baseline (added 2026-09-19; see
  `.handoff/2026-09-18-ubuntu2404-gcc-and-hwcap-shim.md`). The shim is a
  generic, credential-free hypervisor workaround — not role-specific
  automation — so the pre-built image copy (the handoff's optional
  hardening) is acceptable. The shim source is vendored at
  `guest/hwcap/hwcap_mask.c`, identical to the consuming repo's copy
  (AnyDict ADR-0028 D6); a session may still build its own from its
  vendored source as a fallback, which is what the toolchain is for. The
  base never preloads the shim globally (no `/etc/ld.so.preload`) —
  choosing to preload stays the session's call.
- First-login wizards are suppressed at provisioning, before the first GUI
  login: a modal that only a human can dismiss is a build defect (the macOS
  line's MiniBuddy doctrine), and every clone inherits it. Phase 00 writes
  the package-supported `~/.config/gnome-initial-setup-done` marker
  (`AutostartCondition=unless-exists`, added 2026-09-19 after a manual close
  had to be baked into that day's base), and acceptance asserts both the
  marker and the absence of the wizard process, because checking the marker
  alone proves nothing.
- Never put credentials, authenticated browser profiles, private task data, or
  role-specific automation into `pilot-ubuntu-base`.
- A Tart clone may share APFS storage extents with its source, but its writable
  virtual disk is logically independent. Changing the base does not mutate an
  existing role instance.
- Maintain and verify the base through a controlled maintenance boot, then
  create new role instances from it. Never convert an authenticated instance
  back into the base or distribute an authenticated instance.
- On the attached 5K Studio Display, the default windowed Linux GUI
  presentation is a 3840x2160 pixel virtual display with 200 percent integer
  desktop scaling, producing a 1920x1080 logical workspace. This is the Retina
  equivalent of the former 1920x1080 window. Use 5120x2880 pixels at 200
  percent only for an explicitly full-screen 2560x1440 logical workspace.

### Interactive Linux display contract

1. Tart MUST remain the VM runtime: it owns the VM process, storage, devices,
   networking, and lifecycle.
2. Interactive Linux GUI sessions MUST start Tart with its experimental VNC
   server and without Tart's built-in graphics window. The required launch
   combination is `--vnc-experimental --no-graphics` plus the VM's normal
   network and clipboard-isolation arguments.
3. macOS Screen Sharing MUST be the interactive display client. Open the
   password-protected `vnc://` URL emitted by Tart in a fresh Screen Sharing
   process. The URL MUST point to `127.0.0.1`, use Tart's random ephemeral port,
   and retain Tart's generated ephemeral password.
4. The default windowed Retina contract is exactly 3840x2160 guest pixels,
   GNOME 200 percent integer scaling, and a 1920x1080 logical workspace.
5. Do not present a high-density Linux guest through Tart's built-in VM window.
   Tart 2.32.1 uses the Linux scanout's pixel width and height as the macOS
   window's point width and height, so it cannot produce a same-sized Retina
   window.
6. For unattended work, launch Tart with `--no-graphics` and no Screen Sharing
   client. The guest desktop and headed browser continue rendering inside the
   VM without a host viewer window.
7. Acceptance requires all of the following: Tart reports a 3840x2160 display;
   the active Linux DRM mode is 3840x2160; GNOME reports scale factor 2; Screen
   Sharing connects through loopback in a resizable window; and Tart's built-in
   Linux window is absent.

For every single-purpose GUI virtual machine created or managed for unattended
agent work, the following are mandatory:

1. **Passwordless desktop entry:** configure automatic login to the designated
   VM user. Booting, rebooting, or recovering the graphical session MUST NOT
   require a login password. The Unix account may retain a maintenance password
   for `sudo`; do not make the Unix password blank merely to achieve automatic
   desktop login.
2. **Always-on unlocked session:** long inactivity MUST leave the VM in the same
   unlocked desktop session. Disable idle dimming, screen blanking, screensaver
   activation, screen locking, automatic logout, suspend, hibernate, and hybrid
   sleep. Resume-after-idle MUST NOT return to a greeter or request a password.
3. **Layered enforcement:** configure the desktop environment and also disable
   the operating system's sleep/hibernate targets so a desktop preference reset
   cannot silently re-enable inactivity suspension.
4. **Acceptance test:** after provisioning, reboot and verify automatic desktop
   login; then leave the VM untouched for longer than its former/default idle
   timeout and verify that the original unlocked session remains active. Merely
   checking configuration files is not sufficient.
