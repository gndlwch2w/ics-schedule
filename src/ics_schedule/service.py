"""Atomic persistence, source refreshes and deterministic subscription snapshots."""
import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4, uuid5, NAMESPACE_URL
from .calendar import serialize
from .models import ValidationError, validate_event


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CalendarService:
    def __init__(self, root, sources, project_id=None, name="汇总日历"):
        self.root = Path(root)
        self.sources = sources
        self.project_id = project_id
        self.name = name
        self.lock = RLock()
        self.path = self.root / "data" / "projects" / (project_id + ".json") if project_id else self.root / "data/calendar.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"events": [], "configs": {}, "updated": None}
        self.publish(self.state)

    def publish(self, state):
        records = [e for e in state["events"] if e["source"] in self.sources]
        if self.project_id:
            atomic_write(self.root / "subscription" / (self.project_id + ".ics"), serialize(records, self.name))
            return
        files = {"all": serialize(records)}
        for key, source in self.sources.items():
            files[key] = serialize([e for e in records if e["source"] == key], source.title)
        for name, content in files.items():
            atomic_write(self.root / "subscription" / (name + ".ics"), content)

    def commit(self, state):
        state["updated"] = datetime.now(timezone.utc).isoformat()
        # Validate/serialize everything before touching persisted data.
        serialize(state["events"])
        atomic_write(self.path, json.dumps(state, ensure_ascii=False, indent=2).encode())
        self.state = state
        self.publish(state)

    def snapshot(self):
        with self.lock:
            return {"events": copy.deepcopy([e for e in self.state["events"] if e["source"] in self.sources]),
                    "sources": [source.ui() for source in self.sources.values()], "updated": self.state["updated"]}

    def decorate(self, payload, source, event_id, old=None):
        record = validate_event(payload)
        now = datetime.now(timezone.utc).isoformat()
        record.update(id=event_id, source=source,
                      uid=old["uid"] if old else str(uuid5(NAMESPACE_URL, (self.project_id or "legacy") + ":" + source + ":" + event_id)) + "@ics-schedule",
                      sequence=old["sequence"] + 1 if old else 0,
                      created=old["created"] if old else now, updated=now)
        return record

    def save(self, payload, event_id=None):
        with self.lock:
            state = copy.deepcopy(self.state)
            old = next((e for e in state["events"] if e["id"] == event_id and e["source"] == "manual"), None)
            if event_id and not old:
                raise KeyError("事件不存在")
            record = self.decorate(payload, "manual", event_id or uuid4().hex, old)
            if old:
                state["events"].remove(old)
            state["events"].append(record)
            self.commit(state)
            return record

    def delete(self, event_id):
        with self.lock:
            state = copy.deepcopy(self.state)
            old = next((e for e in state["events"] if e["id"] == event_id and e["source"] == "manual"), None)
            if not old:
                raise KeyError("事件不存在")
            state["events"].remove(old)
            self.commit(state)

    def refresh(self, source_id, config):
        with self.lock:
            source = self.sources[source_id]
            if source_id == "manual":
                self.publish(self.state)
                return
            if not isinstance(config, dict):
                raise ValidationError("插件配置必须为对象")
            state = copy.deepcopy(self.state)
            config = config or state["configs"].get(source_id, {})
            old = {e["id"]: e for e in state["events"] if e["source"] == source_id}
            records, seen = [], set()
            for raw in source.collect(config, list(old.values())):
                event_id = str(raw.get("id", ""))
                if not event_id or event_id in seen:
                    raise ValidationError("插件事件必须提供唯一且稳定的 id")
                seen.add(event_id)
                normalized = validate_event(raw)
                previous = old.get(event_id)
                if previous and all(previous.get(k) == v for k, v in normalized.items()):
                    records.append(previous)
                else:
                    records.append(self.decorate(raw, source_id, event_id, previous))
            state["events"] = [e for e in state["events"] if e["source"] != source_id] + records
            persistent = source.persistent_config(config)
            if persistent:
                state["configs"][source_id] = persistent
            else:
                state["configs"].pop(source_id, None)
            self.commit(state)
