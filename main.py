import datetime
from demo.curricular import iCalendarCourseScheduleGeneratorImpl
from demo.tabular import TableCalendarScheduleGeneratorImpl
from demo.ynuimpl import YunnanUniversityGraduateCourseScheduleResolver, GroupReportScheduleResolver, DutyScheduleResolver

def make_course_schedule():
    name = 'ynu-2024-spring'
    cookies = '...'
    first_week_date = datetime.datetime(2024, 2, 26)
    resolver = YunnanUniversityGraduateCourseScheduleResolver(cookies)
    generator = iCalendarCourseScheduleGeneratorImpl(name, resolver, first_week_date)
    generator.generate()
    generator.export(f'{name}.ics')

def make_group_report_schedule():
    name = 'group-report-2024-spring'
    resolver = GroupReportScheduleResolver('春季学期组会安排.xlsx')
    generator = TableCalendarScheduleGeneratorImpl(name, resolver)
    generator.generate()
    generator.export(f'{name}.ics')

def make_duty_schedule():
    name = 'duty-schedule-2024-spring'
    resolver = DutyScheduleResolver('值班表.xlsx', '陈朝伟')
    generator = TableCalendarScheduleGeneratorImpl(name, resolver)
    generator.generate()
    generator.export(f'{name}.ics')

if __name__ == '__main__':
    make_duty_schedule()
