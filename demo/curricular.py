from __future__ import annotations
from abc import ABC
import datetime
from interface.resolver import ScheduleResolver
from interface.igenerator import iCalendarScheduleGenerator
from interface.icalendar import iCalendarImpl

__all__ = [
    'CourseScheduleResolver',
    'iCalendarCourseScheduleGenerator',
    'iCalendarCourseScheduleGeneratorImpl'
]

class CourseScheduleResolver(ScheduleResolver, ABC):
    """课表解析器

    解析课表数据，返回数据的格式如下：
        {
            "course_info": [{  // 课程数据
                "name": "新时代中国特色社会主义理论与实践",  // 课程名
                "position": "文汇楼1栋1201",  // 上课地点
                "teacher": "张子建",  // 授课教师
                "weeks": [ 1, 2, ..., 18 ],  // 上课周
                "day": 4,  // 上课星期
                "sections": [ 7, 8 ]  // 上课节数
            }, ...],
            "section_times": [{  //上课节数时间安排
                    "section": 1,  // 第几节
                    "start_time": "08:30",  // 此节上课开始时间
                    "end_time": "09:15"  // 此节上课结束时间
                }, ...
            ]
        }
    """
    pass

class iCalendarCourseScheduleGenerator(iCalendarScheduleGenerator, ABC):
    """iCalendar 课程表生成器"""
    def __init__(self, name: str, resolver: CourseScheduleResolver, first_week_date: datetime.datetime) -> None:
        super(iCalendarCourseScheduleGenerator, self).__init__(name, resolver, None)
        self.first_week_date = first_week_date

class iCalendarCourseScheduleGeneratorImpl(iCalendarCourseScheduleGenerator):
    def __init__(self, name, resolver, first_week_date):
        super(iCalendarCourseScheduleGeneratorImpl, self).__init__(name, resolver, first_week_date)
        self.week_date_dict = {}
        self.section_times_dict = {}
        self.section_timedelta_dict = {}

    def get_week_date(self, num_week: int) -> datetime.datetime:
        if self.week_date_dict.get(num_week) is None:
            self.week_date_dict[num_week] = self.first_week_date + datetime.timedelta(days=7 * (num_week - 1))
        return self.week_date_dict[num_week]

    def get_section_time_delta(self, num_section: int) -> dict[str, datetime.timedelta]:
        if self.section_timedelta_dict.get(num_section) is None:
            section_time = self.section_times_dict[num_section]
            sh, sm = section_time['start_time'].split(':')
            eh, em = section_time['end_time'].split(':')
            self.section_timedelta_dict[num_section] = {
                'start_delta': datetime.timedelta(hours=int(sh), minutes=int(sm)),
                'end_delta': datetime.timedelta(hours=int(eh), minutes=int(em))
            }
        return self.section_timedelta_dict[num_section]

    def init_section_times_dict(self, section_times: list[dict]) -> None:
        for e in section_times:
            self.section_times_dict[e['section']] = e

    def generate(self) -> None:
        data = self.resolver.resolve()
        self.init_section_times_dict(data['section_times'])
        for e in data['course_info']:
            for num_week in e['weeks']:
                for num_section in e['sections']:
                    day_date = self.get_week_date(num_week) + datetime.timedelta(days=e['day'] - 1)
                    section_delta = self.get_section_time_delta(num_section)
                    start_time = day_date + section_delta['start_delta']
                    self.writer.add_event(
                        event_name=e['name'],
                        start_time=start_time,
                        end_time=day_date + section_delta['end_delta'],
                        description=e['teacher'],
                        location=e['position'],
                        # 提前 25 分钟提示
                        reminder_time=start_time - datetime.timedelta(minutes=25),
                        reminder_text='{event_name} {location}')
