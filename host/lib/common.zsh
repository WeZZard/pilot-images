# Shared helpers for pilot-images host scripts. zsh only. Safe under `set -e` callers:
# helpers use if-statements rather than bare && chains.

log()  { print -- "[$(date +%H:%M:%S)] $*" }
warn() { print -- "[$(date +%H:%M:%S)] WARN: $*" >&2 }
die()  { print -- "FATAL: $*" >&2; exit 1 }

# Bind to the checkout containing this library, not caller-controlled REPO_ROOT.
if (( ${+VM_ENVIRONMENT_FILE} && ! ${+_PILOT_ENVIRONMENT_BOUND} )); then
  _pilot_environment_tool="${${(%):-%x}:A:h:h}/environment.py"
  _pilot_environment_exports=$(python3 "$_pilot_environment_tool" --shell) || die "selected environment resolution failed"
  eval "$_pilot_environment_exports"
  unset _pilot_environment_tool _pilot_environment_exports
  typeset -gr _PILOT_ENVIRONMENT_BOUND=1
  typeset -gr _PILOT_TART_EXECUTABLE="$TART" _PILOT_TART_HOME="$TART_HOME"
  typeset -gr VM_ENVIRONMENT_FILE VM_ENVIRONMENT_FINGERPRINT PILOT_REPO TART_HOME VM_SERVICE_STATE PILOT_IMAGES_STATE_DIR VM_RELAY_STATE_DIR VM_RELAY_URL VM_SERVICE_HOST VM_SERVICE_PORT VMCTL TART
fi
if (( ${+_PILOT_ENVIRONMENT_BOUND} )); then
  # The selected executable/store cannot drift after sourcing an image config.
  tart() { command /usr/bin/env "TART_HOME=$_PILOT_TART_HOME" "$_PILOT_TART_EXECUTABLE" "$@"; }
fi

# Tart owns a separate process session. Cancelling a build must not implicitly
# kill its VM through a shared process group. Retain only the maintenance lock.
tart_background() {
  local executable=tart
  if (( ${+_PILOT_ENVIRONMENT_BOUND} )); then executable="$_PILOT_TART_EXECUTABLE"; fi
  python3 -c 'import os,subprocess,sys
fd=os.environ.get("PILOT_MAINTENANCE_FD")
keep=() if fd is None else (int(fd),)
for n in keep: os.fstat(n)
p=subprocess.Popen(sys.argv[1:],stdin=subprocess.DEVNULL,start_new_session=True,pass_fds=keep)
print("Tart process started: pid="+str(p.pid),flush=True)' "$executable" "$@"
}

# Password-only, no agent keys: prevents "Too many authentication failures" when the
# host agent holds several identities (each offered key consumes a guest MaxAuthTries slot).
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8
          -o LogLevel=ERROR -o PreferredAuthentications=password -o PubkeyAuthentication=no
          -o NumberOfPasswordPrompts=1)

require() {
  if ! command -v "$1" >/dev/null 2>&1; then die "required tool missing: $1"; fi
}

vm_exists()  { tart list 2>/dev/null | awk '{print $2}' | grep -qx -- "$1" }
vm_running() { tart list 2>/dev/null | awk -v v="$1" '$2==v {print $NF}' | grep -q running }

vm_logfile() {
  if [[ -n "${VM_ENVIRONMENT_FILE:-}" ]]; then
    mkdir -p "$PILOT_IMAGES_STATE_DIR/logs" || return 1
    print -r -- "$PILOT_IMAGES_STATE_DIR/logs/tart-run-$1.log"
  else
    print -r -- "/tmp/tart-run-$1.log"
  fi
}

vm_start_headless() {  # vm_start_headless <vm> [logfile]
  local vm=$1 logfile=${2:-}
  if [[ -z "$logfile" ]]; then logfile=$(vm_logfile "$vm") || return 1; fi
  if vm_running "$vm"; then return 0; fi
  log "starting $vm (headless), log: $logfile"
  tart_background run "$vm" --no-graphics > "$logfile" 2>&1
}

