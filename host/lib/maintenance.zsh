# Acquire by exec before any lifecycle mutation. No PID files, traps, unlink, or
# stale takeover. Keep the descriptor open through shell and child lifetimes.
maintenance_enter() { # <line> <script> [original arguments...]
  local line=$1 script=$2
  shift 2
  require python3
  if [[ -n "${PILOT_MAINTENANCE_FD:-}" ]]; then
    python3 "$SCRIPT_DIR/maintenance-lock.py" check "$line" || die "maintenance lock verification failed"
    # Only this re-exec may consume the marker. Descendants retain the lock fd,
    # but a nested entrypoint must contend instead of treating it as permission.
    unset PILOT_MAINTENANCE_FD
  else
    exec python3 "$SCRIPT_DIR/maintenance-lock.py" acquire "$line" zsh "$script" "$@"
  fi
}
