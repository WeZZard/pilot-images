"""Phase 65 (Apple Events grant for SSH-run osascript) and its acceptance probe.

Text-level contracts only: the live TCC row format is verified in-guest by the
phase itself and by acceptance, both over SSH so the client is the real one.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT / 'images/macos26/guest/65-automation.zsh'
ACCEPTANCE = ROOT / 'images/macos26/checks/acceptance.zsh'
LIB = ROOT / 'images/macos26/guest/lib.zsh'


class AutomationGrantPhaseTests(unittest.TestCase):
    def test_phase_is_discoverable_and_shares_the_guest_library(self):
        self.assertTrue(PHASE.is_file())
        self.assertTrue(PHASE.stat().st_mode & 0o100)
        source = PHASE.read_text()
        self.assertIn('source "${0:A:h}/lib.zsh"', source)
        self.assertIn('csreq_hex', LIB.read_text())
        # Phase 60 reuses the shared helper instead of carrying its own copy.
        driver = (ROOT / 'images/macos26/guest/60-cua-driver.zsh').read_text()
        self.assertIn('csreq_hex /Applications/CuaDriver.app', driver)
        self.assertNotIn('SecCodeCopyDesignatedRequirement', driver)

    def test_grant_is_sip_off_only_and_scoped_to_the_ssh_client(self):
        source = PHASE.read_text()
        self.assertIn("csrutil status", source)
        self.assertIn("CLIENT=/usr/libexec/sshd-keygen-wrapper", source)
        # Exactly one client literal is granted; no bundle-id or wildcard client.
        self.assertEqual(source.count("'$CLIENT',1,"), 1)
        self.assertNotIn('com.openssh', source)
        self.assertIn('kTCCServiceAppleEvents', source)
        self.assertIn('com.apple.TCC/TCC.db', source)
        self.assertIn('$HOME/Library/Application Support/com.apple.TCC/TCC.db', source)

    def test_rows_are_idempotent_pinned_and_schema_gated(self):
        source = PHASE.read_text()
        self.assertIn('INSERT OR REPLACE INTO access', source)
        self.assertNotIn('INSERT INTO access', source)
        self.assertIn('PRAGMA table_info(access)', source)
        row = re.search(r"VALUES \('kTCCServiceAppleEvents','\$CLIENT',1,2,2,1,X'\$CLIENT_REQ',0,'\$bid',X'\$req',0,", source)
        self.assertIsNotNone(row, 'row shape: auth_value 2, path client, bundle-id target, both code identities pinned')
        self.assertIn('com.apple.tccd', source)
        for target in ('/Applications', '/System/Applications', 'System Events.app', 'Finder.app', 'Shortcuts Events.app'):
            self.assertIn(target, source)

    def test_phase_verifies_over_the_same_ssh_path_with_a_hard_timeout(self):
        source = PHASE.read_text()
        self.assertIn("perl -e 'alarm 20; exec @ARGV' osascript", source)
        self.assertIn('"System Events"', source)
        self.assertIn('"Finder"', source)


class AutomationGrantAcceptanceTests(unittest.TestCase):
    def test_acceptance_probes_system_events_and_finder_only(self):
        source = ACCEPTANCE.read_text()
        block = source[source.index('Apple Events (Automation)'):source.index('pi list')]
        self.assertIn("perl -e 'alarm 20; exec @ARGV' osascript", block)
        self.assertIn('System Events:get name of every process', block)
        self.assertIn('Finder:get name of startup disk', block)
        self.assertIn("kTCCServiceAppleEvents", block)
        self.assertIn("client='/usr/libexec/sshd-keygen-wrapper'", block)
        # Acceptance must not launch stateful apps into the base.
        for app in ('Reminders', 'Notes', 'Contacts', 'Calendar', 'Music', 'Safari'):
            self.assertNotIn('"' + app + '"', block)

    def test_single_phase_65_runs_reboot_before_checks(self):
        build = (ROOT / 'host/build-base.zsh').read_text()
        self.assertIn('"$ONLY_PHASE" == 65', build)


if __name__ == '__main__':
    unittest.main()
