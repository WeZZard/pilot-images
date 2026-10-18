#!/bin/zsh
# Pre-provision account setup (runs as OLD_USER via sudo, on a near-empty seed).
# Creates NEW_USER as an admin account and the auto-login default, then reboots
# so the caller reconnects as NEW_USER. The seed OLD_USER is removed afterward by
# build-base (from the NEW_USER session). Not a numbered phase — underscore
# prefix keeps it out of phase discovery.
set -e -u -o pipefail
OLD="${OLD_USER:?}"
NEW="${NEW_USER:?}"
NEWPW="${NEW_PASS:?}"

# ---- automatic macOS updates OFF, before the OS can act on one --------------
# The 2026-09-12 build showed the cost of leaving these on: softwareupdated
# offered macOS 26.6.2 forty-three seconds after first boot, attempted it during
# provisioning, failed, and left Setup Assistant showing its "Software Update
# Complete" pane on EVERY later boot. That pane is a modal covering the desktop,
# it is inherited by every clone, and no headless check sees it (auto-login,
# console session, Dock and Finder all report healthy underneath it). The repo's
# update policy already excludes macOS point updates from automation; this is
# what actually enforces it, and it has to run before the first update scan.
SU_DOMAIN=/Library/Preferences/com.apple.SoftwareUpdate
# `softwareupdate --schedule off` runs FIRST and its result is not trusted: on
# macOS 26 it leaves the schedule reporting "on" and it drops the
# AutomaticCheckEnabled key that the defaults write below sets, so running it
# afterwards silently undoes the most important switch.
sudo softwareupdate --schedule off >/dev/null 2>&1 || true
for _k in AutomaticCheckEnabled AutomaticDownload AutomaticallyInstallMacOSUpdates \
          CriticalUpdateInstall ConfigDataInstall; do
  sudo defaults write "$SU_DOMAIN" "$_k" -bool false
done
# Discard anything a scan managed to record before the switches landed, so no
# post-update pane is left queued.
for _k in RecommendedUpdates DDMPersistedErrorKey FirstOfferDateDictionary; do
  sudo defaults delete "$SU_DOMAIN" "$_k" >/dev/null 2>&1 || true
done
sudo killall softwareupdated >/dev/null 2>&1 || true

echo "automatic macOS updates disabled"

if id "$NEW" >/dev/null 2>&1; then
  echo "account $NEW already exists — skipping creation"
else
  echo "creating admin account $NEW"
  sudo sysadminctl -addUser "$NEW" -fullName "$NEW" -password "$NEWPW" -admin
fi

# Remote Login (sshd) is gated by com.apple.access_ssh on the Cirrus seed — the
# new account must be added or the caller can't reconnect over SSH after reboot.
echo "granting $NEW SSH access (com.apple.access_ssh)"
sudo dseditgroup -o edit -a "$NEW" -t user com.apple.access_ssh 2>/dev/null || true

echo "passwordless sudo for $NEW (build convenience; matches the seed's $OLD)"
echo "$NEW ALL=(ALL) NOPASSWD: ALL" | sudo tee "/etc/sudoers.d/${NEW}-nopasswd" >/dev/null
sudo chmod 440 "/etc/sudoers.d/${NEW}-nopasswd"

# ---- onboarding panes marked seen BEFORE the account's FIRST login ---------
# This has to happen here, not in a numbered phase. Setup Assistant launches in
# MiniBuddy mode at the new account's first auto-login, which is the reboot at
# the end of THIS script — before any phase runs. Once it is up it stays up, and
# the 2026-09-12 build proved that writing these keys afterwards does not
# dismiss it: the pane survived three reboots with every key verified correct.
# The seed carries post-update state from its own build date, so a brand-new
# account is offered the "Software Update Complete" pane regardless of whether
# this image ever attempted an update. Writing the keys into the new user's
# preferences while root, before that first login, is the only ordering that
# can stop it launching at all.
SA_PLIST="/Users/$NEW/Library/Preferences/com.apple.SetupAssistant.plist"
sudo mkdir -p "/Users/$NEW/Library/Preferences"
for _k in DidSeeAccessibility DidSeeActivationLock DidSeeAppearanceSetup \
          DidSeeApplePaySetup DidSeeAppStore DidSeeCloudSetup \
          DidSeeiCloudLoginForStorageServices DidSeeLockdownMode DidSeePrivacy \
          DidSeeScreenTime DidSeeSiriSetup DidSeeSyncSetup DidSeeSyncSetup2 \
          DidSeeTermsOfAddress DidSeeTouchIDSetup \
          SkipExpressSettingsUpdating SkipFirstLoginOptimization; do
  sudo defaults write "$SA_PLIST" "$_k" -bool true
done
sudo defaults write "$SA_PLIST" MiniBuddyShouldLaunchToResumeSetup -bool false
sudo defaults write "$SA_PLIST" PreviousSystemVersion -string "$(sw_vers -productVersion)"
sudo defaults write "$SA_PLIST" PreviousBuildVersion  -string "$(sw_vers -buildVersion)"
sudo defaults write "$SA_PLIST" LastSeenCloudProductVersion -string "$(sw_vers -productVersion)"
sudo defaults write "$SA_PLIST" LastSeenBuddyBuildVersion   -string "$(sw_vers -buildVersion)"
# Braces are required: in zsh a bare "$NEW:staff" parses ":s" as a history
# modifier and dies with "bad substitution".
sudo chown -R "${NEW}:staff" "/Users/${NEW}/Library/Preferences"
echo "onboarding panes marked seen for $NEW before first login"

echo "auto-login -> $NEW"
sudo defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser "$NEW"
# /etc/kcpassword holds the auto-login password XOR'd with Apple's static cipher.
# perl is always present on macOS (system python3 is not), so use perl.
sudo perl -e '
my @k = (0x7D,0x89,0x52,0x23,0xD2,0xBC,0xDD,0xEA,0xA3,0xB9,0x1F);
my @p = unpack("C*", $ARGV[0]);
my $pad = @k - (scalar(@p) % @k);
push @p, (0) x $pad;
my @o = map { $p[$_] ^ $k[$_ % @k] } 0 .. $#p;
open(my $fh, ">", "/etc/kcpassword") or die "kcpassword: $!";
binmode $fh; print $fh pack("C*", @o); close $fh;
chmod 0600, "/etc/kcpassword";
' "$NEWPW"

# No reboot here: build-base creates (retry-safe, idempotent) then reboots
# explicitly, so a transient SSH auth flake on this command can be retried
# without racing a self-triggered reboot.
echo "account $NEW created (caller reboots)"
