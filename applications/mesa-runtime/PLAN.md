# Mesa content runtime readiness

- This plan covers exactly `snap:mesa-2404`.
- The baseline executes a Python ctypes probe against the installed Mesa EGL library. The manifest embeds the exact source of `runtime-info.py` so the baseline does not depend on the checkout location. The fixture checks that both copies match.
- The probe initializes a surfaceless software EGL display, reads its vendor and version, and verifies through `/proc/self/maps` that the Mesa implementation came from the current mounted Snap revision. It fails if the display cannot initialize or the installed Mesa implementation cannot be proved.
- The probe uses the installed Snap vendor configuration and library paths. It disables the shader cache and does not connect to a display server, create a window, or start a browser. This proves software EGL runtime readiness, not hardware acceleration or browser rendering readiness.
- The required service extension checks the installed Snap revision, the declared content interfaces, the monitor application metadata, and the installed connect and disconnect hooks. Unknown hook contents or metadata layouts require review and fail closed.
- The extension requires Firefox's `gpu-2404` plug to be connected to `mesa-2404:gpu-2404`. This is content linkage evidence, not evidence that Firefox rendered a page.
- When the `kernel-gpu-2404` plug is disconnected, the installed disconnect hook explicitly disables the component monitor. Only that monitor subcheck is `not-applicable`, and only when the actual unit is loaded, disabled, inactive, and dead with PID zero and a successful result. The output explicitly makes no daemon launch claim.
- When the kernel content plug is connected, the monitor must already be active and running with a positive PID and a successful result. A connected but dead monitor fails the extension.
- The extension as a whole passes only when its applicable metadata, linkage, and policy checks pass. The independent real EGL baseline remains mandatory; a disabled monitor alone can never establish runtime readiness.
- No check installs packages, changes interfaces, runs hooks, or starts or restarts the monitor.
