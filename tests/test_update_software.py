"""host/update-software.py: feeds, URL templates and pin rewriting.

Fixture-only: nothing here reaches the network or downloads a release.
"""
import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
LOCK = json.loads((REPO / 'images/macos26/guest/coding-agents.lock.json').read_text())
FEEDS = {'json', 'text', 'redirect', 'github', 'none'}


def load():
    spec = importlib.util.spec_from_file_location('update_software', REPO / 'host/update-software.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.u = load()

    def test_numeric_parts_compare_as_numbers(self):
        self.assertTrue(self.u.newer('3.14.10', '3.14.9'))
        self.assertTrue(self.u.newer('2.3.93439', '2.3.61406'))
        self.assertFalse(self.u.newer('1.0.70', '1.0.70'))

    def test_a_leading_v_is_dropped(self):
        self.assertEqual(self.u.bare('v1.28.10'), '1.28.10')
        self.assertEqual(self.u.bare('vscode'), 'vscode')


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.u = load()

    def test_json_paths_index_filter_and_fill_earlier_values(self):
        data = {'packages': [{'fileType': 'deb', 'sha256': 'a'}, {'fileType': 'dmg', 'sha256': 'b'}],
                'versions': {'0.3.25': {'url': 'u'}}, 'list': [{'v': 1}]}
        self.assertEqual(self.u.json_path(data, 'packages[fileType=dmg].sha256', {}), 'b')
        self.assertEqual(self.u.json_path(data, 'versions.{version}.url', {'version': '0.3.25'}), 'u')
        self.assertEqual(self.u.json_path(data, 'list.0.v', {}), 1)

    def test_the_match_with_the_newest_version_wins(self):
        page = 'releases/3.9.2/macos-arm64/ZCode- releases/3.16.3/macos-arm64/ZCode- releases/3.10.1/macos-arm64/ZCode-'
        self.assertEqual(self.u.regex_values(r'releases/(?P<version>[\d.]+)/macos-arm64/ZCode-', page)['version'], '3.16.3')

    def test_a_url_template_parses_the_old_url(self):
        template = 'https://example.test/hub/{version}-{build}/Antigravity.dmg'
        self.assertEqual(self.u.parse(template, 'https://example.test/hub/2.25.0-6535/Antigravity.dmg'),
                         {'version': '2.25.0', 'build': '6535'})
        self.assertEqual(self.u.parse(template, 'https://example.test/other.dmg'), {})

    def test_values_replace_old_tokens_raw_and_percent_encoded(self):
        old, new = {'version': '1.2.18+19'}, {'version': '1.2.33+21', 'url': 'x'}
        pairs = self.u.token_pairs(old, new)
        self.assertEqual(self.u.replace_tokens({'links': {'cortex': 'coco-1.2.18+19/cortex'}}, pairs),
                         {'links': {'cortex': 'coco-1.2.33+21/cortex'}})
        self.assertEqual(self.u.replace_tokens('a/1.2.18%2B19/b', pairs), 'a/1.2.33%2B21/b')

    def test_digest_prefixes_and_version_prefixes_are_normalized(self):
        self.assertEqual(self.u.normalized({'version': 'v1.0', 'sha256': 'sha256:ab'}), {'version': '1.0', 'sha256': 'ab'})


class PythonRequirementTests(unittest.TestCase):
    def setUp(self):
        self.u = load()

    def test_a_python_that_still_fits_is_kept(self):
        self.assertEqual(self.u.python_for('3.13', '>=3.11'), '3.13')
        self.assertEqual(self.u.python_for('3.12', ''), '3.12')

    def test_a_release_that_needs_a_newer_python_moves_it(self):
        self.assertEqual(self.u.python_for('3.13', '>=3.14,<3.15'), '3.14')
        self.assertEqual(self.u.python_for('3.11', '>=3.12.1'), '3.12')
        self.assertEqual(self.u.python_for('3.13', '==3.12.*'), '3.12')


class LockFeedTests(unittest.TestCase):
    def setUp(self):
        self.u = load()

    def test_every_vendor_download_has_a_feed(self):
        for agent in LOCK['agents']:
            if agent['method'] in ('archive', 'app', 'script'):
                with self.subTest(agent=agent['id']):
                    release = self.u.release_of(agent)
                    self.assertIn(release['feed'], FEEDS)
                    if release['feed'] == 'none':
                        self.assertTrue(release['reason'])
                    elif release['feed'] != 'github':
                        self.assertTrue(release['url'].startswith('https://'))

    def test_every_download_template_parses_its_own_pin(self):
        for agent in LOCK['agents']:
            template = agent.get('release', {}).get('download')
            if template and agent['release']['feed'] != 'github':
                with self.subTest(agent=agent['id']):
                    parsed = self.u.parse(template, agent['url'])
                    if parsed:
                        self.assertEqual(self.u.fill(template, parsed), agent['url'])


class LineConfTests(unittest.TestCase):
    def setUp(self):
        self.u = load()

    def test_values_are_read_and_rewritten_in_place(self):
        text = 'XCODE_XIP="${XCODE_XIP:-$HOME/x.xip}"\nPYTHON_VERSION="3.14.6"\nNVM_VERSION="v0.40.3"\n'
        self.assertEqual(self.u.conf_value(text, 'PYTHON_VERSION'), '3.14.6')
        self.assertEqual(self.u.conf_value(text, 'XCODE_XIP'), '$HOME/x.xip')
        moved = self.u.set_conf(self.u.set_conf(text, 'PYTHON_VERSION', '3.14.10'), 'NVM_VERSION', 'v0.40.8')
        self.assertEqual(moved, 'XCODE_XIP="${XCODE_XIP:-$HOME/x.xip}"\nPYTHON_VERSION="3.14.10"\nNVM_VERSION="v0.40.8"\n')

    def test_every_macos_line_has_the_pins_it_reports(self):
        for line in self.u.macos_lines():
            with self.subTest(line=line):
                conf = (REPO / 'images' / line / 'line.conf').read_text()
                for key in ('PYTHON_VERSION', 'NVM_VERSION', 'NODE_MAJOR', 'XCODE_VERSION'):
                    self.assertIsNotNone(self.u.conf_value(conf, key), key)


if __name__ == '__main__':
    unittest.main()
