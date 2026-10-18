"""A source provides both events and a declarative UI (no frontend patch needed)."""
from abc import ABC, abstractmethod
from importlib import import_module
import re


class CalendarSource(ABC):
    id = ""
    title = ""
    description = ""
    fields = []

    def ui(self):
        return {"id": self.id, "title": self.title, "description": self.description,
                "fields": self.fields, "editable": self.id == "manual"}

    @abstractmethod
    def collect(self, config, records):
        """Return event dicts; external sources MUST include a stable unique `id`."""
        raise NotImplementedError


def load_sources(specs=()):
    from .manual import ManualSource
    sources = [ManualSource()]
    for spec in specs:
        module, name = spec.split(":", 1)
        sources.append(getattr(import_module(module), name)())
    result = {}
    for source in sources:
        if not isinstance(source, CalendarSource) or not re.fullmatch(r"[a-z][a-z0-9_-]*", source.id):
            raise ValueError("插件必须实现 CalendarSource 并提供合法 id")
        if source.id == "all" or source.id in result:
            raise ValueError(f"插件 id 重复：{source.id}")
        for field in source.fields:
            if field.get("type") not in ("text", "number", "date", "textarea", "select", "password", "checkbox"):
                raise ValueError("不支持的插件字段类型")
        result[source.id] = source
    return result
