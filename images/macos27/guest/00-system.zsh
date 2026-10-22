#!/bin/zsh
# Phase 00 — system baseline: disk, SSH key, shell, always-on unlocked session (doctrine).
source "${0:A:h}/lib.zsh"

# A VM's container must fill the virtual disk the line declares (DISK_GB); a
# physical Mac's partitioning belongs to its owner and is left alone.
if [[ "$(sysctl -n kern.hv_vmm_present 2>/dev/null)" == 1 ]]; then
  apfs_grow_root || { glog "FATAL: the system APFS container does not fill the disk"; exit 1; }
else
  glog "APFS: physical Mac, partitioning left as it is"
fi

if [[ -f /tmp/payload/host_key.pub ]]; then
  mkdir -p ~/.ssh
  chmod 700 ~/.ssh
  touch ~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
  ensure_line ~/.ssh/authorized_keys "$(cat /tmp/payload/host_key.pub)"
  glog "host SSH key authorized"
fi

glog "reclaiming Homebrew for $(id -un) (seed installed it under the removed seed account)"
if [[ -d /opt/homebrew ]]; then
  sudo chown -R "$(id -un):admin" /opt/homebrew 2>/dev/null || true
fi

glog "always-on unlocked session (layered enforcement per doctrine)"
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
sudo pmset -a powernap 0 2>/dev/null || true
# Screen saver OFF ("Start after: Never") for both the user session (ByHost)
# and the login window — idleTime 0 means never activate.
defaults -currentHost write com.apple.screensaver idleTime -int 0
sudo defaults write /Library/Preferences/com.apple.screensaver loginWindowIdleTime -int 0
# Lock Screen > "Require password after screen saver / display off" = Never.
defaults -currentHost write com.apple.screensaver askForPassword -int 0
defaults -currentHost write com.apple.screensaver askForPasswordDelay -int 0
sysadminctl -screenLock off -password "$GUEST_PASS" 2>/dev/null \
  || glog "screenLock off deferred — verify during GUI pass"

AUTOLOGIN=$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null || echo none)
glog "auto-login user: $AUTOLOGIN (expected: $USER)"

glog "enforcing manual-only macOS updates (re-asserted in phase 70, which runs last)"
su_manual_only

glog "suppressing first-login onboarding (Setup Assistant / MiniBuddy panes)"
# A freshly created account has every Setup Assistant pane unseen, so an
# auto-login session can land on Siri/iCloud/Privacy onboarding instead of the
# desktop — an interactive gate nothing in a headless build can answer, and one
# that every clone would inherit. The system-level markers below ship with the
# Cirrus seed; these per-user keys are the gate that is actually still open.
# PreviousSystemVersion/PreviousBuildVersion default to "0" and MiniBuddy
# re-shows the panes whenever they differ from the running OS, so the real
# version has to be recorded next to the DidSee* flags.
typeset -a SA_SEEN
SA_SEEN=(
  DidSeeAccessibility DidSeeActivationLock DidSeeAppearanceSetup
  DidSeeApplePaySetup DidSeeAppStore DidSeeCloudSetup
  DidSeeiCloudLoginForStorageServices DidSeeLockdownMode DidSeePrivacy
  DidSeeScreenTime DidSeeSiriSetup DidSeeSyncSetup DidSeeSyncSetup2
  DidSeeTermsOfAddress DidSeeTouchIDSetup
  SkipExpressSettingsUpdating SkipFirstLoginOptimization
)
for k in "${SA_SEEN[@]}"; do
  defaults write com.apple.SetupAssistant "$k" -bool true
done
# Three components, as Setup Assistant compares them (see _setup-account.zsh).
SA_VERSION=$(sw_vers -productVersion | awk -F. '{printf "%d.%d.%d", $1, $2, $3}')
defaults write com.apple.SetupAssistant PreviousSystemVersion -string "$SA_VERSION"
defaults write com.apple.SetupAssistant PreviousBuildVersion  -string "$(sw_vers -buildVersion)"
# LastSeen* are the long-standing names for the same version gate on earlier
# releases. Unused on this one, harmless, and correct if a seed reverts to them.
defaults write com.apple.SetupAssistant LastSeenCloudProductVersion -string "$SA_VERSION"
defaults write com.apple.SetupAssistant LastSeenBuddyBuildVersion   -string "$(sw_vers -buildVersion)"
# A MiniBuddy that was up when the VM rebooted leaves MiniBuddyLaunch set, and
# loginwindow then relaunches it at every login whatever the version keys say.
defaults delete com.apple.loginwindow MiniBuddyLaunch 2>/dev/null || true
defaults delete com.apple.loginwindow MiniBuddyLaunchCount 2>/dev/null || true
for m in /var/db/.AppleSetupDone /var/db/.AppleDiagnosticsSetupDone; do
  if [[ ! -e "$m" ]]; then
    sudo touch "$m"
    glog "created missing system setup marker: $m"
  fi
done
glog "onboarding suppressed for $USER (macOS $(sw_vers -productVersion) $(sw_vers -buildVersion))"

glog "oh-my-zsh"
if [[ ! -d ~/.oh-my-zsh ]]; then
  RUNZSH=no CHSH=no sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
fi

mkdir -p ~/.local/bin ~/.config/zsh
ensure_line ~/.zshrc 'export PATH="$HOME/.local/bin:$PATH"'
ensure_line ~/.zshrc 'eval "$(/opt/homebrew/bin/brew shellenv)"'
ensure_line ~/.zshrc '[ -f "$HOME/.config/zsh/secrets.zsh" ] && source "$HOME/.config/zsh/secrets.zsh"'

glog "command line tools (full Xcode arrives in phase 20)"
if ! xcode-select -p >/dev/null 2>&1; then
  touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  LABEL=$(softwareupdate -l 2>/dev/null | grep -o 'Label: Command Line Tools[^,]*' | tail -1 | sed 's/^Label: //' || true)
  if [[ -n "$LABEL" ]]; then
    sudo softwareupdate -i "$LABEL"
  else
    glog "no CLT label found — cirrus image likely ships CLT already"
  fi
  rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
fi

glog "phase 00 done"
