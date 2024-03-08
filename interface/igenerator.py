from __future__ import annotations
from abc import ABC, abstractmethod
from interface.resolver import ScheduleResolver
from interface.icalendar import iCalendar, iCalendarImpl

__all__ = ['iCalendarScheduleGenerator']

class iCalendarScheduleGenerator(ABC):
    """iCalendar 日程生成器"""

    def __init__(self, name: str, resolver: ScheduleResolver, writer: iCalendar | None = None):
        self.name = name
        self.resolver = resolver
        self.writer = writer or iCalendarImpl(name=name)

    @abstractmethod
    def generate(self) -> None:
        """生成 iCalendar 日程信息"""
        raise NotImplemented('generate')

    def export(self, filename: str) -> None:
        """导出 iCalendar 日程到文件"""
        self.writer.to_ics(filename)
