from __future__ import annotations
from abc import ABC, abstractmethod
import pytz
import uuid
import getpass
from datetime import datetime
from icalendar import Calendar, Event, vDatetime, vText, Alarm
from icalendar.cal import Component

__all__ = ['iCalendar', 'iCalendarImpl']

def timerify(time: str, time_format: str) -> datetime:
    return datetime.strptime(time, time_format)

def prettify(component: Component) -> str:
    return component.to_ical().decode('utf-8').replace('\r\n', '\n').strip()

class iCalendar(ABC):
    """iCalendar 事件生成工具"""
    def __init__(self,
                 author: str | None = None,
                 name: str | None = None,
                 description: str | None = None,
                 timezone: str | None = None,
                 time_format: str | None = None) -> None:
        self.calendar = Calendar()
        self.author = author or getpass.getuser()
        self.timezone = timezone or 'Asia/Shanghai'
        self.time_format = time_format or '%Y-%m-%d %H:%M:%S'
        # 标识生成该 iCalendar 对象的软件
        self.calendar['PRODID'] = f'-//Chisheng Chen//iCalendar//EN'
        # 指定 iCalendar 规范的版本
        self.calendar['VERSION'] = '2.0'
        # 指定日历中日期和时间的标度，GREGORIAN 表示使用公历
        self.calendar['CALSCALE'] = 'GREGORIAN'
        # 指定用于处理 iCalendar 对象的方法， PUBLISH（发布）、REQUEST（请求）、REPLY（回复）
        self.calendar['METHOD'] = 'PUBLISH'
        # 定义日历的名称
        if name is not None:
            self.calendar['X-WR-CALNAME'] = name
        # 定义日历中所有事件的默认时区
        self.calendar['X-WR-TIMEZONE'] = self.timezone
        # 提供日历的描述信息
        if description is not None:
            self.calendar['X-WR-CALDESC'] = description

    @abstractmethod
    def add_event(self,
                  event_name: str,
                  start_time: str | datetime,
                  end_time: str | datetime,
                  description: str | None = None,
                  location: str | None = None,
                  reminder_time: str | datetime = None,
                  reminder_type: str = 'DISPLAY',
                  reminder_text: str = '{event_name}') -> None:
        """添加一个事件"""
        raise NotImplemented('add_event')

    def to_ics(self, filename: str) -> None:
        """导出 iCalendar 到文件"""
        with open(filename, 'wb') as fp:
            fp.write(self.calendar.to_ical())

class iCalendarImpl(iCalendar):
    def __init__(self, author, name, description, timezone=None, time_format=None):
        super(iCalendarImpl, self).__init__(author, name, description, timezone, time_format)
        self.timezone = pytz.timezone(self.timezone)

    def add_event(self, event_name, start_time, end_time, description=None, location=None,
                  reminder_time=None, reminder_type='DISPLAY', reminder_text='{event_name}') -> None:
        event = Event()
        # 事件记录的创建日期和时间
        event['DTSTAMP'] = vDatetime(datetime.now(self.timezone))
        # 事件开始的日期和时间
        if isinstance(start_time, str):
            start_time = timerify(start_time, self.time_format)
        event['DTSTART'] = vDatetime(start_time.astimezone(self.timezone))
        # 事件结束的日期和时间
        if isinstance(end_time, str):
            end_time = timerify(end_time, self.time_format)
        event['DTEND'] = vDatetime(end_time.astimezone(self.timezone))
        # 事件的唯一标识符，用于确保事件的唯一性
        event['UID'] = f'{prettify(event["DTSTAMP"])}-{uuid.uuid4().hex}@{self.author}'
        # 事件的状态，如 CONFIRMED（已确认）、TENTATIVE（暂定）或 CANCELLED（已取消）
        event['STATUS'] = 'CONFIRMED'
        # 事件的摘要或标题
        event['SUMMARY'] = vText(event_name)
        # 对事件的详细描述
        if description:
            event['DESCRIPTION'] = vText(description)
        # 事件发生的地点
        if location:
            event['LOCATION'] = vText(location)
        # 用于指示事件的版本号或序列号，每次事件更新都会增加这个值
        event['SEQUENCE'] = 0
        # 事件提醒设置
        if reminder_time is not None:
            alarm = Alarm()
            # 指定 Alarm 何时触发，指定触发时间的绝对值（具体的日期和时间）
            if isinstance(reminder_time, str):
                reminder_time = timerify(reminder_time, self.time_format)
            alarm['TRIGGER;VALUE=DATE-TIME'] = vDatetime(reminder_time.astimezone(self.timezone))
            # 指定 Alarm 的动作类型，如 AUDIO（播放声音）, DISPLAY（显示消息），EMAIL（发送电子邮件）等
            alarm['ACTION'] = reminder_type
            # 对 Alarm 的描述，显示在提醒界面上
            alarm['DESCRIPTION'] = reminder_text.format({
                'event_name': repr(event_name),
                'start_time': repr(start_time),
                'end_time': repr(end_time),
                'description': repr(description),
                'location': repr(location)
            })
            event.add_component(alarm)
        self.calendar.add_component(event)
