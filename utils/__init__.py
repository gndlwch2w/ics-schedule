from datetime import datetime
from icalendar.cal import Component

__all__ = [
    'str_timerify',
    'ics_prettify',
    'time_strify'
]

def str_timerify(time: str, time_format: str) -> datetime:
    return datetime.strptime(time, time_format)

def ics_prettify(component: Component) -> str:
    return component.to_ical().decode('utf-8').replace('\r\n', '\n').strip()

def time_strify(time: datetime, time_format: str = '%Y-%m-%d %H:%M:%S') -> str:
    return time.strftime(time_format)
