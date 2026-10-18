"""NJUST graduate timetable provider for the local ics-schedule web UI.

Users provide only a course URL and either a Cookie or copied request headers
through a transient local request.
The teaching-calendar URL is discovered in the timetable HTML and fetched
using that same authenticated session. No credentials/URLs are persisted.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from html import unescape
from http.cookies import SimpleCookie
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from curl_cffi import requests

from . import CalendarSource

HOST = "gsmis.njust.edu.cn"
COURSE_PATH = "/Gstudent/Course/StuCourseQuery.aspx"
TERM_PATH = "/PublicPage/TermCalender.aspx"
MAX_HTML_BYTES = 4 * 1024 * 1024
WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
DAY_RE = re.compile(r"(?:星期|周)\s*([一二三四五六日天1-7])")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)\s*[-~～—–至]\s*([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
PERIOD_RE = re.compile(r"(?:第\s*)?(\d{1,2})\s*(?:[-~～—–至、,，]\s*(\d{1,2}))?\s*节")
PERIOD_CLOCK_RE = re.compile(
    r"第\s*(\d{1,2})\s*节\s*[:：]?\s*"
    r"([01]?\d|2[0-3]):([0-5]\d)\s*[-~～—–至]\s*"
    r"([01]?\d|2[0-3]):([0-5]\d)"
)
WEEK_RE = re.compile(r"(\d{1,2})(?:\s*[-~～—–至]\s*(\d{1,2}))?\s*周")
WEEK_LABEL_RE = re.compile(r"(?:第\s*)?([零〇一二三四五六七八九十百\d]{1,4})\s*周")
DATE_RE = re.compile(r"(?<!\d)(?:(20\d{2})\s*[年./-]\s*)?(1[0-2]|0?[1-9])\s*[月./-]\s*(3[01]|[12]\d|0?[1-9])\s*日?(?!\d)")
COLUMN_NAMES = {
    "title": ("课程名称", "课程名", "课程", "科目"),
    "weekday": ("上课星期", "星期", "周几"),
    "weeks": ("上课周次", "教学周", "周次", "起止周"),
    "sections": ("上课节次", "节次", "节数"),
    "time": ("上课时间", "时间"),
    "location": ("上课地点", "教室", "地点"),
    "teacher": ("任课教师", "授课教师", "教师", "老师"),
    "date": ("上课日期", "日期"),
}
SAFE_REQUEST_HEADERS = {
    "accept": "Accept",
    "accept-encoding": "Accept-Encoding",
    "accept-language": "Accept-Language",
    "cache-control": "Cache-Control",
    "pragma": "Pragma",
    "sec-ch-ua": "Sec-Ch-Ua",
    "sec-ch-ua-mobile": "Sec-Ch-Ua-Mobile",
    "sec-ch-ua-platform": "Sec-Ch-Ua-Platform",
    "sec-fetch-dest": "Sec-Fetch-Dest",
    "sec-fetch-mode": "Sec-Fetch-Mode",
    "sec-fetch-site": "Sec-Fetch-Site",
    "sec-fetch-user": "Sec-Fetch-User",
    "upgrade-insecure-requests": "Upgrade-Insecure-Requests",
    "user-agent": "User-Agent",
}


class ScheduleError(ValueError):
    """User-facing error; never include URLs, HTML, HTTP body or credentials."""


def _request_profile(value):
    """Extract Cookie and a strict allowlist from copied request headers."""
    raw = (value or "").strip()
    if not raw:
        return "", {}
    if "\n" not in raw and "\r" not in raw:
        return (raw[7:].strip() if raw.lower().startswith("cookie:") else raw), {}
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cookies = []
    headers = {}
    for line in lines:
        if ":" not in line:
            continue
        name, header_value = (part.strip() for part in line.split(":", 1))
        lower = name.lower()
        if lower == "cookie":
            cookies.append(header_value)
        elif lower in SAFE_REQUEST_HEADERS and header_value:
            headers[SAFE_REQUEST_HEADERS[lower]] = header_value
    if len(cookies) != 1 or not cookies[0]:
        raise ScheduleError("完整请求头中必须且只能包含一行 Cookie")
    return cookies[0], headers


def _cookie_header(value):
    """Return only the Cookie from a raw value or copied request headers."""
    return _request_profile(value)[0]


def _clean(text):
    return re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()


def _date(value):
    try:
        day = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ScheduleError("请填写正确的学期首周周一日期（YYYY-MM-DD）") from None
    if day.weekday() != 0:
        raise ScheduleError("学期首周日期必须是周一")
    return day


def _reminders(value):
    if value in (None, ""):
        raw = ""
    elif isinstance(value, str):
        raw = value.strip()
    else:
        raise ScheduleError("整体提醒必须为文本")
    if not raw:
        return []
    parts = [part.strip() for part in re.split(r"[,，]", raw)]
    if len(parts) > 5 or any(not re.fullmatch(r"\d+", part) for part in parts):
        raise ScheduleError("整体提醒请填写最多 5 个、以逗号分隔的非负整数")
    reminders = sorted(set(int(part) for part in parts))
    if any(minutes > 525600 for minutes in reminders):
        raise ScheduleError("整体提醒时间须为 0–525600 分钟")
    return reminders


def _times(config):
    raw = config.get("period_times", "{}") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        raise ScheduleError("节次时间表必须为 JSON 对象") from None
    if not isinstance(data, dict):
        raise ScheduleError("节次时间表必须为 JSON 对象")
    result = {}
    for key, item in data.items():
        if not str(key).isdigit() or not 1 <= int(key) <= 30:
            raise ScheduleError("节次时间表的键必须是 1–30 的节次数字")
        if isinstance(item, str):
            match = TIME_RE.fullmatch(item.strip())
            if not match:
                raise ScheduleError("节次时间应为 08:00-08:45 这样的格式")
            start, end = f"{int(match[1]):02d}:{match[2]}", f"{int(match[3]):02d}:{match[4]}"
        elif isinstance(item, list) and len(item) == 2:
            start, end = item
        else:
            raise ScheduleError('节次时间应为 ["08:00","08:45"] 或 "08:00-08:45"')
        try:
            a, b = datetime.strptime(start, "%H:%M"), datetime.strptime(end, "%H:%M")
        except (TypeError, ValueError):
            raise ScheduleError("节次时间必须为 HH:MM") from None
        if b <= a:
            raise ScheduleError("每一节的结束时间必须晚于开始时间")
        result[int(key)] = (a.strftime("%H:%M"), b.strftime("%H:%M"))
    return result


def _weekday(text):
    match = DAY_RE.search(text)
    if match:
        value = match[1]
        return int(value) - 1 if value.isdigit() else WEEKDAY[value]
    value = _clean(text)
    if value in WEEKDAY:
        return WEEKDAY[value]
    if re.fullmatch(r"[1-7]", value):
        return int(value) - 1
    return None


def _weekdays(text):
    matched = DAY_RE.findall(str(text))
    if matched:
        return sorted({int(day) - 1 if day.isdigit() else WEEKDAY[day] for day in matched})
    single = _weekday(text)
    return [single] if single is not None else []


def _weeks(text, current_week=None):
    value = _clean(text)
    # A single 周 suffix may apply to several comma-separated ranges, as in
    # NJUST's "4-6、8-15周" notation.
    blocks = re.findall(
        r"((?:\d{1,2}\s*(?:[-~～—–至]\s*\d{1,2})?\s*[、,，]?\s*)+)周",
        value,
    )
    matches = []
    for block in blocks:
        matches.extend(re.findall(r"(\d{1,2})(?:\s*[-~～—–至]\s*(\d{1,2}))?", block))
    if not matches:
        return [current_week] if current_week is not None else []
    weeks = set()
    for begin, end in matches:
        first, last = int(begin), int(end or begin)
        if not 1 <= first <= last <= 40:
            raise ScheduleError("网页包含不合法的教学周范围")
        weeks.update(range(first, last + 1))
    if "单周" in value or "单数周" in value or re.search(r"[（(]单[）)]", value):
        weeks = {week for week in weeks if week % 2}
    if "双周" in value or "双数周" in value or re.search(r"[（(]双[）)]", value):
        weeks = {week for week in weeks if not week % 2}
    return sorted(weeks)


def _sections(text):
    match = PERIOD_RE.search(text)
    if not match:
        # Row headers may be simply '1-2' or '3' instead of '第1-2节'.
        match = re.fullmatch(r"\s*(\d{1,2})(?:\s*[-~～—–]\s*(\d{1,2}))?\s*", text)
    if not match:
        return None
    first, last = int(match[1]), int(match[2] or match[1])
    if not 1 <= first <= last <= 30:
        raise ScheduleError("网页中的节次不合法")
    return first, last


def _clock_range(text, section_range, period_times):
    match = TIME_RE.search(text)
    if match:
        return f"{int(match[1]):02d}:{match[2]}", f"{int(match[3]):02d}:{match[4]}"
    if section_range:
        first, last = section_range
        if first in period_times and last in period_times:
            return period_times[first][0], period_times[last][1]
    raise ScheduleError("网页未给出具体钟点时间；请在渠道配置中填写每节课的起止时间")


def _cell_lines(cell):
    fragment = BeautifulSoup(str(cell), "html.parser")
    for br in fragment.find_all("br"):
        br.replace_with("\n")
    return [_clean(line) for line in fragment.get_text("\n").splitlines() if _clean(line)]


def _course_details(cell):
    lines = _cell_lines(cell)
    if not lines or all(x in ("-", "—", "无", "空", "&nbsp;") for x in lines):
        return "", "", "", ""
    raw = " ".join(lines)
    # NJUST renders one compact string, for example:
    # 课程名｛4-6、8-15周[教师:张三,地点:III-116]｝
    title = re.split(r"[｛{]", lines[0], maxsplit=1)[0].strip()
    teacher, location = "", ""
    teacher_inline = re.search(r"(?:任课|授课)?(?:教师|老师)\s*[:：]\s*([^,，\]】}｝]+)", raw)
    place_inline = re.search(r"(?:地点|教室|上课地点)\s*[:：]\s*([^,，\]】}｝]+)", raw)
    if teacher_inline:
        teacher = teacher_inline[1].strip()
    if place_inline:
        location = place_inline[1].strip()
    for line in lines[1:]:
        teacher_match = re.match(r"^(?:任课|授课)?(?:教师|老师)[:：]\s*(.*)$", line)
        place_match = re.match(r"^(?:地点|教室|上课地点)[:：]\s*(.*)$", line)
        if teacher_match:
            teacher = teacher_match[1]
        elif place_match:
            location = place_match[1]
    return _clean(title), _clean(teacher), _clean(location), raw


def _day(first_monday, week_dates, week, weekday):
    monday = week_dates.get(week)
    if monday is None and first_monday:
        monday = first_monday + timedelta(weeks=week - 1)
    if monday is None:
        raise ScheduleError("教学日历未能解析出周次对应日期；请填写学期第一周周一")
    return monday + timedelta(days=weekday)


def _event(day, title, begin, finish, location="", teacher=""):
    try:
        start = datetime.fromisoformat(f"{day.isoformat()}T{begin}")
        end = datetime.fromisoformat(f"{day.isoformat()}T{finish}")
    except ValueError:
        raise ScheduleError("网页上课时间格式不合法") from None
    if end <= start:
        raise ScheduleError("课程结束时间必须晚于开始时间")
    # Stable event IDs preserve ICS UIDs if a teacher or room is changed.
    key = f"{day}|{begin}|{finish}|{title}"
    return {
        "id": "njust-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24],
        "title": title,
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
        "timezone": "Asia/Shanghai",
        "location": location,
        "description": f"任课教师：{teacher}" if teacher else "",
        "categories": "课程",
    }


def _merge_adjacent(events):
    """Join adjacent cells that describe one uninterrupted class session.

    NJUST may render periods 1–2 and period 3 as separate table cells even
    when the course, teacher and room are identical.  A normal class break is
    at most 20 minutes, so those cells should produce one calendar event.
    """
    ordered = sorted(events, key=lambda item: (item["start"], item["end"], item["title"]))
    merged = []
    for item in ordered:
        if merged:
            previous = merged[-1]
            start = datetime.fromisoformat(item["start"])
            previous_end = datetime.fromisoformat(previous["end"])
            same_session = all(previous.get(key, "") == item.get(key, "") for key in (
                "title", "timezone", "location", "description", "categories"
            ))
            if (same_session and start.date() == previous_end.date()
                    and timedelta(0) <= start - previous_end <= timedelta(minutes=20)):
                finish = max(previous_end, datetime.fromisoformat(item["end"]))
                previous["end"] = finish.isoformat(timespec="minutes")
                key = f'{start.date()}|{previous["start"][11:16]}|{finish.strftime("%H:%M")}|{previous["title"]}'
                previous["id"] = "njust-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
                continue
        merged.append(dict(item))
    return merged


def _parse_list(soup, first_monday, week_dates, current_week, period_times):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for i, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            header = [_clean(c.get_text(" ")) for c in cells]
            mapped = {}
            for j, label in enumerate(header):
                compact = re.sub(r"[\s:：()（）]", "", label)
                for field, candidates in COLUMN_NAMES.items():
                    if compact in candidates and field not in mapped:
                        mapped[field] = j
            if not ("title" in mapped and ("weekday" in mapped or "date" in mapped)
                    and ("sections" in mapped or "time" in mapped)):
                continue
            events = []
            for item in rows[i + 1:]:
                columns = [_clean(c.get_text(" ", strip=True))
                           for c in item.find_all(["th", "td"], recursive=False)]
                if len(columns) <= max(mapped.values()):
                    continue
                def get(name):
                    return columns[mapped[name]] if name in mapped else ""
                title = get("title")
                if not title or title in ("合计", "无课程", "暂无数据"):
                    continue
                if get("date"):
                    try:
                        dates = [date.fromisoformat(get("date").replace("/", "-"))]
                    except ValueError:
                        raise ScheduleError("课程表中含有无法识别的上课日期") from None
                else:
                    weekdays = _weekdays(get("weekday"))
                    if not weekdays:
                        raise ScheduleError("课程表中含有无法识别的上课星期")
                    weeks = _weeks(get("weeks"), current_week)
                    if not weeks:
                        raise ScheduleError("无法识别课程对应的教学周；请确认是否为完整课表")
                    if current_week is not None:
                        weeks = [week for week in weeks if week == current_week]
                    dates = [_day(first_monday, week_dates, week, weekday)
                             for week in weeks for weekday in weekdays]
                section = _sections(get("sections") + " " + get("time"))
                times = _clock_range(get("time") + " " + get("sections"), section, period_times)
                events += [_event(day, title, *times, get("location"), get("teacher")) for day in dates]
            return events, True
    return [], False


def _grid_rows(rows, start, max_col):
    active = {}
    for row in rows[start:]:
        children = row.find_all(["th", "td"], recursive=False)
        expanded, col, child_idx = {}, 0, 0
        while col <= max_col:
            if col in active:
                tag, remain = active[col]
                expanded[col] = tag
                if remain <= 1:
                    del active[col]
                else:
                    active[col] = (tag, remain - 1)
                col += 1
                continue
            if child_idx >= len(children):
                col += 1
                continue
            tag = children[child_idx]
            child_idx += 1
            try:
                colspan, rowspan = max(1, int(tag.get("colspan", 1))), max(1, int(tag.get("rowspan", 1)))
            except ValueError:
                raise ScheduleError("课表的合并单元格格式不合法") from None
            for offset in range(colspan):
                target = col + offset
                if target <= max_col:
                    expanded[target] = tag
                    if rowspan > 1:
                        active[target] = (tag, rowspan - 1)
            col += colspan
        yield expanded


def _parse_grid(soup, first_monday, week_dates, current_week, period_times):
    recognized = False
    events = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_idx, section_col, col_days = None, None, {}
        for i, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            labels = [_clean(c.get_text(" ")) for c in cells]
            days = {j: _weekday(_clean(c.get_text(" "))) for j, c in enumerate(cells)}
            days = {j: d for j, d in days.items() if d is not None}
            if len(set(days.values())) >= 3:
                section_col = next((j for j, label in enumerate(labels)
                                    if re.sub(r"\s+", "", label) in ("节次", "节数")), None)
                if section_col is None:
                    continue
                header_idx, col_days = i, days
                break
        if header_idx is None:
            continue
        recognized = True
        # Group rowspan cells: a class spanning periods 1 and 2 must be one
        # continuous VEVENT, not two separate overlapping calendar items.
        groups = {}
        for expanded in _grid_rows(rows, header_idx + 1, max(col_days)):
            section_cell = expanded.get(section_col)
            period_label = _clean(section_cell.get_text(" ")) if section_cell else ""
            section = _sections(period_label)
            if not section:
                continue
            for col, weekday in col_days.items():
                cell = expanded.get(col)
                if cell is None or cell is section_cell:
                    continue
                title, teacher, place, details = _course_details(cell)
                if not title or title.startswith(("星期", "节次", "第几")):
                    continue
                weeks = _weeks(details, current_week)
                if current_week is not None:
                    weeks = [week for week in weeks if week == current_week]
                if not weeks:
                    raise ScheduleError("表格式课表缺少教学周信息，且未找到可切换的教学周控件")
                begin, end = _clock_range(period_label + " " + details, section, period_times)
                for week in weeks:
                    day = _day(first_monday, week_dates, week, weekday)
                    key = (id(cell), weekday, week)
                    if key in groups:
                        item = groups[key]
                        item["begin"] = min(item["begin"], begin)
                        item["end"] = max(item["end"], end)
                    else:
                        groups[key] = {"day": day, "title": title, "begin": begin,
                                       "end": end, "place": place, "teacher": teacher}
        for item in groups.values():
            events.append(_event(item["day"], item["title"], item["begin"], item["end"],
                                 item["place"], item["teacher"]))
    return events, recognized


def parse_timetable(html, first_monday=None, current_week=None, period_times=None, week_dates=None):
    """Parse a captured HTML page into events; unrecognized pages raise."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("input", attrs={"type": "password"}) or (
        re.search(r"(?:统一身份认证|用户登录|请先登录)", _clean(soup.get_text(" ")))
        and not soup.find("select", attrs={"name": re.compile("weeks", re.IGNORECASE)})):
        raise ScheduleError("教务系统会话可能已失效，请在本机更新 Cookie")
    first = _date(first_monday) if isinstance(first_monday, str) and first_monday else first_monday
    mapped = week_dates or {}
    events, found = _parse_list(soup, first, mapped, current_week, period_times or {})
    if not found:
        events, found = _parse_grid(soup, first, mapped, current_week, period_times or {})
    if not found:
        raise ScheduleError("无法识别教务网页课程表格；请提供脱敏 HTML 用于适配，勿包含 Cookie")
    return _merge_adjacent(events)


