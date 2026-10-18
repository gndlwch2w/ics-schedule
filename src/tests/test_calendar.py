import json
import tempfile
import threading
import unittest
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from icalendar import Calendar
from ics_schedule.models import ValidationError, validate_event
from ics_schedule.plugins import CalendarSource, load_sources
from ics_schedule.server import handler_for
from ics_schedule.service import CalendarService
from ics_schedule.workspace import WorkspaceService


def example(**kwargs):
    return dict(title='项目讨论，下一步;计划\\记录\n中文', start='2026-10-19T09:00', end='2026-10-19T10:00', timezone='Asia/Shanghai', **kwargs)


class Feed(CalendarSource):
    id = 'test'
    title = '测试来源'
    fields = [{'name': 'title', 'label': '标题', 'type': 'text'}]

    def collect(self, config, records):
        if config.get('fail'):
            raise RuntimeError('source offline')
        event = example()
        event.update(id='stable-1', title=config.get('title', '外部事件'))
        return [event]


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sources = load_sources()
        self.sources['test'] = Feed()
        self.service = CalendarService(self.root, self.sources)

    def tearDown(self):
        self.temp.cleanup()

    def calendar(self, name='all'):
        data = (self.root / 'subscription' / (name + '.ics')).read_bytes()
        self.assertIn(b'\r\n', data)
        self.assertTrue(all(len(line) <= 75 for line in data.split(b'\r\n')))
        return Calendar.from_ical(data)

    def test_roundtrip_recurrence_alarm_timezone(self):
        saved = self.service.save(example(frequency='WEEKLY', weekdays=['MO', 'WE'], count=8, reminders=[0, 10, 60]))
        calendar = self.calendar()
        event = calendar.walk('VEVENT')[0]
        self.assertEqual(str(event['summary']), saved['title'])
        self.assertEqual(event['dtstart'].dt.hour, 9)
        self.assertEqual(event['rrule']['BYDAY'], ['MO', 'WE'])
        self.assertEqual(event['rrule']['COUNT'], [8])
        self.assertEqual(len(calendar.walk('VALARM')), 3)
        self.assertEqual(len(calendar.walk('VTIMEZONE')), 1)
        self.assertEqual(str(event['uid']), saved['uid'])

    def test_edit_uid_sequence_persistence_delete(self):
        first = self.service.save(example())
        changed = dict(first, title='修改后')
        second = self.service.save(changed, first['id'])
        self.assertEqual(first['uid'], second['uid'])
        self.assertEqual(second['sequence'], 1)
        self.assertEqual(second['created'], first['created'])
        restarted = CalendarService(self.root, self.sources)
        self.assertEqual(restarted.snapshot()['events'][0]['title'], '修改后')
        restarted.delete(first['id'])
        self.assertEqual(self.calendar().walk('VEVENT'), [])
        with self.assertRaises(KeyError):
            restarted.save(example(), first['id'])

    def test_all_day_exclusive_end(self):
        self.service.save({'title': '休假', 'all_day': True, 'start': '2026-10-19', 'end': '2026-10-21', 'frequency': 'YEARLY', 'until': '2030-10-19'})
        event = self.calendar().walk('VEVENT')[0]
        self.assertEqual(event['dtstart'].dt, date(2026, 10, 19))
        self.assertEqual(event['dtend'].dt, date(2026, 10, 21))
        self.assertEqual(event['rrule']['UNTIL'], [date(2030, 10, 19)])

    def test_validation_does_not_write(self):
        cases = [dict(title=''), dict(end='2026-10-19T08:00'), dict(timezone='Not/AZone'), dict(count=2, until='2026-12-01'), dict(reminders=[-1]), dict(interval=0), dict(status='bad'), dict(url='javascript:alert(1)'), dict(all_day='false'), dict(start='2026-10-19T09:00+08:00')]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.service.save(dict(example(), **change))
        self.assertFalse((self.root / 'data/calendar.json').exists())

    def test_dst_gap_rejected_and_until_utc(self):
        with self.assertRaises(ValidationError):
            validate_event(dict(example(), timezone='America/New_York', start='2026-03-08T02:30', end='2026-03-08T04:00'))
        self.service.save(dict(example(frequency='DAILY', until='2026-12-01'), timezone='America/New_York'))
        until = self.calendar().walk('VEVENT')[0]['rrule']['UNTIL'][0]
        self.assertEqual(until.utcoffset().total_seconds(), 0)

    def test_plugin_refresh_isolation_and_failure_retention(self):
        self.service.save(example())
        self.service.refresh('test', {'title': '导入日程'})
        first = next(e for e in self.service.snapshot()['events'] if e['source'] == 'test')
        self.service.refresh('test', {'title': '导入日程'})
        second = next(e for e in self.service.snapshot()['events'] if e['source'] == 'test')
        self.assertEqual(first, second)
        self.assertEqual(len(self.calendar().walk('VEVENT')), 2)
        self.assertEqual(len(self.calendar('test').walk('VEVENT')), 1)
        self.assertEqual(len(self.calendar('manual').walk('VEVENT')), 1)
        with self.assertRaises(RuntimeError):
            self.service.refresh('test', {'fail': True})
        self.assertEqual(len(self.service.snapshot()['events']), 2)
        self.service.refresh('test', {'title': '更新导入'})
        updated = next(e for e in self.service.snapshot()['events'] if e['source'] == 'test')
        self.assertEqual(updated['uid'], first['uid'])
        self.assertEqual(updated['sequence'], 1)

    def test_http_workflow(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(WorkspaceService(self.root / 'http', self.sources)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, method='GET', body=None, headers=None):
            data = None if body is None else json.dumps(body).encode()
            return urlopen(Request(base + path, data=data, method=method, headers=headers or {'Content-Type': 'application/json'}))
        try:
            with request('/') as response:
                self.assertIn('日历汇集', response.read().decode())
            with request('/api/projects/default/events', 'POST', example()) as response:
                self.assertEqual(response.status, 201)
                event = json.load(response)
            with request('/subscription/default.ics') as response:
                self.assertIn('text/calendar', response.headers['Content-Type'])
                self.assertEqual(len(Calendar.from_ical(response.read()).walk('VEVENT')), 1)
            with self.assertRaises(HTTPError) as ctx:
                request('/api/projects/default/events', 'POST', example(), {'Content-Type': 'application/json', 'Origin': 'https://other.invalid'})
            self.assertEqual(ctx.exception.code, 403)
            with self.assertRaises(HTTPError) as ctx:
                request('/subscription/../../data/calendar.json')
            self.assertEqual(ctx.exception.code, 404)
            with request('/api/projects/default/events/' + event['id'], 'DELETE', {}) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
