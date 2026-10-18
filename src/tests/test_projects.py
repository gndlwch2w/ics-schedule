import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from icalendar import Calendar
from ics_schedule.models import ValidationError
from ics_schedule.plugins import load_sources
from ics_schedule.publishing import GitHubPublisher, PublishError, destination, digest, raw_url, validate_settings
from ics_schedule.service import CalendarService
from ics_schedule.workspace import WorkspaceService
from test_calendar import Feed, example


class FakePublisher:
    def publish(self, settings, content, previous=None):
        return {'settings': dict(settings), 'digest': digest(content), 'url': raw_url(settings), 'commit': 'a' * 40}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sources = load_sources()
        self.sources['test'] = Feed()
        self.workspace = WorkspaceService(self.root, self.sources, FakePublisher())
        self.other = self.workspace.create({'name': '另一订阅'})['id']

    def tearDown(self):
        self.temp.cleanup()

    def settings(self, project_id, path=None):
        return {'name': project_id, 'publication': {'repository': 'owner/calendars', 'branch': 'main', 'path': path or f'subscription/{project_id}.ics', 'transport': 'ssh'}}

    def test_event_config_and_output_isolation(self):
        a, b = self.workspace.calendar('default'), self.workspace.calendar(self.other)
        a.save(example())
        before = (self.root / 'subscription/default.ics').read_bytes()
        b.save(dict(example(), title='B'))
        b.refresh('test', {'title': 'B 插件'})
        a.refresh('test', {'title': 'A 插件'})
        self.assertEqual(a.state['configs']['test']['title'], 'A 插件')
        self.assertEqual(b.state['configs']['test']['title'], 'B 插件')
        a_event = next(e for e in a.state['events'] if e['source'] == 'test')
        b_event = next(e for e in b.state['events'] if e['source'] == 'test')
        self.assertNotEqual(a_event['uid'], b_event['uid'])
        with self.assertRaises(KeyError):
            b.delete(a.state['events'][0]['id'])
        stable_a = (self.root / 'subscription/default.ics').read_bytes()
        b.save(dict(example(), title='B 再次修改'))
        self.assertEqual(stable_a, (self.root / 'subscription/default.ics').read_bytes())
        self.assertNotEqual(before, stable_a)
        restarted = WorkspaceService(self.root, self.sources, FakePublisher())
        self.assertEqual(len(restarted.snapshot(self.other)['events']), 3)
        self.assertEqual(len(restarted.snapshot('default')['events']), 2)

    def test_publish_states_destinations_and_failure(self):
        self.workspace.configure('default', self.settings('default'))
        self.workspace.configure(self.other, self.settings(self.other))
        result = self.workspace.publish_project('default')
        self.assertTrue(result['url'].startswith('https://raw.githubusercontent.com/'))
        projects = self.workspace.snapshot()['projects']
        self.assertEqual([p['status'] for p in projects], ['published', 'unpublished'])
        self.workspace.calendar('default').save(example())
        self.assertEqual(self.workspace.snapshot()['projects'][0]['status'], 'changed')
        with patch.object(self.workspace.publisher, 'publish', side_effect=PublishError('网络断开')):
            with self.assertRaises(PublishError):
                self.workspace.publish_project('default')
        failed = self.workspace.snapshot()['projects'][0]
        self.assertEqual(failed['subscription_url'], result['url'])
        self.assertEqual(failed['status'], 'changed')
        self.assertEqual(failed['last_error'], '网络断开')
        self.workspace.publish_project('default')
        self.assertEqual(self.workspace.snapshot()['projects'][0]['status'], 'published')
        with self.assertRaises(ValidationError):
            self.workspace.configure(self.other, self.settings(self.other, 'subscription/default.ics'))
        self.workspace.configure('default', self.settings('default', 'subscription/renamed.ics'))
        self.assertIsNone(self.workspace.snapshot()['projects'][0]['subscription_url'])
        with self.assertRaises(ValidationError):
            self.workspace.configure(self.other, self.settings(self.other, 'subscription/default.ics'))

    def test_migrate_legacy_without_changing_uid(self):
        with tempfile.TemporaryDirectory() as root:
            legacy = CalendarService(root, self.sources)
            record = legacy.save(example())
            original = (Path(root) / 'data/calendar.json').read_bytes()
            workspace = WorkspaceService(root, self.sources)
            self.assertEqual(workspace.snapshot()['events'][0]['uid'], record['uid'])
            self.assertEqual((Path(root) / 'data/calendar.json').read_bytes(), original)
            self.assertEqual(len(workspace.projects), 1)

    def test_settings_reject_unsafe_paths_and_branches(self):
        config = self.settings('default')['publication']
        for change in ({'path': '../outside.ics'}, {'path': '/tmp/x.ics'}, {'path': '.git/config.ics'}, {'branch': '-bad'}, {'branch': 'a..b'}, {'repository': 'https://example.com/a/b'}, {'path': 'a.txt'}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_settings(dict(config, **change))
        valid = validate_settings(dict(config, branch='calendar/work'))
        self.assertIn('/refs/heads/calendar/work/', raw_url(valid))


class LocalPublisher(GitHubPublisher):
    def __init__(self, remote):
        self.remote = remote

    def check_public(self, settings):
        pass

    def remote_url(self, settings):
        return str(self.remote)


class GitPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.git('init', '--bare', str(self.remote))
        self.seed = self.root / 'seed'
        self.git('init', '-b', 'main', str(self.seed))
        self.git('config', 'user.name', 'Test', cwd=self.seed)
        self.git('config', 'user.email', 'test@example.com', cwd=self.seed)
        (self.seed / 'README.md').write_text('keep this file')
        self.git('add', 'README.md', cwd=self.seed)
        self.git('commit', '-m', 'Initialize', cwd=self.seed)
        self.git('remote', 'add', 'origin', str(self.remote), cwd=self.seed)
        self.git('push', 'origin', 'main', cwd=self.seed)
        self.publisher = LocalPublisher(self.remote)
        self.settings = {'repository': 'owner/calendars', 'branch': 'main', 'path': 'subscription/a.ics', 'transport': 'ssh'}

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()

    def test_real_git_first_update_noop_and_other_file_preserved(self):
        first = self.publisher.publish(self.settings, b'A version 1')
        b = dict(self.settings, path='subscription/b.ics')
        self.publisher.publish(b, b'B version 1')
        second = self.publisher.publish(self.settings, b'A version 2', first)
        self.assertNotEqual(first['commit'], second['commit'])
        noop = self.publisher.publish(self.settings, b'A version 2', second)
        self.assertEqual(second['commit'], noop['commit'])
        self.assertEqual(self.git('--git-dir', str(self.remote), 'show', 'main:subscription/b.ics'), 'B version 1')
        self.assertEqual(self.git('--git-dir', str(self.remote), 'show', 'main:README.md'), 'keep this file')
        self.assertEqual(self.git('--git-dir', str(self.remote), 'diff-tree', '--no-commit-id', '--name-only', '-r', second['commit']), 'subscription/a.ics')
        with self.assertRaises(PublishError):
            self.publisher.publish(self.settings, b'overwrite without history')
        with self.assertRaises(PublishError):
            self.publisher.publish(self.settings, b'using stale base', first)

    def test_crlf_preserved_with_repository_attributes(self):
        (self.seed / '.gitattributes').write_text('*.ics text eol=lf\n')
        self.git('add', '.gitattributes', cwd=self.seed)
        self.git('commit', '-m', 'Normalize text fixture', cwd=self.seed)
        self.git('push', 'origin', 'main', cwd=self.seed)
        content = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'
        first = self.publisher.publish(self.settings, content)
        stored = subprocess.check_output(['git', '--git-dir', str(self.remote), 'show', 'main:subscription/a.ics'])
        self.assertEqual(stored, content)
        updated = content.replace(b'END:VCALENDAR', b'X-WR-CALNAME:Updated\r\nEND:VCALENDAR')
        second = self.publisher.publish(self.settings, updated, first)
        self.assertEqual(second['digest'], digest(updated))

    def test_reject_symlink_path(self):
        (self.seed / 'linked').symlink_to(self.root, target_is_directory=True)
        self.git('add', 'linked', cwd=self.seed)
        self.git('commit', '-m', 'Symlink fixture', cwd=self.seed)
        self.git('push', 'origin', 'main', cwd=self.seed)
        with self.assertRaises(PublishError):
            self.publisher.publish(dict(self.settings, path='linked/escape.ics'), b'no')
        self.assertFalse((self.root / 'escape.ics').exists())


if __name__ == '__main__':
    unittest.main()
