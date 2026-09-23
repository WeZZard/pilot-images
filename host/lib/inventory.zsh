# Source after common.zsh and line.conf. No automatic collection on source.
# Raw stdout is streamed unchanged to an immutable per-run evidence directory;
# login+interactive shell loads macOS nvm/Homebrew setup before python3 discovery.
inventory_init() {
  require python3
  INVENTORY_TOOL="$REPO_ROOT/host/inventory.py"
  INVENTORY_ROOT="${TART_HOME:-$HOME/.tart}/vms"
  INVENTORY_STATE=$(python3 "$INVENTORY_TOOL" state-path --root "$INVENTORY_ROOT") || return 1
  WORK_INVENTORY="$INVENTORY_STATE/work/$LINE.json"
  BASE_INVENTORY="$INVENTORY_STATE/base/$LINE.json"
  PENDING_INVENTORY="$INVENTORY_STATE/pending/$LINE.json"
  PORTABLE_INVENTORY="$REPO_ROOT/images/$LINE/applications.json"
  ACCEPTANCE_TOOL="$REPO_ROOT/host/application-acceptance.py"
  WORK_ACCEPTANCE="$INVENTORY_STATE/acceptance/work/$LINE.json"
  FRESH_WORK_ACCEPTANCE="$INVENTORY_STATE/acceptance/fresh-work/$LINE.json"
  mkdir -p "$INVENTORY_STATE/extracted"
}

inventory_invalidate() {
  # Any replacement/refresh invalidates fresh-work certification first.
  if [[ "$1" == "$WORK_INVENTORY" || "$1" == "$BASE_INVENTORY" ]]; then
    python3 "$INVENTORY_TOOL" invalidate --output "$FRESH_WORK_ACCEPTANCE" || return 1
  fi
  python3 "$INVENTORY_TOOL" invalidate --output "$1"
}

inventory_stopped() {
  # Unknown/list failures must not be mistaken for stopped. No grep pipeline.
  local listing state
  listing=$(tart list) || die "cannot establish Tart state"
  state=$(print -r -- "$listing" | awk -v v="$1" '$2==v {print $NF}')
  [[ "$state" == stopped ]] || die "$1 must be known stopped (got: $state)"
}

inventory_extract() { # <ip>; sets RAW_INVENTORY (original preserved on all failures)
  local ip=$1 evidence
  evidence=$(mktemp -d "$INVENTORY_STATE/extracted/$LINE-XXXXXXXX") || return 1
  RAW_INVENTORY="$evidence/inventory.json"
  vssh "$ip" 'mkdir -p /tmp/payload/inventory' || return 1
  vscp "$ip" "$REPO_ROOT/inventory/collect.py" "$REPO_ROOT/inventory/aliases.json" /tmp/payload/inventory/ || return 1
  # Write on the guest, not stdout of the login shell (startup chatter isn't JSON).
  vssh "$ip" "$GUEST_SHELL -lic 'python3 /tmp/payload/inventory/collect.py --aliases /tmp/payload/inventory/aliases.json > /tmp/payload/inventory/installed.json'" > "$evidence/extraction.log" 2>&1 || return 1
  vssh "$ip" 'cat /tmp/payload/inventory/installed.json' > "$RAW_INVENTORY" || return 1
  # Retain exact payload versions beside the extracted original for provenance.
  cp "$REPO_ROOT/inventory/collect.py" "$REPO_ROOT/inventory/aliases.json" "$evidence/" || return 1
  # Run on the guest's ordinary noninteractive SSH PATH. No -lic, nvm or repair.
  APPLICATION_REPORT="$evidence/applications.json"
  vscp "$ip" "$REPO_ROOT/applications" /tmp/payload/ || return 1
  vssh "$ip" "mkdir -p /tmp/payload/images/$LINE" || return 1
  vscp "$ip" "$REPO_ROOT/images/$LINE/guest" "/tmp/payload/images/$LINE/" || return 1
  vscp "$ip" "$REPO_ROOT/images/$LINE/application-tests.json" /tmp/payload/application-tests.json || return 1
  local check_status=0
  vssh "$ip" "python3 /tmp/payload/applications/check.py --selection /tmp/payload/application-tests.json --inventory /tmp/payload/inventory/installed.json --build-id ${evidence:t} --output /tmp/payload/application-report.json" > "$evidence/application-check.log" 2>&1 || check_status=$?
  vssh "$ip" 'cat /tmp/payload/application-report.json' > "$APPLICATION_REPORT" || return 1
  if (( check_status != 0 )); then
    warn "application acceptance failed (exit $check_status); report: $APPLICATION_REPORT; log: $evidence/application-check.log"
    return 1
  fi
  # Validate the final guest state AFTER application launches, so tests cannot
  # create credentials or change image settings after the last required check.
  local name script extension check_rc remote
  case "$GUEST_SHELL" in
    zsh) extension=zsh ;;
    bash|sh) extension=sh ;;
    *) warn "unsupported image check interpreter: $GUEST_SHELL"; return 1 ;;
  esac
  remote="/tmp/payload/image-checks-${evidence:t}"
  vssh "$ip" "mkdir -p $remote" || return 1
  for name in acceptance no-secrets; do
    script="$REPO_ROOT/images/$LINE/checks/$name.$extension"
    [[ -f "$script" ]] || { warn "missing required image check: $script"; return 1; }
    cp "$script" "$evidence/${script:t}" || return 1
    vscp "$ip" "$evidence/${script:t}" "$remote/${script:t}" || return 1
    check_rc=0
    vssh "$ip" "DISPLAY_W=${DISPLAY_W:-} DISPLAY_H=${DISPLAY_H:-} XCODE_VERSION=${XCODE_VERSION:-} $GUEST_SHELL $remote/${script:t}" > "$evidence/$name.log" 2>&1 || check_rc=$?
    python3 "$ACCEPTANCE_TOOL" record-image-check --image "$LINE" --evidence "$evidence" \
      --name "$name" --script "$script" --returncode "$check_rc" || return 1
    (( check_rc == 0 )) || { warn "$name failed; retained evidence: $evidence"; return 1; }
  done
}