wait_ip() {  # wait_ip <vm> [timeout_s] -> prints IP
  local vm=$1 timeout=${2:-240} t=0 ip=""
  while (( t < timeout )); do
    ip=$(tart ip "$vm" 2>/dev/null || true)
    if [[ -n "$ip" ]]; then print -- "$ip"; return 0; fi
    sleep 3
    t=$(( t + 3 ))
  done
  return 1
}

# Password-auth ssh/scp (cirrus default credentials; key auth also works once installed).
# Identity used by vssh/vscp/wait_ssh. Defaults to the image account; build-base
# overrides SSH_USER/SSH_PASS to the seed account during the pre-provision
# account-setup step, then switches to the image account.
pilot_ssh_cleanup() {
  if [[ -n "${_PILOT_SSH_DIR:-}" ]]; then
    local target
    for target in "${_PILOT_SSH_TARGETS[@]}"; do
      ssh "${SSH_OPTS[@]}" -O exit "$target" >/dev/null 2>&1 || true
    done
    [[ "$_PILOT_SSH_DIR" == /tmp/pilot-ssh.* ]] && /bin/rm -rf -- "$_PILOT_SSH_DIR"
  fi
}

pilot_ssh_session() {  # Reuse authenticated transport, never guest commands.
  local target=$1
  if [[ -z "${_PILOT_SSH_DIR:-}" ]]; then
    # The macOS AF_UNIX limit is short; the ordinary TMPDIR path is too long.
    _PILOT_SSH_DIR=$(mktemp -d /tmp/pilot-ssh.XXXXXXXX) || return 1
    typeset -ga _PILOT_SSH_TARGETS; _PILOT_SSH_TARGETS=()
    SSH_OPTS+=(-o ControlMaster=auto -o ControlPersist=600 -o "ControlPath=$_PILOT_SSH_DIR/%C"
               -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
    autoload -Uz add-zsh-hook
    add-zsh-hook zshexit pilot_ssh_cleanup
  fi
  if (( ! ${_PILOT_SSH_TARGETS[(Ie)$target]} )); then _PILOT_SSH_TARGETS+=("$target"); fi
}

vssh() {  # vssh <ip> <command...>
  local ip=$1; shift
  pilot_ssh_session "${SSH_USER:-$GUEST_USER}@$ip" || return 1
  sshpass -p "${SSH_PASS:-$GUEST_PASS}" ssh "${SSH_OPTS[@]}" "${SSH_USER:-$GUEST_USER}@$ip" "$@"
}

vscp() {  # vscp <ip> <src...> <remote-dst>
  local ip=$1; shift
  local dst="${@[-1]}"
  local -a srcs; srcs=("${@[1,-2]}")
  pilot_ssh_session "${SSH_USER:-$GUEST_USER}@$ip" || return 1
  sshpass -p "${SSH_PASS:-$GUEST_PASS}" scp "${SSH_OPTS[@]}" -r "${srcs[@]}" "${SSH_USER:-$GUEST_USER}@$ip:$dst"
}

wait_ssh() {  # wait_ssh <ip> [timeout_s]
  # Require TWO consecutive OKs: macOS password auth (opendirectoryd) is racy in
  # the first seconds of boot — one lucky success then a refusal is common, so a
  # single probe is not enough to call SSH ready.
  local ip=$1 timeout=${2:-300} t=0 ok=0
  while (( t < timeout )); do
    if vssh "$ip" true 2>/dev/null; then
      ok=$(( ok + 1 ))
      if (( ok >= 2 )); then return 0; fi
    else
      ok=0
    fi
    sleep 3
    t=$(( t + 3 ))
  done
  return 1
}

vssh_retry() {  # vssh_retry <ip> <command...> — tolerate transient early-boot auth refusals
  local ip=$1; shift
  local n=0
  while (( n < 30 )); do
    if vssh "$ip" "$@"; then return 0; fi
    sleep 4
    n=$(( n + 1 ))
  done
  return 1
}

vscp_retry() {  # vscp_retry <ip> <src...> <remote-dst> — same, for scp transfers
  local n=0
  while (( n < 30 )); do
    if vscp "$@"; then return 0; fi
    sleep 4
    n=$(( n + 1 ))
  done
  return 1
}
