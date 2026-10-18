"""Offline fixtures for the optional NJUST HTML scraper; no real credentials."""
import unittest
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ics_schedule.plugins import njust
from ics_schedule.plugins import load_sources
from ics_schedule.service import CalendarService


LIST_HTML = '''
<html><form><table><tr><th>课程名称</th><th>星期</th><th>周次</th>
<th>节次</th><th>地点</th><th>教师</th></tr>
<tr><td>模式识别</td><td>星期二</td><td>2-4周</td>
<td>第1-2节</td><td>教学楼A201</td><td>张老师</td></tr></table></form></html>
'''
GRID_TEMPLATE = '''
<html><form action="StuCourseQuery.aspx?EID=example" method="post">
<input name="__VIEWSTATE" value="state-{week}" type="hidden"/>
<input name="__EVENTVALIDATION" value="validation-{week}" type="hidden"/>
<select name="ctl00$Content$DropDownListWeeks">
<option value="1" {sel1}>第1周</option><option value="2" {sel2}>第2周</option>
</select>
<table><tr><th>节次</th><th>星期一</th><th>星期二</th><th>星期三</th></tr>
<tr><td>1-2节</td><td></td><td>算法设计<br>教师：王老师<br>地点：A101</td><td></td></tr>
</table></form></html>
'''
CAL_HTML = '''<html><table>
<tr><td>第一周</td><td>2026年9月7日 - 2026年9月13日</td></tr>
<tr><td>第2周</td><td>2026-09-14 至 2026-09-20</td></tr>
</table></html>'''
NJUST_GRID_HTML = '''<html><body>学期：2026-2027秋学期
<table><tr><th>时间</th><th>节次</th><th>星期一</th><th>星期二</th>
<th>星期三</th><th>星期四</th><th>星期五</th><th>星期六</th><th>星期日</th></tr>
<tr><td rowspan="5">上午</td><td>1</td><td rowspan="2">高级英语学术写作6班
｛4-6、8-15周[教师:焦保清,地点:III-116]｝</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td>2</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td>3</td><td rowspan="1">高级英语学术写作6班
｛4-6、8-14周[教师:焦保清,地点:III-116]｝</td><td></td><td></td><td></td><td></td><td></td></tr></table>
<table><tr><td>上午： 第1节： 8:00-8:45 第2节： 8:50-9:35
第3节： 9:40-10:25</td></tr></table></body></html>'''
NJUST_CALENDAR_GRID = '''<html><body><div>学期：2026-2027秋学期</div><table>
<tr><th>周次</th><th>星期一</th><th>星期二</th><th>星期三</th><th>星期四</th>
<th>星期五</th><th>星期六</th><th>星期日</th></tr>
<tr><td>一</td><td>24 (8月)</td><td>25 (8月)</td><td>26 (8月)</td><td>27 (8月)</td>
<td>28 (8月)</td><td>29 (8月)</td><td>30 (8月)</td></tr>
<tr><td>十九</td><td>28 (12月)</td><td>29 (12月)</td><td>30 (12月)</td><td>31 (12月)</td>
<td>1 (1月)</td><td>2 (1月)</td><td>3 (1月)</td></tr></table></body></html>'''


def grid_html(week):
    return GRID_TEMPLATE.format(week=week, sel1='selected="selected"' if week == 1 else '',
                                sel2='selected="selected"' if week == 2 else '')


