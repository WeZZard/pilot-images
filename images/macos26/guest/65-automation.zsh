#!/bin/zsh
# Phase 65 — Apple Events (Automation) grant for osascript run over SSH.
#
# macOS attributes Apple Events sent from an SSH session to the session's
# responsible process, /usr/libexec/sshd-keygen-wrapper, and the first script
# against each app asks the console user to approve "sshd-keygen-wrapper wants
# access to control <App>". Nothing headless can answer that sheet and every
# clone inherits the missing grant. Measured 2026-09-26 in a relay clone:
# `osascript -e 'tell application "Reminders" to quit'` hung on it until the
# relay's 60 s timeout.
#
# Like phase 60, the GUI consent is replaced by rows written directly to the TCC
# store — valid only because the CI image has SIP disabled. Automation rows
# (kTCCServiceAppleEvents) live in the USER database, one per (client, target
# app). Only sshd-keygen-wrapper is granted, and only towards app bundles that
# ship in the image; both sides are pinned to their designated code requirement
# so a replaced binary does not inherit the grant. Idempotent: reruns replace.
source "${0:A:h}/lib.zsh"

if ! csrutil status 2>/dev/null | grep -qi 'disabled'; then
  glog "SIP is not confirmed disabled; headless TCC provisioning is unsupported"
  exit 1
fi

CLIENT=/usr/libexec/sshd-keygen-wrapper
DB="$HOME/Library/Application Support/com.apple.TCC/TCC.db"
[[ -x "$CLIENT" ]] || { glog "missing Apple Events client $CLIENT"; exit 1 }
[[ -f "$DB" ]] || { glog "no user TCC database at $DB"; exit 1 }

# --- schema gate --------------------------------------------------------------
# TCC row formats change between releases. Refuse to write unless every column
# this phase fills exists and no other NOT NULL column lacks a default.
typeset -a WRITES
WRITES=(service client client_type auth_value auth_reason auth_version csreq
        indirect_object_identifier_type indirect_object_identifier
        indirect_object_code_identity flags last_modified)
SCHEMA=$(sqlite3 "$DB" 'PRAGMA table_info(access);') || { glog "cannot read the access table schema of $DB"; exit 1 }
[[ -n "$SCHEMA" ]] || { glog "no access table in $DB"; exit 1 }
typeset -A PRESENT
while IFS='|' read -r _cid name _type notnull dflt pk; do
  PRESENT[$name]=1
  if [[ "$notnull" == 1 && -z "$dflt" && "$pk" == 0 ]] && (( ! ${WRITES[(Ie)$name]} )); then
    glog "TCC access schema changed: NOT NULL column '$name' has no default and is not written here"
    exit 1
  fi
done <<< "$SCHEMA"
for col in "${WRITES[@]}"; do
  [[ -n "${PRESENT[$col]:-}" ]] || { glog "TCC access schema changed: column '$col' missing"; exit 1 }
done

# --- targets: every app bundle the image ships ---------------------------------
typeset -a TARGETS
TARGETS=()
setopt null_glob
for dir in /Applications /Applications/Utilities /System/Applications /System/Applications/Utilities; do
  for app in "$dir"/*.app; do TARGETS+=("$app"); done
done
unsetopt null_glob
for app in "/System/Library/CoreServices/System Events.app" \
           "/System/Library/CoreServices/Finder.app" \
           "/System/Library/CoreServices/Shortcuts Events.app"; do
  if [[ -d "$app" ]]; then TARGETS+=("$app"); fi
done
(( ${#TARGETS} > 0 )) || { glog "no target app bundles found"; exit 1 }

CLIENT_REQ=$(csreq_hex "$CLIENT") || { glog "cannot compute the designated requirement of $CLIENT"; exit 1 }

# --- rows ---------------------------------------------------------------------
# service           kTCCServiceAppleEvents            (Automation)
# client            path, client_type 1               (sshd-keygen-wrapper)
# auth_value 2      allowed; auth_reason 2 user consent; auth_version 1
# csreq             client's designated requirement
# indirect object   target bundle id (type 0) + target's designated requirement
SQL=$(mktemp)
print -r -- 'BEGIN;' > "$SQL"
GRANTED=0
SKIPPED=0
for app in "${TARGETS[@]}"; do
  bid=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist" 2>/dev/null) || bid=""
  if [[ -z "$bid" || "$bid" == *[^A-Za-z0-9._-]* ]]; then
    glog "skip (no usable bundle id): ${app:t}"
    SKIPPED=$(( SKIPPED + 1 ))
    continue
  fi
  if ! req=$(csreq_hex "$app"); then
    glog "skip (no designated requirement): ${app:t}"
    SKIPPED=$(( SKIPPED + 1 ))
    continue
  fi
  print -r -- "INSERT OR REPLACE INTO access (service,client,client_type,auth_value,auth_reason,auth_version,csreq,indirect_object_identifier_type,indirect_object_identifier,indirect_object_code_identity,flags,last_modified) VALUES ('kTCCServiceAppleEvents','$CLIENT',1,2,2,1,X'$CLIENT_REQ',0,'$bid',X'$req',0,strftime('%s','now'));" >> "$SQL"
  GRANTED=$(( GRANTED + 1 ))
done
print -r -- 'COMMIT;' >> "$SQL"
(( GRANTED > 0 )) || { glog "no target could be granted"; exit 1 }
sqlite3 "$DB" < "$SQL" || { glog "writing Apple Events rows to $DB failed"; exit 1 }
rm -f "$SQL"
# The user tccd caches decisions; restart it so the rows apply to this session.
launchctl kickstart -k "gui/$(id -u)/com.apple.tccd" 2>/dev/null || killall tccd 2>/dev/null || true
sleep 2
glog "Apple Events rows written for $CLIENT: $GRANTED targets, $SKIPPED skipped"

# --- verify from this SSH session: its responsible process IS the client ------
ROWS=$(sqlite3 "$DB" "SELECT count(*) FROM access WHERE service='kTCCServiceAppleEvents' AND client='$CLIENT' AND client_type=1 AND auth_value=2;")
(( ROWS >= GRANTED )) || { glog "expected at least $GRANTED Apple Events rows, found $ROWS"; exit 1 }
for probe in 'tell application "System Events" to get name of every process' \
             'tell application "Finder" to get name of startup disk'; do
  if ! perl -e 'alarm 20; exec @ARGV' osascript -e "$probe" >/dev/null; then
    glog "osascript over SSH is still blocked (consent modal) or failed: $probe"
    exit 1
  fi
done
glog "osascript over SSH reaches System Events and Finder without a consent modal"
glog "phase 65 done"
