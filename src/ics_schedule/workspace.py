"""Independent subscription projects and publication metadata."""
import copy
import json
import re
import subprocess
from datetime import datetime, timezone
from threading import RLock
from pathlib import Path
from uuid import uuid4
from .models import ValidationError
from .publishing import GitHubPublisher, PublishError, destination, digest, validate_settings
from .service import CalendarService, atomic_write


class WorkspaceService:
    def __init__(self, root, sources, publisher=None):
        self.root = Path(root)
        self.sources = sources
        self.lock = RLock()
        self.publisher = publisher or GitHubPublisher()
        self.path = self.root / 'data/projects.json'
        self.suggestion = self.repository_suggestion()
        if self.path.exists():
            self.projects = json.loads(self.path.read_text())
        else:
            self.projects = [self.new_record('默认订阅', 'default')]
            legacy = self.root / 'data/calendar.json'
            if legacy.exists():
                # Keep the original untouched as a migration backup, preserving existing UIDs.
                atomic_write(self.root / 'data/projects/default.json', legacy.read_bytes())
            self.persist()
        self.calendars = {p['id']: CalendarService(self.root, sources, p['id'], p['name']) for p in self.projects}

    def repository_suggestion(self):
        try:
            result = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=self.root, capture_output=True, text=True, timeout=5)
            match = re.fullmatch(r'(?:git@github.com:|https://github.com/)([\w.-]+/[\w.-]+?)(?:\.git)?\s*', result.stdout)
            return match.group(1) if match else ''
        except (OSError, subprocess.TimeoutExpired):
            return ''

    def new_record(self, name, project_id):
        return {'id': project_id, 'name': name, 'publication': {'repository': self.suggestion, 'branch': 'main', 'path': f'subscription/{project_id}.ics', 'transport': 'ssh'},
                'published': None, 'history': [], 'reserved': [], 'last_error': ''}

    def persist(self):
        atomic_write(self.path, json.dumps(self.projects, ensure_ascii=False, indent=2).encode())

    def project(self, project_id):
        for project in self.projects:
            if project['id'] == project_id:
                return project
        raise KeyError(project_id)

    def calendar(self, project_id):
        return self.calendars[project_id]

    def snapshot(self, project_id=None):
        with self.lock:
            project_id = project_id or self.projects[0]['id']
            calendar = self.calendar(project_id)
            result = calendar.snapshot()
            summaries = []
            for project in self.projects:
                item = copy.deepcopy(project)
                published = project['published']
                same_target = published and destination(published['settings']) == destination(project['publication'])
                content = (self.root / 'subscription' / (project['id'] + '.ics')).read_bytes()
                item['subscription_url'] = published['url'] if same_target else None
                item['status'] = 'unpublished' if not same_target else ('published' if digest(content) == published['digest'] else 'changed')
                item.pop('history', None)
                item.pop('reserved', None)
                summaries.append(item)
            result.update(projects=summaries, current_project=project_id)
            return result

    def create(self, payload):
        with self.lock:
            name = self.validate_name(payload.get('name'))
            project = self.new_record(name, uuid4().hex)
            calendar = CalendarService(self.root, self.sources, project['id'], name)
            self.projects.append(project)
            self.calendars[project['id']] = calendar
            self.persist()
            return {'id': project['id']}

    @staticmethod
    def validate_name(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise ValidationError('项目名称须为 1–100 个字符')
        return value.strip()

    def configure(self, project_id, payload):
        with self.lock:
            project = self.project(project_id)
            name = self.validate_name(payload.get('name', project['name']))
            settings = validate_settings(payload.get('publication', project['publication']))
            target = destination(settings)
            for other in self.projects:
                if other['id'] != project_id:
                    occupied = [destination(other['publication']), *[tuple(x) for x in other.get('reserved', [])]]
                    if target in occupied:
                        raise ValidationError('此仓库、分支和文件路径已由另一订阅项目使用，请更换路径')
            project.update(name=name, publication=settings, last_error='')
            calendar = self.calendar(project_id)
            calendar.name = name
            calendar.publish(calendar.state)
            self.persist()
            return {'ok': True}

    def publish_project(self, project_id):
        with self.lock:
            project = self.project(project_id)
            settings = validate_settings(project['publication'])
            target = destination(settings)
            previous = next((p for p in reversed(project.get('history', [])) if destination(p['settings']) == target), None)
            content = (self.root / 'subscription' / (project_id + '.ics')).read_bytes()
            # Reserve before network activity, including uncertain push outcomes.
            if list(target) not in project['reserved']:
                project['reserved'].append(list(target))
            self.persist()
            try:
                published = self.publisher.publish(settings, content, previous)
            except PublishError as exc:
                project['last_error'] = str(exc)
                self.persist()
                raise
            published['at'] = datetime.now(timezone.utc).isoformat()
            project['published'] = published
            project['history'] = [p for p in project['history'] if destination(p['settings']) != target] + [published]
            project['last_error'] = ''
            self.persist()
            return {'ok': True, 'url': published['url'], 'commit': published['commit']}
