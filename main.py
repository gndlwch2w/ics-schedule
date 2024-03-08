import datetime
from course import iCalendarCourseScheduleImpl
from ynu import YunnanUniversityGraduateCourseScheduleResolver

if __name__ == '__main__':
    name = 'ynu-2024-spring'
    cookies = '...'
    first_week_date = datetime.datetime(2024, 2, 26)
    resolver = YunnanUniversityGraduateCourseScheduleResolver(cookies)
    generator = iCalendarCourseScheduleImpl(name, resolver, first_week_date)
    generator.generate()
    generator.export(f'{name}.ics')
