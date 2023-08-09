import datetime
from api import *
from ynu import YNUGraduateClassScheduleResolver

if __name__ == '__main__':
    name = "ynu-2023-autumn"
    first_week_date = datetime.datetime(2023, 9, 4)
    resolver = YNUGraduateClassScheduleResolver()
    generator = ICSClassScheduleGenerator(name, resolver, first_week_date)
    generator.generate()
    generator.export(f"{name}.ics")
