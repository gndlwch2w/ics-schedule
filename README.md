# ics-schedule

采用 iCalendar 协议从教务网课表数据生成 ics 课表文件，用作日历的日程提醒与安排。

### 1 Example

```python
import datetime
from course import iCalendarCourseScheduleImpl
from ynu import YunnanUniversityGraduateCourseScheduleResolver

if __name__ == '__main__':
  name = 'ynu-2023-autumn'
  cookies = '...'
  first_week_date = datetime.datetime(2024, 2, 26)
  resolver = YunnanUniversityGraduateCourseScheduleResolver(cookies)
  generator = iCalendarCourseScheduleImpl(name, resolver, first_week_date)
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

导入到 Windows 日历程序如下图所示：

<img src="import-to-window-calendar.png" style="zoom:85%; box-shadow: 0 0 20px rgba(0, 0, 0, .25);"  alt=""/>

### 2 API

- CourseScheduleResolver: 课表解析器
    - parser(resource: Any) -> CourseScheduleType: 解析课表数据，返回解析后的课程数据

      ```json
      // 返回的数据结构
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
      ```

    - provider() -> Any: 返回获取到的课表数据
    - resolve() -> CourseScheduleType: 返回从原始课表解析后的课表数据

- iCalendar: iCalendar 事件生成工具
    - add_event(event_name: str, start_time: str | datetime, end_time: str | datetime, description: str | None = None, location: str | None = None, reminder_time: str | datetime = None, reminder_type: str = 'DISPLAY', reminder_text: str = '{event_name}'): 添加一个事件
    - to_ics(path): 导出 iCalendar 到文件

- iCalendarCourseSchedule: iCalendar 课程表生成工具
    - generate(): 生成 iCalendar 课表
    - export(path): 导出 iCalendar 课表到 ics 文件

### 3 References

- iCalendar for Python: https://icalendar.readthedocs.io/en/latest/usage.html#more-documentation
- RFC 2445: https://datatracker.ietf.org/doc/html/rfc2445#section-4.8.6.1
- 小爱课程表文档: https://ldtu0m3md0.feishu.cn/docs/doccnhZPl8KnswEthRXUz8ivnhb
- iCalendar Specification Excerpts: https://www.kanzaki.com/docs/ical/created.html

