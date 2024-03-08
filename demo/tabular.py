from abc import ABC
from interface.resolver import ScheduleResolver
from interface.igenerator import iCalendarScheduleGenerator

__all__ = [
    'TableScheduleResolver',
    'TableCalendarScheduleGeneratorImpl'
]

class TableScheduleResolver(ScheduleResolver, ABC):
    """表日程解析器

    解析表数据，返回数据的格式如下：
        [{
            "name": "...",
            "start_time": "2024-3-14 14:00:00",
            "end_time": "2024-3-14 16:00:00",
            "reminder_time": "2024-3-14 16:00:00",
            "description": ".."
            "location": "1514",
        }, ...]
    """
    pass

class TableCalendarScheduleGeneratorImpl(iCalendarScheduleGenerator):
    def __init__(self, name, resolver):
        super(TableCalendarScheduleGeneratorImpl, self).__init__(name, resolver)

    def generate(self):
        for e in self.resolver.resolve():
            self.writer.add_event(
                event_name=e['name'],
                start_time=e['start_time'],
                end_time=e['end_time'],
                description=e['description'],
                location=e['location'],
                # 提前 1 天提示
                reminder_time=e['reminder_time'],
                reminder_text='{event_name} {location}')
