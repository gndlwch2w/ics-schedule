# 日历汇集 · ics-schedule

**只在本机使用的日历编辑器**。每个项目是一份独立订阅：在网页中编辑、汇总不同渠道的日程，生成 ICS，再发布到 GitHub。日历客户端订阅 GitHub 的原始文件地址，网页不需要部署，本机服务也不需要一直运行。

## 启动

需要 Python 3.9+ 和 Git：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/ics-schedule
```

打开 http://127.0.0.1:8000 。仅允许本机访问。使用 `--port 8080` 更改端口，`--root /path/to/workspace` 指定本地数据和生成文件的父目录（默认启动目录）。一个工作目录只运行一个服务进程。

## 项目 = 独立订阅

1. 点击侧栏“新建订阅”，例如工作日程、课程表、个人安排。
2. 在当前项目中创建或编辑日程，或从插件渠道同步数据。
3. 打开“发布设置”，设置项目名称、GitHub 公开仓库（`owner/repository`）、现有分支及独立的 ICS 路径，例如 `subscription/work.ics`。
4. 保存设置后，点击“发布到 GitHub”。确认当前项目和目标路径后，应用只提交该项目的 ICS 文件。
5. 发布成功后，“复制订阅链接”提供 GitHub 原始文件 URL，例如：
   `https://raw.githubusercontent.com/owner/repository/refs/heads/main/subscription/work.ics`
6. 在日历客户端选择“订阅日历”并粘贴链接。后续修改本地日程，点击“重新发布”，客户端继续使用同一链接。

项目拥有独立的日程、插件配置、本地 ICS、发布设置和发布记录。渠道只用于项目内的数据来源和列表筛选；发布和下载始终包含**当前项目的全部已加载渠道**。

“未发布 / 有更新待发布 / 已发布”区分本地与远端状态。编辑会自动保存本地，但不会自动推送。已发布后若有本地更新，仍可复制原有订阅地址。修改仓库、分支或路径会改变订阅地址，需再次发布并在客户端重新订阅；原文件不会自动删除。

下载 ICS 只导出本地快照，不代表已发布。GitHub 缓存及日历客户端的刷新周期可能使更新稍有延迟。

## GitHub 发布设置与认证

- 仓库须为已存在的**公开 GitHub 仓库**，指定分支也必须存在；首次使用可在 GitHub 创建包含 README 的仓库。
- SSH：使用本机 SSH 密钥和已确认的 GitHub 主机密钥。首次使用请先在终端完成 GitHub SSH 连接配置。
- HTTPS：使用本机已有的 Git credential helper。请先在终端完成认证；网页不收集或保存访问令牌。
- 应用会检查公开仓库是否可匿名访问。网络或 GitHub API 限流可能使发布暂时失败，可稍后重试。
- 首次设置会尝试从本地代码仓库的 GitHub origin 提取仓库建议值；分支默认为 `main`，请按实际情况修改。
- 发布使用临时 Git checkout，仅提交指定 ICS，不使用当前代码仓库的暂存区，不带入源码、JSON 数据或其他工作目录改动。
- 重新发布从目标分支最新版本开始，不强推；相同内容不产生新提交。其他文件会保留。
- 不同项目不能绑定相同的仓库、分支与路径，包括其他项目曾经发布的路径。
- 首次发布发现已有不同内容的文件，或再次发布发现远端文件与上次发布记录不一致，会拒绝覆盖。请换一个未使用的路径，或恢复远端文件后重试。
- 发布失败保留本地数据和上次成功的订阅地址，并显示错误。若网络中断导致推送结果不确定，重试会识别已上传的相同内容。

公开订阅包含项目中的全部事件。“私密／机密”仅是 ICS 属性，不会对公开文件提供访问控制。

## 日程能力

支持标题、描述、地点、时区、全天事件、链接、分类、状态、可见性和忙闲状态。支持按日／周／月／年重复、重复间隔、每周重复日、次数或截止日期，最多五个提前提醒。

全天事件的结束日期**不包含在内**，例如 10 月 19 日单日事件设置开始 19 日、结束 20 日。编辑事件保留 UID 并递增 SEQUENCE；重复事件编辑作用于整个系列，暂不支持只改一次。时间使用 IANA 时区，ICS 包含 VTIMEZONE；不存在的夏令时时间会被拒绝，回拨重叠时间采用第一次出现。

