from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .agent import PoohAgent


COMMAND_CATALOG = [
    {"name": "/help", "desc": "查看全部命令与用法"},
    {"name": "/tools", "desc": "查看当前可用工具与说明"},
    {"name": "/skills", "desc": "查看当前可用技能与说明"},
    {"name": "/clear", "desc": "清空当前会话"},
    {"name": "/new", "desc": "新建并切换到会话"},
    {"name": "/switch <session_id_prefix>", "desc": "切换到指定会话"},
    {"name": "/compact", "desc": "压缩当前会话上下文"},
    {"name": "/ctx", "desc": "查看当前会话上下文占用"},
    {"name": "/sessions", "desc": "列出历史会话"},
    {"name": "/model [name]", "desc": "查看或切换模型"},
    {"name": "/exit", "desc": "退出当前会话流程"},
]

TOOL_DESCRIPTION_MAP = {
    "bash": "在 workplace 沙箱内执行 Shell 命令，适合运行脚本、查看状态和做本地验证。",
    "read_file": "读取文件内容，可用于查看代码、配置、文档和中间产物。",
    "write_file": "新建或覆盖文件，适合生成脚本、文档、配置和交付文件。",
    "edit_file": "按文本替换修改文件，适合在现有实现上做精确变更。",
    "list_dir": "查看目录结构，快速确认文件和子目录分布。",
    "glob": "按模式查找文件，适合批量定位模块、资源和配置文件。",
    "grep": "使用 ripgrep 搜索仓库内容，适合定位函数、字段和引用关系。",
    "web_fetch": "已知具体 URL 时抓取网页正文，自动去掉导航和广告噪声。",
    "web_search": "联网搜索候选结果，适合快速找资料、新闻或外部说明。",
    "web_search_and_read": "联网搜索并自动抓取正文，适合需要深入阅读的场景。",
    "use_skill": "加载某个 skill 的完整工作流说明，再按该技能流程执行任务。",
    "spawn_agent": "启动受限子代理处理边界清晰的子任务，降低主上下文压力。",
}


@dataclass
class CommandResult:
    handled: bool
    text: str = ""
    session_key: str | None = None


