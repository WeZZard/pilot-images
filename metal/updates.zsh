#!/bin/zsh
# Update strategy of a PHYSICAL Mac: nightly refresh via crontab, mirroring the
# host's ~/.crontab.d convention. Run by metal/bootstrap.zsh in place of the VM
# image's phase 70, which forbids self-updates (docs/decisions.md, 2026-10-01:
# physical Mac minis and VM images get separate update strategies). Deliberately
# EXCLUDED from automatic updates: macOS itself and Xcode.
source "${0:A:h:h}/images/macos26/guest/lib.zsh"

rm -rf "$HOME/.crontab.d"
write_refresh_scripts "$HOME/.crontab.d"

crontab - <<EOF
MAILTO=""
0 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.macos/brew_upgrade
0 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/rustup_update
5 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/npm_global_update
10 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/pi_update
15 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/claude_update
20 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/cua_driver_update
EOF

glog "installed crontab:"
crontab -l
# Runs last, after Homebrew and Xcode have had their chance to re-enable
# checking and re-offer a point update.
glog "re-asserting manual-only macOS updates (final step)"
su_manual_only
glog "metal updates done"
