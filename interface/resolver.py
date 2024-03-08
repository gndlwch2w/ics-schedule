from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

__all__ = ['ScheduleResolver']

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