class TestNJUSTWeb(unittest.TestCase):
    def test_term_calendar(self):
        self.assertEqual(njust.parse_term_calendar(CAL_HTML),
                         {1: date(2026, 9, 7), 2: date(2026, 9, 14)})

    def test_term_calendar_year_boundary(self):
        html = '<table><tr><td>第17周</td><td>2026-12-28 至 1月3日</td></tr></table>'
        self.assertEqual(njust.parse_term_calendar(html)[17], date(2026, 12, 28))

    def test_real_njust_term_calendar_grid(self):
        self.assertEqual(njust.parse_term_calendar(NJUST_CALENDAR_GRID),
                         {1: date(2026, 8, 24), 19: date(2026, 12, 28)})

    def test_chinese_number_week_select(self):
        html = '<select name="DropDownListWeeks"><option value="x1">第一周</option>' + \
               '<option value="x2" selected>第十二周</option></select>'
        self.assertEqual(njust._week_selector(njust.BeautifulSoup(html, 'html.parser'))[1:],
                         ({1: 'x1', 12: 'x2'}, 12))

    def test_course_list_weeks_and_times(self):
        times = {1: ('08:00', '08:45'), 2: ('08:55', '09:40')}
        events = njust.parse_timetable(LIST_HTML, '2026-09-07', period_times=times)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]['start'], '2026-09-15T08:00')
        self.assertEqual(events[0]['end'], '2026-09-15T09:40')
        self.assertEqual(events[2]['start'], '2026-09-29T08:00')
        self.assertEqual(events[0]['location'], '教学楼A201')

    def test_grid_single_week(self):
        times = {1: ('08:00', '08:45'), 2: ('08:55', '09:40')}
        items = njust.parse_timetable(grid_html(2), '2026-09-07', 2, times)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['start'], '2026-09-15T08:00')
        self.assertEqual(items[0]['end'], '2026-09-15T09:40')
        self.assertIn('王老师', items[0]['description'])

    def test_grid_rowspan_merges_periods(self):
        html = """<table><tr><th>节次</th><th>星期一</th><th>星期二</th><th>星期三</th></tr>
        <tr><td>1节</td><td></td><td rowspan="2">信息检索<br>2周</td><td></td></tr>
        <tr><td>2节</td><td></td><td></td></tr></table>"""
        times = {1: ('08:00', '08:45'), 2: ('08:55', '09:40')}
        items = njust.parse_timetable(html, '2026-09-07', 2, times)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['start'], items[0]['end']),
                         ('2026-09-15T08:00', '2026-09-15T09:40'))

    def test_real_njust_grid_two_leading_columns_and_inline_details(self):
        times = njust.discover_period_times(NJUST_GRID_HTML)
        self.assertEqual(times, {1: ('08:00', '08:45'), 2: ('08:50', '09:35'),
                                 3: ('09:40', '10:25')})
        items = njust.parse_timetable(NJUST_GRID_HTML, week_dates={
            week: date(2026, 8, 24) + (week - 1) * njust.timedelta(weeks=1)
            for week in range(1, 16)
        }, period_times=times)
        self.assertEqual(len(items), 11)
        self.assertEqual(items[0]['title'], '高级英语学术写作6班')
        self.assertEqual(items[0]['location'], 'III-116')
        self.assertEqual(items[0]['description'], '任课教师：焦保清')
        self.assertEqual(items[0]['start'], '2026-09-14T08:00')
        self.assertEqual(items[0]['end'], '2026-09-14T10:25')
        self.assertEqual(items[-1]['end'], '2026-11-30T09:35')

    def test_adjacent_same_course_cells_merge_but_different_rooms_do_not(self):
        day = date(2026, 9, 14)
        first = njust._event(day, '课程', '08:00', '09:35', 'A101', '张老师')
        adjacent = njust._event(day, '课程', '09:40', '10:25', 'A101', '张老师')
        other_room = njust._event(day, '课程', '10:40', '11:25', 'A102', '张老师')
        items = njust._merge_adjacent([other_room, adjacent, first])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['end'], '2026-09-14T10:25')
        self.assertEqual(items[1]['location'], 'A102')

    def test_list_multiple_weekdays_and_odd_weeks(self):
        html = LIST_HTML.replace('星期二', '周一、周三').replace('2-4周', '1-4周(单)')
        times = {1: ('08:00', '08:45'), 2: ('08:55', '09:40')}
        events = njust.parse_timetable(html, '2026-09-07', period_times=times)
        self.assertEqual(len(events), 4)
        self.assertEqual(events[0]['start'], '2026-09-07T08:00')

    def test_week_selector_and_postback(self):
        soup = njust.BeautifulSoup(grid_html(1), 'html.parser')
        name, options, current = njust._week_selector(soup)
        self.assertEqual((options, current), ({1: '1', 2: '2'}, 1))
        fields, action = njust._webform_payload(soup, name, '2')
        self.assertEqual(fields['__EVENTTARGET'], name)
        self.assertEqual(fields[name], '2')
        self.assertEqual(fields['__VIEWSTATE'], 'state-1')
        self.assertEqual(action, 'StuCourseQuery.aspx?EID=example')

    def test_no_login_and_wrong_markup_rejected(self):
        for html in ('<input type="password"/>', '<html><p>未知页面</p></html>'):
            with self.assertRaises(njust.ScheduleError):
                njust.parse_timetable(html, '2026-09-07')

    def test_reject_external_hosts(self):
        for url in ('http://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx',
                    'https://other.test/Gstudent/Course/StuCourseQuery.aspx',
                    'https://gsmis.njust.edu.cn.evil.test/Gstudent/Course/StuCourseQuery.aspx'):
            with self.assertRaises(njust.ScheduleError):
                njust._safe_url(url, njust.COURSE_PATH)

    def test_discover_calendar_from_link_and_javascript(self):
        url = 'https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx?EID=LOCAL_SECRET'
        for html in (
            '<a href="/PublicPage/TermCalender.aspx?EID=LOCAL_CAL">教学日历</a>',
            "<script>window.open('/PublicPage/TermCalender.aspx?EID=LOCAL_CAL');</script>",
            '<a onclick="openWin(\'/PublicPage/TermCalender.aspx?EID=LOCAL_CAL\')">日历</a>',
        ):
            self.assertEqual(njust.discover_term_calendar(html, url),
                'https://gsmis.njust.edu.cn/PublicPage/TermCalender.aspx?EID=LOCAL_CAL')
        self.assertIsNone(njust.discover_term_calendar('<p>no calendar</p>', url))

    def test_discover_explicit_period_times(self):
        html = '<table><tr><td>第1节</td><td>08:00-08:45</td></tr>' + \
               '<tr><td>第2节</td><td>08:55-09:40</td></tr></table>'
        self.assertEqual(njust.discover_period_times(html),
                         {1: ('08:00', '08:45'), 2: ('08:55', '09:40')})

    def test_collect_from_form_fields_calendar_link_and_cookie_redaction(self):
        calls = []
        def fake_fetch(session, method, url, path, **kwargs):
            calls.append((method, path, kwargs.get('data', {})))
            if path == njust.TERM_PATH:
                return CAL_HTML
            week = 1 if method == 'GET' else int(kwargs['data']['ctl00$Content$DropDownListWeeks'])
            return grid_html(week).replace('</form>',
                '<a href="/PublicPage/TermCalender.aspx?EID=LOCAL_CAL">教学日历</a>' +
                '<table><tr><td>第1节</td><td>08:00-08:45</td></tr>' +
                '<tr><td>第2节</td><td>08:55-09:40</td></tr></table></form>')
        config = {'course_url': 'https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx?EID=LOCAL_SECRET',
                  'cookie': 'ASP.NET_SessionId=FAKE_TEST_TOKEN; LoginType=1'}
        with patch.object(njust, '_fetch', side_effect=fake_fetch):
            items = njust.NJUSTGraduateWebSource().collect(config, [])
        self.assertEqual([e['start'] for e in items], ['2026-09-08T08:00', '2026-09-15T08:00'])
        self.assertEqual([(call[0],call[1]) for call in calls],
                         [('GET', njust.COURSE_PATH), ('GET', njust.TERM_PATH), ('POST', njust.COURSE_PATH)])
        self.assertNotIn('FAKE_TEST_TOKEN', str(items))
        self.assertNotIn('LOCAL_SECRET', str(items))
        self.assertNotIn('LOCAL_CAL', str(items))

    def test_request_profile_matches_current_chrome_session(self):
        captured = {}
        def fake_fetch(session, method, url, path, **kwargs):
            captured.update(session.headers)
            if path == njust.TERM_PATH:
                return CAL_HTML
            week = 1 if method == 'GET' else int(kwargs['data']['ctl00$Content$DropDownListWeeks'])
            return GRID_TEMPLATE.format(
                week=week,
                sel1='selected' if week == 1 else '',
                sel2='selected' if week == 2 else '',
            ).replace(
                '</form>', '<a href="/PublicPage/TermCalender.aspx?EID=LOCAL">教学日历</a>'
                '<table><tr><td>第1节</td><td>08:00-08:45</td></tr>'
                '<tr><td>第2节</td><td>08:55-09:40</td></tr></table></form>')
        with patch.object(njust, '_fetch', side_effect=fake_fetch):
            njust.NJUSTGraduateWebSource().collect({
                'course_url': 'https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx?EID=LOCAL',
                'cookie': 'ASP.NET_SessionId=TOKEN; LoginType=1',
            }, [])
        normalized = {key.lower(): value for key, value in captured.items()}
        self.assertIn('Chrome/155.0.0.0', normalized['user-agent'])
        self.assertEqual(normalized['sec-fetch-dest'], 'document')

    def test_no_events_does_not_replace_existing_data(self):
        with patch.object(njust, '_fetch', return_value='<html><body>failure</body></html>'):
            with self.assertRaises(njust.ScheduleError):
                njust.NJUSTGraduateWebSource().collect({
                    'course_url': 'https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx',
                    'cookie': 'LoginType=1'}, [])

    def test_input_only_two_required_fields(self):
        fields = njust.NJUSTGraduateWebSource.fields
        self.assertEqual([f['name'] for f in fields], ['course_url', 'cookie'])
        self.assertTrue(all(f['transient'] and f['required'] for f in fields))

    def test_cookie_value_or_complete_request_headers(self):
        value = 'ASP.NET_SessionId=TOKEN; LoginType=1'
        self.assertEqual(njust._cookie_header(value), value)
        self.assertEqual(njust._cookie_header('Cookie: ' + value), value)
        headers = ('GET /Gstudent/Course/StuCourseQuery.aspx HTTP/1.1\r\n'
                   'Accept: text/html\r\nCache-Control: max-age=0\r\nCookie: ' + value +
                   '\r\nHost: gsmis.njust.edu.cn\r\nX-Unsafe: ignored')
        self.assertEqual(njust._cookie_header(headers), value)
        cookie, profile = njust._request_profile(headers)
        self.assertEqual(cookie, value)
        self.assertEqual(profile, {'Accept': 'text/html', 'Cache-Control': 'max-age=0'})
        with self.assertRaises(njust.ScheduleError):
            njust._cookie_header('GET / HTTP/1.1\r\nHost: gsmis.njust.edu.cn')

    def test_built_in_source_is_loaded_without_cli_flag(self):
        self.assertIn('njust_graduate_web', load_sources())

    def test_copied_browser_headers_override_request_defaults(self):
        captured = {}
        complete_headers = ('GET /Gstudent/Course/StuCourseQuery.aspx HTTP/1.1\r\n'
                            'Accept: text/html\r\nCache-Control: max-age=0\r\n'
                            'User-Agent: Browser-Test\r\n'
                            'Cookie: ASP.NET_SessionId=TOKEN; LoginType=1')
        def fake_fetch(session, method, url, path, **kwargs):
            captured.update({key.lower(): value for key, value in session.headers.items()})
            if path == njust.TERM_PATH:
                return CAL_HTML
            week = 1 if method == 'GET' else int(kwargs['data']['ctl00$Content$DropDownListWeeks'])
            return grid_html(week).replace('</form>',
                '<a href="/PublicPage/TermCalender.aspx?EID=LOCAL">教学日历</a>'
                '<table><tr><td>第1节</td><td>08:00-08:45</td></tr>'
                '<tr><td>第2节</td><td>08:55-09:40</td></tr></table></form>')
        with patch.object(njust, '_fetch', side_effect=fake_fetch):
            njust.NJUSTGraduateWebSource().collect({
                'course_url': 'https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx?EID=LOCAL',
                'cookie': complete_headers,
            }, [])
        self.assertEqual(captured['cache-control'], 'max-age=0')
        self.assertEqual(captured['user-agent'], 'Browser-Test')
        self.assertNotIn('pragma', captured)

    def test_url_and_cookie_are_never_persisted(self):
        config = {
            'course_url': 'https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx?EID=LOCAL_SECRET',
            'cookie': 'ASP.NET_SessionId=FAKE_TEST_TOKEN; LoginType=1',
        }
        with tempfile.TemporaryDirectory() as root:
            service = CalendarService(root, load_sources(), 'njust-test', 'NJUST')
            with patch.object(njust.NJUSTGraduateWebSource, 'collect', return_value=[{
                'id': 'course-1', 'title': '测试课程',
                'start': '2026-09-08T08:00', 'end': '2026-09-08T09:40',
                'timezone': 'Asia/Shanghai',
            }]):
                service.refresh('njust_graduate_web', config)
            raw = (Path(root) / 'data/projects/njust-test.json').read_text()
            self.assertNotIn('FAKE_TEST_TOKEN', raw)
            self.assertNotIn('LOCAL_SECRET', raw)
            self.assertNotIn('course_url', json.loads(raw)['configs'].get('njust_graduate_web', {}))


if __name__ == '__main__':
    unittest.main()