inventory_bind() { # <vm> <output> [previous association]
  local vm=$1 output=$2
  if [[ "$output" == "$WORK_INVENTORY" ]]; then
    python3 "$INVENTORY_TOOL" invalidate --output "$FRESH_WORK_ACCEPTANCE" || return 1
  fi
  local portable="$PENDING_INVENTORY" mode=work
  local -a previous; previous=()
  if [[ "$output" == "$BASE_INVENTORY" ]]; then
    portable="$PORTABLE_INVENTORY"; mode=base-maintenance
  fi
  if (( $# == 3 )); then
    previous=(--previous "$3")
  else
    previous=(--mode "$mode" --evidence-id "${RAW_INVENTORY:h:t}" \
      --collector "${RAW_INVENTORY:h}/collect.py" --aliases "${RAW_INVENTORY:h}/aliases.json")
  fi
  inventory_stopped "$vm"
  # Reject stale/failed acceptance before exposing even a transient association.
  local -a validation_input
  if (( $# == 3 )); then
    # Promotion uses the fresh clone's actual raw hash/build ID, not work's.
    validation_input=(--raw "$APPLICATION_RAW")
  else
    validation_input=(--raw "$RAW_INVENTORY")
  fi
  python3 "$ACCEPTANCE_TOOL" validate --report "$APPLICATION_REPORT" --image "$LINE" "${validation_input[@]}" || return 1
  python3 "$INVENTORY_TOOL" bind --output "$output" --raw "$RAW_INVENTORY" --portable "$portable" \
    --root "$INVENTORY_ROOT" --vm "$vm" --image "$LINE" --os "$LINE_KIND" "${previous[@]}" || return 1
  local receipt="$INVENTORY_STATE/acceptance/base/$LINE.json"
  [[ "$output" != "$WORK_INVENTORY" ]] || receipt="$WORK_ACCEPTANCE"
  local -a report_input; report_input=()
  if (( $# == 3 )); then report_input=(--raw "$APPLICATION_RAW" --image-receipt "$WORK_ACCEPTANCE"); fi
  if ! python3 "$ACCEPTANCE_TOOL" seal --association "$output" --portable "$portable" --receipt "$receipt" --report "$APPLICATION_REPORT" --image "$LINE" "${report_input[@]}"; then
    inventory_invalidate "$output"
    return 1
  fi
}

inventory_verify_fresh_work() {
  inventory_stopped "$WORK_VM"
  local result
  result=$(python3 "$ACCEPTANCE_TOOL" verify-fresh --association "$WORK_INVENTORY" --portable "$PENDING_INVENTORY" \
    --receipt "$FRESH_WORK_ACCEPTANCE" --image "$LINE" --root "$INVENTORY_ROOT" --vm "$WORK_VM" --os "$LINE_KIND") || return 1
  local -a paths; paths=("${(@f)result}")
  (( ${#paths} == 2 )) || return 1
  APPLICATION_REPORT="$paths[1]"
  APPLICATION_RAW="$paths[2]"
}

inventory_verify_work() {
  inventory_stopped "$WORK_VM"
  python3 "$INVENTORY_TOOL" verify --output "$WORK_INVENTORY" --portable "$PENDING_INVENTORY" \
    --root "$INVENTORY_ROOT" --vm "$WORK_VM" --image "$LINE" --os "$LINE_KIND" || return 1
  APPLICATION_REPORT=$(python3 "$ACCEPTANCE_TOOL" verify --association "$WORK_INVENTORY" --portable "$PENDING_INVENTORY" --receipt "$WORK_ACCEPTANCE" --image "$LINE") || return 1
}
