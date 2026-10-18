"""Validated, JSON-serializable event contract shared by every source."""
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ValidationError(ValueError):
    pass


def integer(value, label, low, high):
    try:
        if isinstance(value, bool) or str(int(value)) != str(value):
            raise ValueError()
        result = int(value)
        if not low <= result <= high:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValidationError(f"{label}必须为 {low}–{high} 的整数")


def event_time(value, all_day, tz):
    try:
        if all_day:
            return date.fromisoformat(value)
        local = datetime.fromisoformat(value)
        if local.tzinfo is not None:
            raise ValueError()
        aware = local.replace(tzinfo=ZoneInfo(tz))
        if aware.astimezone(timezone.utc).astimezone(aware.tzinfo).replace(tzinfo=None) != local:
            raise ValidationError("该时间处于夏令时跳变的空缺时段")
        return aware
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"无效日期或时间：{value}") from exc


def validate_event(raw):
    if not isinstance(raw, dict):
        raise ValidationError("事件必须为 JSON 对象")
    result = {}
    for key in ("title", "description", "location", "url", "categories"):
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > 10000:
            raise ValidationError(f"{key} 必须是长度不超过 10000 的文本")
        result[key] = value.strip()
    if not result["title"]:
        raise ValidationError("请填写事件标题")
    if result["url"] and (urlsplit(result["url"]).scheme not in ("http", "https") or not urlsplit(result["url"]).netloc):
        raise ValidationError("链接必须为完整的 http 或 https 地址")
    result["all_day"] = raw.get("all_day", False)
    if not isinstance(result["all_day"], bool):
        raise ValidationError("全天选项必须为布尔值")
    tz = raw.get("timezone", "Asia/Shanghai")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError("请填写有效的 IANA 时区，如 Asia/Shanghai")
    result["timezone"] = tz
    for key in ("start", "end"):
        value = event_time(raw.get(key), result["all_day"], tz)
        result[key] = value.isoformat() if result["all_day"] else value.replace(tzinfo=None).isoformat(timespec="minutes")
    if result["end"] <= result["start"]:
        raise ValidationError("结束时间必须晚于开始时间；全天事件结束日期不包含在内")
    for key, choices, default in (
        ("status", ("CONFIRMED", "TENTATIVE", "CANCELLED"), "CONFIRMED"),
        ("privacy", ("PUBLIC", "PRIVATE", "CONFIDENTIAL"), "PUBLIC"),
        ("availability", ("OPAQUE", "TRANSPARENT"), "OPAQUE"),
        ("frequency", ("", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"), ""),
    ):
        result[key] = raw.get(key, default)
        if result[key] not in choices:
            raise ValidationError(f"无效的 {key}")
    result["interval"] = integer(raw.get("interval", 1), "重复间隔", 1, 365)
    result["count"] = integer(raw["count"], "重复次数", 1, 10000) if raw.get("count") not in (None, "") else None
    result["until"] = raw.get("until") or ""
    if result["until"]:
        until = event_time(result["until"], True, tz)
        if until < date.fromisoformat(result["start"][:10]):
            raise ValidationError("重复截止日不能早于开始日期")
    if result["count"] and result["until"]:
        raise ValidationError("重复次数和截止日期只能设置一个")
    days = raw.get("weekdays", [])
    if not isinstance(days, list) or any(d not in ("MO", "TU", "WE", "TH", "FR", "SA", "SU") for d in days):
        raise ValidationError("无效的重复星期")
    result["weekdays"] = list(dict.fromkeys(days))
    reminders = raw.get("reminders", [])
    if not isinstance(reminders, list) or len(reminders) > 5:
        raise ValidationError("最多设置 5 个提醒")
    result["reminders"] = sorted(set(integer(v, "提前提醒分钟数", 0, 525600) for v in reminders))
    return result
