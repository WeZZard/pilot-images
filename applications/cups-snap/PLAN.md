# CUPS Snap readiness

- This plan covers exactly `snap:cups`.
- The baseline runs the installed `/snap/bin/cups.lpstat -r` command. Its exit code alone does not establish scheduler readiness.
- The required `service.py` extension uses the C locale and requires the exact response `scheduler is running`.
- The extension independently requires `snap.cups.cupsd.service` to be loaded, active, and running, with a positive `MainPID` and `Result=success`.
- A stopped scheduler, a zero PID, a failed unit result, or an unreadable service state fails the plan even when the baseline command exits successfully.
- The check does not modify configuration, restart services, submit print jobs, or claim that a printer is reachable.
