# socat baseline

- Ubuntu phase 40 explicitly installs socat for guest browser forwarding.
- The shared baseline verifies availability and runs `socat -V`, which reports its version and compiled features without opening a listener or forwarding traffic.
- Network forwarding behavior is outside this basic launch test and can be verified by a task-specific test when needed.
