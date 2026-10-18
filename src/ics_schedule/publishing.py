"""Publish one ICS in an isolated Git checkout; never touch the app checkout/index."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .models import ValidationError


class PublishError(Exception):
    pass


def digest(content):
    return hashlib.sha256(content).hexdigest()


def validate_settings(raw):
    if not isinstance(raw, dict):
        raise ValidationError("发布设置必须是对象")
    settings = {}
    for key in ("repository", "branch", "path", "transport"):
        value = raw.get(key, "ssh" if key == "transport" else "")
        if not isinstance(value, str):
            raise ValidationError("发布设置必须为文本")
        settings[key] = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", settings['repository']):
        raise ValidationError("仓库格式应为 owner/repository")
    settings['repository'] = settings['repository'].removesuffix('.git')
    branch = settings['branch']
    if not branch or branch.startswith('-') or subprocess.run(['git', 'check-ref-format', 'refs/heads/' + branch], capture_output=True).returncode:
        raise ValidationError("请填写有效的现有 Git 分支名称")
    path = settings['path']
    if not path.endswith('.ics') or not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or any(part in ('', '.', '..') or part.startswith('.') for part in path.split('/')):
        raise ValidationError("文件路径须为相对路径并以 .ics 结尾，如 subscription/work.ics；只支持英文、数字、下划线和短横线")
    if settings['transport'] not in ('ssh', 'https'):
        raise ValidationError("请选择 SSH 或 HTTPS")
    return settings


def destination(settings):
    return settings['repository'].lower(), settings['branch'], settings['path']


def raw_url(settings):
    return 'https://raw.githubusercontent.com/' + settings['repository'] + '/refs/heads/' + quote(settings['branch'], safe='/') + '/' + quote(settings['path'], safe='/')


class GitHubPublisher:
    def remote_url(self, settings):
        repo = settings['repository']
        return f'git@github.com:{repo}.git' if settings['transport'] == 'ssh' else f'https://github.com/{repo}.git'

    def check_public(self, settings):
        repository = settings['repository']
        request = Request('https://api.github.com/repos/' + repository, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ics-schedule'})
        try:
            with urlopen(request, timeout=20) as response:
                info = json.load(response)
            if info.get('private', True):
                raise PublishError('订阅需要公开仓库；私有仓库的链接无法供日历客户端匿名访问')
        except HTTPError as exc:
            if exc.code == 403 and exc.headers.get('X-RateLimit-Remaining') == '0':
                self.check_public_page(repository)
            elif exc.code == 404:
                raise PublishError('找不到 GitHub 仓库，请检查仓库名称是否正确且仓库已创建') from exc
            else:
                raise PublishError(f'GitHub API 返回 HTTP {exc.code}，暂时无法确认公开仓库') from exc
        except (URLError, ValueError) as exc:
            raise PublishError('无法确认公开仓库，请检查仓库名称、网络和 GitHub API 访问限制') from exc

    def check_public_page(self, repository):
        request = Request('https://github.com/' + repository, headers={'User-Agent': 'ics-schedule'})
        try:
            with urlopen(request, timeout=20) as response:
                if response.status != 200:
                    raise PublishError(f'GitHub 仓库页面返回 HTTP {response.status}，无法确认公开仓库')
        except HTTPError as exc:
            if exc.code == 404:
                raise PublishError('找不到 GitHub 仓库，或仓库不是公开仓库；请检查仓库名称和可见性') from exc
            raise PublishError(f'GitHub 仓库页面返回 HTTP {exc.code}，无法确认公开仓库') from exc
        except URLError as exc:
            raise PublishError('无法访问 GitHub 仓库页面，请检查网络连接后重试') from exc

    def git(self, args, cwd=None, binary=False):
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never',
                   GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes')
        try:
            result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', *args], cwd=cwd, env=env, capture_output=True, text=not binary, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PublishError('Git 不可用或操作超时，请检查 Git 安装和网络后重试') from exc
        if result.returncode:
            detail = result.stderr.decode(errors='replace').strip() if binary else result.stderr.strip()
            detail = re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1***:***@', detail)
            detail = re.sub(r'\bGIT_[A-Z0-9_]+\b', '[环境变量]', detail)
            detail = detail[:500]
            message = 'Git 操作失败。请检查仓库/分支、SSH 或 HTTPS 凭据及推送权限；若远端刚有更新，请重试。不会强制覆盖远端。'
            if detail:
                message += ' Git 返回：' + detail
            raise PublishError(message)
        return result.stdout if binary else result.stdout.strip()

    def publish(self, settings, content, previous=None):
        settings = validate_settings(settings)
        self.check_public(settings)
        with tempfile.TemporaryDirectory(prefix='ics-publish-') as temporary:
            checkout = Path(temporary) / 'repository'
            self.git(['clone', '--depth', '1', '--single-branch', '--branch', settings['branch'], '--', self.remote_url(settings), str(checkout)])
            target = checkout / settings['path']
            for candidate in [target, *target.parents]:
                if candidate == checkout:
                    break
                if candidate.is_symlink():
                    raise PublishError('发布路径包含符号链接，请更换目标路径')
            if target.exists() and not target.is_file():
                raise PublishError('目标路径不是普通文件')
            existing = self.git(['show', 'HEAD:' + settings['path']], checkout, binary=True) if target.exists() else None
            if existing != content:
                if existing is not None and (not previous or digest(existing) != previous['digest']):
                    raise PublishError('目标文件已存在或被外部修改。为避免覆盖，请使用新的文件路径，或恢复到上次发布版本后重试。')
                if existing is None and previous:
                    raise PublishError('上次发布的远端文件已被删除，请恢复文件或更换发布路径')
                target.parent.mkdir(parents=True, exist_ok=True)
                # Keep RFC 5545 CRLF bytes intact, regardless of repository text filters.
                attributes = checkout / '.git/info/attributes'
                attributes.parent.mkdir(parents=True, exist_ok=True)
                attributes.write_text('* -text -filter -ident -working-tree-encoding\n')
                target.write_bytes(content)
                self.git(['add', '-f', '--', settings['path']], checkout)
                self.git(['-c', 'user.name=Calendar Hub', '-c', 'user.email=calendar-hub@users.noreply.github.com',
                          'commit', '-m', 'Update calendar subscription: ' + settings['path'], '--only', '--', settings['path']], checkout)
                self.git(['push', 'origin', 'HEAD:refs/heads/' + settings['branch']], checkout)
            return {'digest': digest(content), 'commit': self.git(['rev-parse', 'HEAD'], checkout),
                    'settings': settings, 'url': raw_url(settings)}
