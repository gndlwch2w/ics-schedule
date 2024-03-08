# ics-schedule

采用 iCalendar 协议从教务网课表数据生成 ics 课表文件，用作日历的日程提醒与安排。

### 1 Example

```python
import datetime
from demo.curricular import iCalendarCourseScheduleGeneratorImpl
from demo.ynuimpl import YunnanUniversityGraduateCourseScheduleResolver

if __name__ == '__main__':
    name = 'ynu-2024-spring-v2'
    cookies = '...'
    first_week_date = datetime.datetime(2024, 2, 26)
    resolver = YunnanUniversityGraduateCourseScheduleResolver(cookies)
    generator = iCalendarCourseScheduleGeneratorImpl(name, resolver, first_week_date)
    generator.generate()
    generator.export(f'{name}.ics')
```

其生成的 `ynu-2023-autumn.ics` 文件样例：

```ics
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Chisheng Chen//ynu-2023-autumn//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALDESC:ynu-2023-autumn
X-WR-CALNAME:ynu-2023-autumn
X-WR-TIMEZONE:Asia/Shanghai
BEGIN:VEVENT
SUMMARY:新时代中国特色社会主义理论与实践
DTSTART;TZID=Asia/Shanghai:20230907T165500
DTEND;TZID=Asia/Shanghai:20230907T174000
DTSTAMP;TZID=Asia/Shanghai:20230809T234838
UID:20230809T234838-1cc33338a6ac4818a61f60755f51621d@Chisheng Chen
SEQUENCE:0
DESCRIPTION:张子建
LOCATION:文汇楼1栋1201
STATUS:CONFIRMED
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:新时代中国特色社会主义理论与实践
REPEAT:2
TRIGGER:-PT25M
END:VALARM
END:VEVENT
...
END:VCALENDAR
```

### 2 References

- iCalendar for Python: https://icalendar.readthedocs.io/en/latest/usage.html#more-documentation
- RFC 2445: https://datatracker.ietf.org/doc/html/rfc2445#section-4.8.6.1
- 小爱课程表文档: https://ldtu0m3md0.feishu.cn/docs/doccnhZPl8KnswEthRXUz8ivnhb
- iCalendar Specification Excerpts: https://www.kanzaki.com/docs/ical/created.html

