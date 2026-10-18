from . import CalendarSource


class ManualSource(CalendarSource):
    id = "manual"
    title = "手动日程"
    description = "从一个想法开始，安排每一个重要时刻。支持全天、重复日程与多重提醒。"

    def collect(self, config, records):
        return records
