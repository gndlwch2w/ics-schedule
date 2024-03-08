from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ics import iCalendar, iCalendarImpl

__all__ = ['ScheduleResolver', 'iCalendarScheduleGenerator']

class ScheduleResolver(ABC):
    """日程解析器"""

    @abstractmethod
    def parser(self, resource: Any) -> Any:
        """数据解析接口"""
        raise NotImplemented('parser')

    @abstractmethod
    def provider(self) -> Any:
        """数据提供接口"""
        raise NotImplemented('provider')

    def resolve(self) -> Any:
        """返回解析后的数据"""
        return self.parser(self.provider())

class iCalendarScheduleGenerator(ABC):
    """iCalendar 日程生成器"""
    def __init__(self, name: str, resolver: ScheduleResolver, writer: iCalendar | None = None):
        self.name = name
        self.resolver = resolver
        self.writer = writer or iCalendarImpl

    @abstractmethod
    def generate(self) -> None:
        """生成 iCalendar 日程信息"""
        raise NotImplemented('generate')

    def export(self, filename: str) -> None:
        """导出 iCalendar 日程到文件"""
        self.writer.to_ics(filename)
