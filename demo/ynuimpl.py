import os.path
import json
import time
import datetime
import requests
from fake_useragent import UserAgent
import pandas as pd
import re
from demo.curricular import CourseScheduleResolver
from demo.tabular import TableScheduleResolver
from utils import time_strify

__all__ = [
    'YunnanUniversityGraduateCourseScheduleResolver',
    'GroupReportScheduleResolver',
    'DutyScheduleResolver'
]

class YunnanUniversityGraduateCourseScheduleResolver(CourseScheduleResolver):
    """云南大学研究生课程表解析器"""
    def __init__(self, cookies):
        self.ua_generator = UserAgent()
        self.cookies = cookies

    def parser(self, resource):
        def parse_week_str(week_str):
            # 10-18周
            if re.match('([0-9]+)-([0-9]+)周', week_str):
                s, t = week_str[:-1].split('-')
                return list(range(int(s), int(t) + 1))
            # 1,3,5-18周
            if ',' in week_str:
                s, t = week_str[:-1].split('-')
                r = [int(e) for e in s.split(',')]
                r.extend(list(range(r[-1] + 1, int(t) + 1)))
                return r
            # 3周
            if re.match('([0-9]+)周', week_str):
                return [int(week_str[:-1])]
            raise ValueError(f'Invalid week {week_str}')

        # 解析课程信息
        course_info = {}
        for e in resource['results']:
            name = e['KCMC']
            if course_info.get(name) is None:
                course_info[name] = {
                    'name': name,
                    'position': e['JASMC'],
                    'teacher': e['JSXM'],
                    'weeks': parse_week_str(e['ZCMC']),
                    'day': e['XQ'],
                    'sections': [e['KSJCDM']]
                }
            else:
                course_info[name]['weeks'].extend(parse_week_str(e['ZCMC']))
                course_info[name]['sections'].append(e['KSJCDM'])

        # 去除重复数据
        for name, v in course_info.items():
            course_info[name]['weeks'] = list(set(v['weeks']))
            course_info[name]['sections'] = list(set(v['sections']))

        def parse_time_int(time_int):
            time_str = str(time_int)
            time_str = f'0{time_str}' if len(time_str) == 3 else time_str
            return f'{time_str[:2]}:{time_str[2:]}'

        # 解析课程节数时间安排
        section_times = []
        raw_section_times = [e for e in json.loads(resource['skjcList']) if e['JCFADM'] == '02']
        for e in raw_section_times:
            section_times.append({
                'section': int(e['DM']),
                'start_time': parse_time_int(e['KSSJ']),
                'end_time': parse_time_int(e['JSSJ'])
            })

        return {
            'course_info': list(course_info.values()),
            'section_times': section_times
        }

    def provider(self):
        api = 'https://yjsxk.ynu.edu.cn/yjsxkapp/sys/xsxkapp/xsxkCourse/loadKbxx.do'
        params = {
            '_': int(time.time() * 1000)
        }
        headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br',
            'Host': 'yjsxk.ynu.edu.cn',
            'Referer': 'https://yjsxk.ynu.edu.cn/yjsxkapp/sys/xsxkapp/course.html',
            'Cookie': self.cookies,
            'User-Agent': self.ua_generator.chrome
        }
        return requests.get(api, params=params, headers=headers, verify=False).json()

def read_table(filename: str, **kwargs) -> pd.DataFrame:
    if filename.endswith('.csv'):
        return pd.read_csv(filename, **kwargs)
    if filename.endswith('.xlsx'):
        return pd.read_excel(filename, **kwargs)
    raise ValueError(f'Unsupported file type {os.path.splitext(filename)[1]}')

class GroupReportScheduleResolver(TableScheduleResolver):
    """组会日程解析器 @春季学期组会安排.xlsx"""
    def __init__(self, filename):
        super(GroupReportScheduleResolver, self).__init__()
        self.filename = filename

    def parser(self, resource: pd.DataFrame):
        schedule = []
        for _, row in resource.iterrows():
            schedule.append({
                'name': row['组会/讨论内容'].strip(),
                'start_time': time_strify(row['组会时间'] + datetime.timedelta(hours=14)),
                'end_time': time_strify(row['组会时间'] + datetime.timedelta(hours=16)),
                'reminder_time': time_strify(row['组会时间'] - datetime.timedelta(hours=2)),
                'description': f'人员：{row["组会报告/讨论人员"].strip()}, 主持：{row["主持人"].strip()}, '
                               f'形式：{row["组会形式"].strip()}',
                'location': '暂定',
            })
        return schedule

    def provider(self):
        return read_table(self.filename)

class DutyScheduleResolver(TableScheduleResolver):
    """值班日程解析器 @值班表.xlsx"""
    def __init__(self, filename, name):
        super(DutyScheduleResolver, self).__init__()
        self.filename = filename
        self.name = name

    def parser(self, resource: pd.DataFrame):
        schedule = []
        begin_delta = {
            0: datetime.timedelta(hours=8, minutes=30),
            1: datetime.timedelta(hours=14),
            2: datetime.timedelta(hours=19),
        }
        duration_delta = datetime.timedelta(hours=3, minutes=30)
        reminder_delta = datetime.timedelta(hours=2)
        for _, row in resource.iterrows():
            for i in [i for i, e in enumerate(row['值班人员'].split())
                      if e.strip() == self.name]:
                start_time = row['日期'].to_pydatetime() + begin_delta[i]
                schedule.append({
                    'name': '实验室值班',
                    'start_time': start_time,
                    'end_time': start_time + duration_delta,
                    'reminder_time': start_time - reminder_delta,
                    'description': row['值班人员'],
                    'location': '1506',
                })
        return schedule

    def provider(self):
        return read_table(self.filename)