def _chinese_number(value):
    if value.isdigit():
        return int(value)
    value = value.replace("〇", "零")
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if "十" in value:
        tens, ones = value.split("十", 1)
        return (digits.get(tens, 1) if tens else 1) * 10 + (digits.get(ones, 0) if ones else 0)
    return digits.get(value)


def _candidate_calendar_rows(soup):
    for row in soup.find_all("tr"):
        yield _clean(row.get_text(" ", strip=True))
    # Include simple paragraphs for sites that do not use a table.
    for element in soup.find_all(["p", "li", "div"]):
        if not element.find(["table", "tr", "p", "li", "div"]):
            yield _clean(element.get_text(" ", strip=True))


def parse_term_calendar(html):
    """Extract {week_number: Monday} from explicit week/date rows.

    This intentionally does NOT guess a term start from generic month grids,
    weekends or arbitrary dates in the teaching-calendar header.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = _clean(soup.get_text(" ", strip=True))
    if soup.find("input", attrs={"type": "password"}) or "统一身份认证" in text:
        raise ScheduleError("教学日历页面要求重新登录")
    mapping = {}

    # The current NJUST teaching calendar is a compact month grid.  Its rows
    # contain Chinese week numbers (without the 周 suffix) and cells such as
    # "24 (8月)"; the only year information is in "2026-2027秋学期".
    academic_year = re.search(r"(20\d{2})\s*[-—–至]\s*(20\d{2})\s*(?:年)?\s*[春秋]?学期", text)
    if academic_year:
        first_year, second_year = int(academic_year[1]), int(academic_year[2])
        month_day = re.compile(r"(?<!\d)(3[01]|[12]\d|0?[1-9])\s*[（(]\s*"
                               r"(1[0-2]|0?[1-9])\s*月\s*[）)]")
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [_clean(cell.get_text(" ")) for cell in rows[0].find_all(["th", "td"], recursive=False)]
            if not headers or headers[0] != "周次" or sum("星期" in value for value in headers) < 5:
                continue
            for row in rows[1:]:
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) < 8:
                    continue
                number = _chinese_number(_clean(cells[0].get_text(" ")))
                if number is None or not 1 <= number <= 40:
                    continue
                days = []
                for cell in cells[1:8]:
                    matched = month_day.search(_clean(cell.get_text(" ")))
                    if not matched:
                        days = []
                        break
                    day, month = int(matched[1]), int(matched[2])
                    # Chinese university autumn terms cross New Year.  Months
                    # Aug-Dec use the first academic year; Jan-Jul the second.
                    year = first_year if month >= 8 else second_year
                    try:
                        days.append(date(year, month, day))
                    except ValueError:
                        raise ScheduleError("教学日历包含无法识别的日期") from None
                if len(days) == 7 and all(days[i] + timedelta(days=1) == days[i + 1] for i in range(6)):
                    mapping[number] = days[0]
            if mapping:
                return mapping

    for row in _candidate_calendar_rows(soup):
        matches = list(WEEK_LABEL_RE.finditer(row))
        dates = list(DATE_RE.finditer(row))
        if len(matches) != 1 or not dates:
            continue
        number = _chinese_number(matches[0][1])
        if number is None or not 1 <= number <= 40:
            continue
        # Require a full year on the date, so e.g. 9月1日 is not
        # silently interpreted in the wrong academic year.
        year = next((int(m[1]) for m in dates if m[1]), None)
        if year is None:
            continue
        parsed_dates = []
        inferred_year, previous_month = year, None
        for m in dates:
            month = int(m[2])
            if m[1]:
                inferred_year = int(m[1])
            elif previous_month == 12 and month == 1:
                # The second end date of a Dec-Jan teaching week may omit its year.
                inferred_year += 1
            try:
                parsed_dates.append(date(inferred_year, month, int(m[3])))
            except ValueError:
                raise ScheduleError("教学日历包含无法识别的日期") from None
            previous_month = month
        start = min(parsed_dates)
        monday = start - timedelta(days=start.weekday())
        # For a week range, every date must be no more than 6 days after Monday.
        if any(not 0 <= (day - monday).days <= 6 for day in parsed_dates):
            continue
        if number in mapping and mapping[number] != monday:
            raise ScheduleError("教学日历内同一教学周对应多个日期，请手动填写首周周一")
        mapping[number] = monday
    return mapping


def _week_selector(soup):
    for select in soup.find_all("select"):
        name = select.get("name") or select.get("id", "")
        if "dropdownlistweeks" not in name.lower():
            continue
        weeks = {}
        for option in select.find_all("option"):
            value, label = option.get("value", ""), _clean(option.get_text(" "))
            match = re.search(r"(?<!\d)([1-9]|[12]\d|3\d|40)(?!\d)", label)
            if match:
                week = int(match.group(1))
            elif re.fullmatch(r"\d{1,2}", value):
                week = int(value)
            else:
                named = WEEK_LABEL_RE.search(label)
                week = _chinese_number(named[1]) if named else None
            if week is not None and 1 <= week <= 40 and value:
                weeks[week] = value
        selected = next((o for o in select.find_all("option") if o.has_attr("selected")), None)
        current = next((w for w, value in weeks.items() if selected and value == selected.get("value")), None)
        return name, weeks, current
    return None, {}, None


def _webform_payload(soup, selector_name, value):
    form = soup.find("form")
    if form is None:
        raise ScheduleError("未找到 ASP.NET 表单，无法切换教学周")
    fields = {}
    for element in form.find_all("input"):
        name, kind = element.get("name"), (element.get("type") or "text").lower()
        if not name or kind in ("submit", "button", "image", "file", "reset", "password"):
            continue
        if kind in ("checkbox", "radio") and not element.has_attr("checked"):
            continue
        fields[name] = element.get("value", "")
    for element in form.find_all("select"):
        name = element.get("name")
        if name:
            selected = element.find("option", selected=True) or element.find("option")
            fields[name] = selected.get("value", "") if selected else ""
    for element in form.find_all("textarea"):
        if element.get("name"):
            fields[element["name"]] = element.get_text()
    fields[selector_name] = value
    fields["__EVENTTARGET"] = selector_name
    fields["__EVENTARGUMENT"] = ""
    return fields, form.get("action") or ""


def discover_term_calendar(course_html, course_url):
    """Resolve the TermCalender.aspx entry within course HTML (link, iframe, JS)."""
    soup = BeautifulSoup(course_html, "html.parser")
    candidate_urls = []
    # Plain anchors, iframe/frame sources and form buttons using data attributes.
    for element in soup.find_all(True):
        for attr in ("href", "src", "data-url", "data-href", "onclick"):
            value = element.get(attr)
            if isinstance(value, str) and "TermCalender.aspx".lower() in value.lower():
                candidate_urls.append(value)
    # ASP.NET pages often open the academic calendar with window.open(...)
    # inside a <script> rather than exposing a normal hyperlink.
    candidate_urls.append(course_html)
    pattern = re.compile(
        r"(?P<path>(?:https?://[^\s'\"<>]+)?(?:/|\.\./)*"
        r"(?:PublicPage/)?TermCalender\.aspx(?:\?[^\s'\"<>\)]+)?)",
        re.IGNORECASE,
    )
    for candidate in candidate_urls:
        candidate = unescape(candidate.replace("\\/", "/"))
        # Direct link may begin from a relative path; every result is validated.
        for match in pattern.finditer(candidate):
            path = match.group("path").rstrip(";, ")
            resolved = urljoin(course_url, path)
            try:
                return _safe_url(resolved, TERM_PATH)
            except ScheduleError:
                continue
    return None


def discover_period_times(course_html):
    """Learn section times only if explicitly printed in course-page markup."""
    soup = BeautifulSoup(course_html, "html.parser")
    times = {}
    # Scan the complete visible text first.  NJUST puts all periods of a
    # morning/afternoon/evening block in one table cell.
    for match in PERIOD_CLOCK_RE.finditer(_clean(soup.get_text(" "))):
        section = int(match[1])
        times[section] = (f"{int(match[2]):02d}:{match[3]}",
                          f"{int(match[4]):02d}:{match[5]}")
    for line in soup.get_text("\n").splitlines():
        section = _sections(_clean(line))
        clock = TIME_RE.search(line)
        if section and clock and section[0] == section[1]:
            times[section[0]] = (f"{int(clock[1]):02d}:{clock[2]}",
                                 f"{int(clock[3]):02d}:{clock[4]}")
    for row in soup.find_all("tr"):
        cells = [_clean(cell.get_text(" ")) for cell in row.find_all(["th", "td"], recursive=False)]
        if len(cells) >= 2:
            section = _sections(cells[0])
            clock = TIME_RE.search(" ".join(cells[1:]))
            if section and clock and section[0] == section[1]:
                times[section[0]] = (f"{int(clock[1]):02d}:{clock[2]}",
                                     f"{int(clock[3]):02d}:{clock[4]}")
    return times


def _safe_url(url, path):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or (parsed.hostname or "").lower() != HOST
                or parsed.path.lower() != path.lower() or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ScheduleError("URL 必须为南理工研究生教务系统的指定 HTTPS 页面")
    except ValueError:
        raise ScheduleError("教务系统 URL 格式不正确") from None
    return url


def _fetch(session, method, url, path, **kwargs):
    _safe_url(url, path)
    response = None
    try:
        response = session.request(method, url, timeout=(8, 25), allow_redirects=False,
                                   **kwargs)
        if response.status_code in (301, 302, 303, 307, 308, 401, 403):
            raise ScheduleError("教务系统访问被重定向或拒绝，请重新登录并更新会话")
        if response.status_code != 200:
            raise ScheduleError(f"教务系统返回 HTTP {response.status_code}")
        if len(response.content) > MAX_HTML_BYTES:
            raise ScheduleError("网页内容过大，已停止抓取")
        return response.text
    except requests.RequestsError:
        raise ScheduleError("网页请求失败，请检查校园网连接和本地会话是否有效") from None
    finally:
        if response is not None:
            response.close()


class NJUSTGraduateWebSource(CalendarSource):
    id = "njust_graduate_web"
    title = "南理工课表"
    description = "粘贴课表网址和刚刷新的主文档请求头，一键解析并导入课程；教学日历会从课表网页自动寻找。"
    fields = [
        {"name": "course_url", "label": "课表 URL", "type": "text", "required": True,
         "placeholder": "https://gsmis.njust.edu.cn/Gstudent/Course/StuCourseQuery.aspx?...",
         "help": "从浏览器地址栏复制当前课表页面的完整网址；仅用于本次解析，不保存。",
         "transient": True},
        {"name": "cookie", "label": "Cookie 或完整请求头", "type": "password", "required": True,
         "placeholder": "可粘贴 Cookie 值，也可粘贴以 GET 开头的完整请求头",
         "help": "会提取 Cookie 与必要的浏览器请求头，用于本次请求南京理工大学教务系统；不会写入配置、日志或 ICS。",
         "transient": True},
        {"name": "reminders", "label": "整体提醒（分钟，逗号分隔）", "type": "text",
         "placeholder": "例如：30；留空不提醒",
         "help": "应用于本次同步导入的全部课程；填写 0 表示上课时提醒，最多 5 个时间。"},
    ]

    def collect(self, config, records):
        reminders = _reminders(config.get("reminders", ""))
        course_url = (config.get("course_url") or "").strip()
        supplied_cookie = (config.get("cookie") or "").strip()
        raw_cookie, copied_headers = _request_profile(supplied_cookie)
        if not course_url or not raw_cookie:
            raise ScheduleError("请输入课表 URL 和 Cookie 后点击解析课表")
        if len(course_url) > 4096 or len(supplied_cookie) > 32000 or len(raw_cookie) > 16000:
            raise ScheduleError("URL 或 Cookie 长度/格式不正确")
        _safe_url(course_url, COURSE_PATH)
        jar = SimpleCookie()
        try:
            jar.load(raw_cookie)
        except Exception:
            raise ScheduleError("Cookie 格式不正确") from None
        if not jar:
            raise ScheduleError("Cookie 格式不正确")
        # Honor the machine's proxy settings so the request uses the same
        # egress path as Chrome.  NJUST's protection may bind FSS cookies to
        # both the browser fingerprint and source network.  HTTPS still keeps
        # the Cookie encrypted between this process and gsmis.njust.edu.cn.
        session = requests.Session(impersonate="chrome", trust_env=True)
        # The site's bot/session middleware binds its FSS cookies to the
        # browser request profile.  A custom scraper User-Agent produces HTTP
        # 412 even while the same cookies still work in Chrome.
        request_headers = {
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/155.0.0.0 Safari/537.36"),
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,image/apng,*/*;q=0.8"),
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
        if copied_headers:
            # A normal reload and a forced refresh can use different cache
            # headers.  Do not retain our defaults when the browser omitted
            # them; some session middleware includes this profile in its
            # anti-replay checks.
            request_headers.pop("Cache-Control", None)
            request_headers.pop("Pragma", None)
            request_headers.update(copied_headers)
        session.headers.update(request_headers)
        for key, morsel in jar.items():
            session.cookies.set(key, morsel.value, domain=HOST, path="/", secure=True)
        try:
            html = _fetch(session, "GET", course_url, COURSE_PATH)
            calendar_url = discover_term_calendar(html, course_url)
            week_dates = {}
            if calendar_url:
                week_dates = parse_term_calendar(_fetch(session, "GET", calendar_url, TERM_PATH))
            first = None
            if week_dates:
                week, monday = min(week_dates.items())
                first = monday - timedelta(weeks=week - 1)
            period_times = discover_period_times(html)
            select_name, weeks, selected = _week_selector(BeautifulSoup(html, "html.parser"))
            pages = [(selected, html)] if weeks and selected in weeks else []
            if weeks:
                current_html = html
                for week, option_value in sorted(weeks.items()):
                    if week == selected:
                        continue
                    fields, action = _webform_payload(BeautifulSoup(current_html, "html.parser"),
                                                      select_name, option_value)
                    post_url = _safe_url(urljoin(course_url, action), COURSE_PATH)
                    current_html = _fetch(session, "POST", post_url, COURSE_PATH, data=fields,
                                          headers={"Referer": course_url})
                    _, returned_weeks, returned_selected = _week_selector(BeautifulSoup(current_html, "html.parser"))
                    if returned_weeks and returned_selected is not None and returned_selected != week:
                        raise ScheduleError("教务系统未切换至请求的教学周，请核查页面或会话")
                    period_times.update(discover_period_times(current_html))
                    pages.append((week, current_html))
            else:
                pages = [(None, html)]
            events = {}
            for week, page in pages:
                try:
                    page_events = parse_timetable(page, first, week, period_times, week_dates)
                except ScheduleError as exc:
                    if str(exc).startswith("教学日历未能解析出周次对应日期"):
                        raise ScheduleError("无法从课表内的教学日历自动确定学期日期，请提供脱敏后的校历 HTML 以适配") from None
                    raise
                for event in page_events:
                    previous = events.get(event["id"])
                    if previous is not None and previous != event:
                        raise ScheduleError("同一课程存在冲突的时间或地点信息，请核查课表")
                    events[event["id"]] = event
            if not events:
                raise ScheduleError("未解析到任何课程，为避免删除现有课程，本次同步已取消")
            for event in events.values():
                event["reminders"] = reminders
            return sorted(events.values(), key=lambda e: (e["start"], e["title"]))
        finally:
            session.close()
