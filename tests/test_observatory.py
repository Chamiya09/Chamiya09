"""Offline behavioral checks. Synthetic fixtures never become published statistics."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import generate_observatory as obs


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


class FakeGitHub(obs.GitHub):
    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path == '/users/example':
            return {'login': 'example', 'type': 'User', 'public_repos': 2}, {}
        repo = {'id': 1, 'full_name': 'example/one', 'owner': {'login': 'example'},
                'fork': False, 'private': False, 'stargazers_count': 7}
        if path == '/users/example/repos':
            return [repo], {'Link': '<https://api.github.com/page2>; rel="next"'}
        if path == 'https://api.github.com/page2':
            return [dict(repo, id=2, full_name='example/two', fork=True, stargazers_count=3)], {}
        if path.startswith('/search/'):
            return {'total_count': 1201, 'incomplete_results': False}, {}
        if path == '/repos/example/one/languages':
            return {'Python': 300, 'HTML': 100}, {}
        if path == '/repos/example/two/languages':
            return {'Java': 100}, {}
        raise AssertionError(path)


class ObservatoryTests(unittest.TestCase):
    def test_repository_readme_is_ready_for_markdown_updates(self):
        readme = (obs.ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertEqual(readme.count(obs.START), 1)
        self.assertEqual(readme.count(obs.END), 1)
        self.assertLess(readme.index(obs.START), readme.index(obs.END))
        for name in ('github-observatory.svg', 'github-observatory-mobile.svg'):
            self.assertIn(name, readme)
            self.assertTrue((obs.ROOT / 'assets' / name).is_file())
            root = ET.parse(obs.ROOT / 'assets' / name).getroot()
            self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')

    def test_pagination_real_totals_and_fork_exclusion(self):
        client = FakeGitHub()
        data = obs.collect(client, 'example', NOW)
        self.assertEqual(data['metrics'], {'commits': 1201, 'pull_requests': 1201,
                                         'stars': 10, 'public_repositories': 2})
        self.assertEqual(data['language_bytes'], {'HTML': 100, 'Python': 300})
        self.assertIn(('https://api.github.com/page2', None), client.calls)
        self.assertNotIn(('/repos/example/two/languages', None), client.calls)
        self.assertIn('author-date:2026-01-01..2026-06-04', data['queries']['commits'])
        self.assertEqual(data['queries']['pull_requests'], 'is:pr author:example is:public')

    def test_include_forks(self):
        data = obs.collect(FakeGitHub(), 'example', NOW, include_forks=True)
        self.assertEqual(data['language_bytes']['Java'], 100)

    def test_empty_and_grouped_languages(self):
        self.assertEqual(obs.language_segments({}), [])
        segments = obs.language_segments({str(i): i for i in range(1, 9)})
        self.assertEqual(len(segments), 6)
        self.assertEqual(segments[-1][0], 'Other languages')
        self.assertAlmostEqual(sum(s[1] for s in segments), 100)
        self.assertAlmostEqual(obs.language_segments({'Python': 300, 'HTML': 100})[0][1], 75)

    @patch.object(obs.time, 'sleep')
    def test_incomplete_search_is_never_published_as_zero(self, sleep):
        with patch.object(obs.GitHub, 'get', return_value=({'total_count': 0, 'incomplete_results': True}, {})):
            with self.assertRaises(obs.DataError):
                obs.GitHub().search_count('commits', 'author:example')

    @patch.object(obs.time, 'sleep')
    def test_transient_http_error_retries(self, sleep):
        error = HTTPError(obs.API, 503, 'Unavailable', {}, None)
        with patch.object(obs, 'urlopen', side_effect=error) as request:
            with self.assertRaises(obs.DataError):
                obs.GitHub().get('/users/example')
        self.assertEqual(request.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    @patch.object(obs.time, 'sleep')
    def test_long_rate_limit_fails_without_publishing(self, sleep):
        error = HTTPError(obs.API, 429, 'Rate limited', {'Retry-After': '3600'}, None)
        with patch.object(obs, 'urlopen', side_effect=error):
            with self.assertRaises(obs.DataError):
                obs.GitHub().get('/users/example')
        sleep.assert_not_called()

    def test_reject_foreign_pagination_url(self):
        with self.assertRaises(obs.DataError):
            obs.GitHub('test-token').get('https://example.org/page2')

    def test_missing_count_is_not_zero(self):
        for value in (None, -1, '0', True):
            with self.assertRaises(obs.DataError):
                obs.count(value, 'metric')

    def make_readme(self, folder):
        readme = Path(folder) / 'README.md'
        readme.write_bytes(('Banner and introduction\r\n\r\n' + obs.START + '\r\nold block\r\n' + obs.END + '\r\n\r\nKeep my tech stack.\r\n').encode())
        return readme

    def test_image_only_readme_and_no_timestamp_only_changes(self):
        data = obs.collect(FakeGitHub(), 'example', NOW)
        data['language_bytes'] = {'A&B <language>|*test*': 20}
        with tempfile.TemporaryDirectory() as folder:
            readme = self.make_readme(folder)
            self.assertTrue(obs.publish(data, readme, NOW))
            before = readme.read_bytes()
            self.assertFalse(obs.publish(data, readme, NOW + timedelta(hours=6)))
            self.assertEqual(before, readme.read_bytes())
            content = before.decode()
            self.assertIn('<!-- observatory-data:', content)
            self.assertIn('github-observatory.svg', content)
            self.assertNotIn('<details>', content)
            self.assertNotIn('View statistics as text', content)
            self.assertNotIn('<svg', content)
            self.assertTrue(content.startswith('Banner and introduction\r\n\r\n' + obs.START))
            self.assertTrue(content.endswith(obs.END + '\r\n\r\nKeep my tech stack.\r\n'))

    def test_failed_collection_preserves_last_valid_readme(self):
        with tempfile.TemporaryDirectory() as folder:
            readme = self.make_readme(folder)
            obs.publish(obs.collect(FakeGitHub(), 'example', NOW), readme, NOW)
            before = readme.read_bytes()
            with patch.object(obs, 'collect', side_effect=obs.DataError('API failed')):
                self.assertEqual(obs.main(['--username', 'example', '--readme', str(readme)]), 1)
            self.assertEqual(before, readme.read_bytes())

    def test_ambiguous_markers_leave_readme_untouched(self):
        data = obs.collect(FakeGitHub(), 'example', NOW)
        for content in ('No markers', obs.END + obs.START, obs.START + obs.START + obs.END):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as folder:
                readme = Path(folder) / 'README.md'
                readme.write_text(content)
                with self.assertRaises(obs.DataError):
                    obs.publish(data, readme, NOW)
                self.assertEqual(readme.read_text(), content)

    def test_changed_metric_updates_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            readme = self.make_readme(folder)
            data = obs.collect(FakeGitHub(), 'example', NOW)
            obs.publish(data, readme, NOW)
            data['metrics']['stars'] = 42
            self.assertTrue(obs.publish(data, readme, NOW + timedelta(hours=6)))
            content = readme.read_text(encoding='utf-8')
            self.assertIn('"stars": 42', content)
            self.assertIn('2026\\u002d06\\u002d04T18:00:00Z', content)


if __name__ == '__main__':
    unittest.main()
