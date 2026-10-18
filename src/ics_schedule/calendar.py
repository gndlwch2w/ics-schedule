"""Serialize using icalendar, including timezone definitions and alarm components."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from icalendar import Alarm, Calendar, Event
from .models import event_time


def serialize(records, name="汇总日历"):
    calendar = Calendar()
    calendar.add("prodid", "-//ics-schedule//Calendar Hub//ZH")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", name)
    for record in records:
        event = Event()
        event.add("uid", record["uid"])
        event.add("sequence", record["sequence"])
        event.add("dtstamp", datetime.fromisoformat(record["updated"]))
        event.add("last-modified", datetime.fromisoformat(record["updated"]))
        event.add("created", datetime.fromisoformat(record["created"]))
        event.add("summary", record["title"])
        for key in ("start", "end"):
            event.add("dt" + key, event_time(record[key], record["all_day"], record["timezone"]))
        for key in ("description", "location", "url", "status"):
            if record[key]:
                event.add(key, record[key])
        event.add("class", record["privacy"])
        event.add("transp", record["availability"])
        if record["categories"]:
            event.add("categories", [c.strip() for c in record["categories"].split(",") if c.strip()])
        if record["frequency"]:
            rule = {"freq": record["frequency"], "interval": record["interval"]}
            if record["count"]:
                rule["count"] = record["count"]
            if record["until"]:
                until = date.fromisoformat(record["until"])
                rule["until"] = until if record["all_day"] else datetime.combine(until, time(23, 59, 59), ZoneInfo(record["timezone"])).astimezone(timezone.utc)
            if record["frequency"] == "WEEKLY" and record["weekdays"]:
                rule["byday"] = record["weekdays"]
            event.add("rrule", rule)
        for minutes in record["reminders"]:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", record["title"])
            alarm.add("trigger", -timedelta(minutes=minutes))
            event.add_component(alarm)
        calendar.add_component(event)
    # Cover the full supported scheduling range, including future recurring events.
    calendar.add_missing_timezones(first_date=date(1970, 1, 1), last_date=date(2100, 1, 1))
    return calendar.to_ical()
