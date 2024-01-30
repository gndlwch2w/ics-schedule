import pytz
import datetime
from uuid import uuid4
from icalendar import Calendar, Event, vDatetime, Alarm

__all__ = [
    "ClassScheduleResolver",
    "ICSClassScheduleWriter",
    "ICSClassScheduleGenerator"
]

class ClassScheduleResolver:
    """课表解析器"""

    def parser(self, res):
        """解析爬取的课表数据，返回解析后的课程数据

        返回数据的格式如下：
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
        raise NotImplemented("parser")

    def provider(self):
        """返回爬取课表数据"""
        raise NotImplemented("provider")

    def resolve(self):
        """返回从原始课表解析后的课表数据"""
        return self.parser(self.provider())

def display(cal: Calendar):
    """格式化输出 ics 数据"""
    data = cal.to_ical()
    return data.decode("utf-8").replace('\r\n', '\n').strip() \
        if isinstance(data, bytes) else data

class ICSClassScheduleWriter:
    """iCalendar 课程表书写本"""

    def __init__(self, author, subject, timezone="Asia/Shanghai"):
        self.cal = Calendar()
        self.author = author
        self.cal["PRODID"] = f"-//{author}//{subject}//EN"
        self.cal["VERSION"] = "2.0"
        self.cal["CALSCALE"] = "GREGORIAN"
        self.cal["METHOD"] = "PUBLISH"
        self.cal["X-WR-CALNAME"] = subject
        self.cal["X-WR-TIMEZONE"] = timezone
        self.cal["X-WR-CALDESC"] = subject
        self.tz = pytz.timezone(timezone)

    def add_schedule(self, start, end, name, teacher, position, alert=25):
        """添加课程计划"""
        event = Event()
        event["DTSTAMP"] = vDatetime(datetime.datetime.now(self.tz))
        event["DTSTART"] = vDatetime(start.astimezone(self.tz))
        event["DTEND"] = vDatetime(end.astimezone(self.tz))
        event["UID"] = f"{display(event['DTSTAMP'])}-{uuid4().hex}@{self.author}"
        event["STATUS"] = "CONFIRMED"
        event["SUMMARY"] = name
        event["DESCRIPTION"] = teacher
        event["LOCATION"] = position
        event["SEQUENCE"] = 0
        if alert is not None and alert > 0:
            alarm = Alarm()
            alarm["TRIGGER"] = f"-PT{alert}M"
            alarm["REPEAT"] = 2
            alarm["ACTION"] = "DISPLAY"
            alarm["DESCRIPTION"] = name
            event.add_component(alarm)
        self.cal.add_component(event)

    def to_ics(self, path):
        """导出课程数据为 ics 文件"""
        with open(path, "wb") as fp:
            fp.write(self.cal.to_ical())

class ICSClassScheduleGenerator:
    """iCalendar 课程表生成器"""

    def __init__(self, name, resolver: ClassScheduleResolver, first_week_date: datetime.datetime):
        self.resolver = resolver
        self.first_week_date = first_week_date
        self.week_date_dict = {}
        self.section_times_dict = {}
        self.section_timedelta_dict = {}
        self.writer = ICSClassScheduleWriter("Chisheng Chen", name)

    def get_week_date(self, num_week):
        if self.week_date_dict.get(num_week) is None:
            self.week_date_dict[num_week] = self.first_week_date + datetime.timedelta(days=7 * (num_week - 1))
        return self.week_date_dict[num_week]

    def get_section_time_delta(self, num_section):
        if self.section_timedelta_dict.get(num_section) is None:
            section_time = self.section_times_dict[num_section]
            sh, sm = section_time["start_time"].split(":")
            eh, em = section_time["end_time"].split(":")
            self.section_timedelta_dict[num_section] = {
                "start_delta": datetime.timedelta(hours=int(sh), minutes=int(sm)),
                "end_delta": datetime.timedelta(hours=int(eh), minutes=int(em))
            }
        return self.section_timedelta_dict[num_section]

    def init_section_times_dict(self, section_times):
        for e in section_times:
            self.section_times_dict[e["section"]] = e

    def generate(self):
        data = self.resolver.resolve()
        self.init_section_times_dict(data["section_times"])
        for e in data["course_info"]:
            for num_week in e["weeks"]:
                for num_section in e["sections"]:
                    day_date = self.get_week_date(num_week) + datetime.timedelta(days=e["day"] - 1)
                    section_delta = self.get_section_time_delta(num_section)
                    self.writer.add_schedule(
                        start=day_date + section_delta["start_delta"],
                        end=day_date + section_delta["end_delta"],
                        name=e["name"],
                        teacher=e["teacher"],
                        position=e["position"])

    def export(self, path):
        self.writer.to_ics(path)