## 本地文件与迁移

```text
src/ics_schedule/
  models.py              # 事件校验
  calendar.py            # ICS 序列化
  service.py             # 单项目日程、渠道与生成文件
  workspace.py           # 项目管理、迁移及发布记录
  publishing.py          # 隔离的 GitHub 提交与推送
  server.py              # 本机 HTTP API
  plugins/               # 渠道协议及手动渠道
  static/                # 统一网页和基础组件样式
src/tests/               # 事件、API、项目隔离及 Git 发布测试
data/projects.json       # 项目索引、发布设置与结果
data/projects/<id>.json  # 各项目独立事件和插件配置
subscription/<id>.ics    # 各项目独立生成文件
```

本地数据和生成文件默认不提交到代码仓库；发布器会将指定的单个 ICS 提交到目标仓库，即使那里有 ICS 忽略规则。请备份完整 `data/`，其中的发布记录用于识别远端冲突。

从旧版本启动时，原有 `data/calendar.json` 自动复制到“默认订阅”，保留原 UID 和渠道配置；旧 JSON 不修改，作为迁移备份。旧的 `all.ics` 和按渠道生成的文件不再通过编辑器提供下载，也不会发布到 GitHub。未加载的渠道数据仍保留在项目 JSON 中，但不会包含在本次生成与发布的 ICS 中。

## 扩展渠道

继承 `CalendarSource`，同时提供 `collect(config, records)` 数据采集方法与 `fields` UI 字段描述。主界面自动生成渠道入口、配置表单和列表筛选；同一个插件在不同项目中的配置和数据相互隔离。

例如创建 `src/ics_schedule/plugins/example.py`：

```python
from . import CalendarSource

class ExampleSource(CalendarSource):
    id = "example"
    title = "示例渠道"
    description = "通过统一接口提供数据与配置界面"
    fields = [{"name": "title", "label": "日程标题", "type": "text",
               "required": True, "default": "团队会议"}]

    def collect(self, config, records):
        return [{"id": "meeting-001", "title": config["title"],
                 "start": "2026-10-20T09:00", "end": "2026-10-20T10:00",
                 "timezone": "Asia/Shanghai"}]
```

```sh
.venv/bin/ics-schedule --plugin ics_schedule.plugins.example:ExampleSource
```

可重复传入 `--plugin MODULE:CLASS`。插件是受信任的本地 Python 代码。id 应以小写字母开头，仅包含小写字母、数字、下划线和短横线，不能与 `all/manual` 或其他插件重复。

支持表单字段：`text/password/number/date/textarea/select/checkbox`；可选 `default/required/placeholder/help`，下拉选项格式为 `options: [{"value": "...", "label": "..."}]`。配置业务校验由插件负责，配置仅保存在本机，不通过状态 API 返回。

采集返回当前项目中该渠道的完整快照。事件必须具有来源内稳定且唯一的 `id`；缺失事件被移除，空列表清空当前渠道。采集或校验失败保留原数据；内容未变不增加事件版本。插件日程只读，通过“保存配置并同步”刷新，暂不支持后台定时采集。

事件必填 `title/start/end`，完整字段见 `models.validate_event`。插件的 `records` 参数是当前项目、当前渠道的上一次事件列表。

## API 与测试

- `GET /api/state?project=<id>`：当前项目状态和项目摘要，不传 id 时使用默认项目。
- `POST /api/projects`：`{"name": "项目名称"}` 新建订阅。
- `PUT /api/projects/<id>`：更新 `name` 和 `publication` 设置。
- `POST /api/projects/<id>/publish`：发布当前项目。
- `POST /api/projects/<id>/events`、`PUT/DELETE /api/projects/<id>/events/<event-id>`：操作当前项目的手动事件。
- `POST /api/projects/<id>/sources/<source-id>/refresh`：同步当前项目的渠道；空对象沿用已保存的配置。
- `GET /subscription/<id>.ics`：下载当前项目本地快照。

写入请求使用 `Content-Type: application/json`；发布和删除传 `{}`。

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s src/tests -v
```

发布集成测试使用临时本地 Git 仓库，不向真实 GitHub 推送。ICS 通过 [icalendar](https://icalendar.readthedocs.io/en/6.x/index.html) 序列化。