class CommandProcessor:
    def __init__(self, agent: PoohAgent) -> None:
        self.agent = agent

    def _clean_text(self, value: str) -> str:
        text = " ".join(str(value or "").split()).strip()
        return text or "—"

    def _render_table(
        self,
        key: str,
        title: str,
        columns: tuple[str, str],
        rows: list[tuple[str, str]],
        note: str | None = None,
        *,
        default_width: int = 180,
        min_width: int = 128,
        max_width: int = 480,
    ) -> str:
        body_rows = []
        for left, right in rows:
            body_rows.append(
                '<div class="cmd-row">'
                f'<div class="cmd-cell cmd-name" title="{escape(self._clean_text(left))}"><code>{escape(self._clean_text(left))}</code></div>'
                '<div class="cmd-divider-slot" aria-hidden="true"></div>'
                f'<div class="cmd-cell cmd-desc">{escape(self._clean_text(right))}</div>'
                "</div>"
            )
        if not body_rows:
            body_rows.append(
                '<div class="cmd-row">'
                '<div class="cmd-cell cmd-name"><code>—</code></div>'
                '<div class="cmd-divider-slot" aria-hidden="true"></div>'
                '<div class="cmd-cell cmd-desc">当前没有可展示内容</div>'
                "</div>"
            )

        note_html = f'<div class="cmd-note">{escape(note)}</div>' if note else ""
        return (
            '<div class="cmd-panel">'
            f'<div class="cmd-title">{escape(title)}</div>'
            f'<div class="cmd-table" data-resizable="1" data-table-key="{escape(key)}" '
            f'data-min-col="{min_width}" data-max-col="{max_width}" style="--cmd-col-width:{default_width}px;">'
            '<div class="cmd-row cmd-head-row">'
            f'<div class="cmd-cell cmd-head">{escape(columns[0])}</div>'
            '<div class="cmd-divider-slot">'
            '<button class="cmd-divider-handle" type="button" title="左右拖动调整列宽" aria-label="左右拖动调整列宽"></button>'
            "</div>"
            f'<div class="cmd-cell cmd-head">{escape(columns[1])}</div>'
            "</div>" + "".join(body_rows) + "</div>" + note_html + "</div>"
        )

    def handle(self, raw: str, session_key: str) -> CommandResult:
        if not raw.startswith("/"):
            return CommandResult(False)
        parts = raw.strip().split(maxsplit=1)
        command = parts[0]
        argument = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            return CommandResult(
                True,
                self._render_table(
                    "help",
                    "命令总览",
                    ("命令", "说明"),
                    [(item["name"], item["desc"]) for item in COMMAND_CATALOG],
                    default_width=210,
                ),
            )
        if command == "/tools":
            specs = self.agent.tools.specs()
            rows = [
                (
                    spec.get("name", ""),
                    TOOL_DESCRIPTION_MAP.get(
                        spec.get("name", ""), spec.get("description", "") or "—"
                    ),
                )
                for spec in specs
            ]
            return CommandResult(
                True,
                self._render_table(
                    "tools",
                    "工具清单",
                    ("工具", "说明"),
                    rows or [("—", "当前没有可用工具")],
                    default_width=170,
                ),
            )
        if command == "/clear":
            session_id = self.agent.sessions.clear_session(session_key)
            return CommandResult(True, f"cleared session_id={session_id}")
        if command == "/new":
            session_id = self.agent.sessions.new_session(session_key)
            return CommandResult(
                True, f"created and switched to session_id={session_id}"
            )
        if command == "/switch":
            if not argument:
                return CommandResult(True, "usage: /switch <session_id_prefix>")
            try:
                target_session_key, session_id = self.agent.sessions.switch_session(
                    argument
                )
            except ValueError as exc:
                return CommandResult(True, str(exc))
            return CommandResult(
                True,
                f"switched to session_id={session_id}",
                session_key=target_session_key,
            )
        if command == "/compact":
            compacted = self.agent.compact_session(session_key, force=True)
            return CommandResult(
                True, "context compacted" if compacted else "nothing to compact"
            )
        if command == "/ctx":
            usage = self.agent.get_context_usage(session_key)
            session_id = self.agent.sessions.get_session_id(session_key)
            raw_usage = self.agent.sessions.get_last_usage(session_key)
            if isinstance(raw_usage, dict):
                input_tokens = raw_usage.get("input_tokens")
                output_tokens = raw_usage.get("output_tokens")
                total_tokens = raw_usage.get("total_tokens")
                return CommandResult(
                    True,
                    f"session_id={session_id}\n"
                    "终端显示: "
                    f"{usage.display}\n"
                    f"input_tokens={input_tokens}  "
                    f"output_tokens={output_tokens}  "
                    f"total_tokens={total_tokens}\n"
                    f"auto_compact={usage.auto_compact_threshold}  "
                    f"blocking={usage.blocking_limit}",
                )
            return CommandResult(
                True,
                f"session_id={session_id}\n"
                "终端显示: "
                f"{usage.display}\n"
                "input_tokens=unknown  output_tokens=unknown  total_tokens=unknown\n"
                f"auto_compact={usage.auto_compact_threshold}  "
                f"blocking={usage.blocking_limit}",
            )
        if command == "/sessions":
            rows = []
            current_session_id = self.agent.sessions.get_session_id(session_key)
            for item in self.agent.sessions.list_sessions()[:200]:
                marker = "*" if item["session_id"] == current_session_id else " "
                channel = (
                    item["session_key"].split(":")[2]
                    if ":" in item["session_key"]
                    else "unknown"
                )
                rows.append(
                    f"{marker} {item['session_id']}  {channel}  messages={item['message_count']}  last_active={item['last_active']}"
                )
            return CommandResult(True, "\n".join(rows) or "(no sessions)")
        if command == "/skills":
            skills = self.agent.skills.discover()
            rows = [(skill.name, skill.description or "—") for skill in skills]
            return CommandResult(
                True,
                self._render_table(
                    "skills",
                    "技能清单",
                    ("技能", "说明"),
                    rows or [("—", "当前没有已加载技能")],
                    default_width=220,
                    max_width=560,
                ),
            )
        if command == "/model":
            if argument:
                self.agent.config.model = argument.strip()
                return CommandResult(True, f"model set to {self.agent.config.model}")
            return CommandResult(True, self.agent.config.model)
        if command == "/exit":
            return CommandResult(True, "__EXIT__")
        return CommandResult(True, f"unknown command: {command}")
