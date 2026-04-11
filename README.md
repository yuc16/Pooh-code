# Pooh Code

`pooh-code` 是一个用 Python 重构的、面向当前仓库运行的代码代理。它保留了 Claude Code 的核心工作流形态：

- 会话式 CLI
- 工具调用循环
- JSONL transcript 持久化
- skills 加载
- 自动上下文压缩
- 子 agent 搜索代理
- 飞书长连接入口
- ChatGPT OAuth / Codex responses 接口
- 联网搜索（Tavily + Brave 多引擎并行合并 + DuckDuckGo 兜底 + 搜索后自动阅读）

## 目录结构

源码现在放在 `src/pooh_code/`。

- [src/pooh_code](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code)：核心实现
- [workplace/runtime](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime)：运行时目录

`workplace/runtime/` 里只放运行时内容：

- `config/settings.json`：本地配置
- `sessions/`：主 agent 和子 agent transcript
- `skills/`：本地 skills
- `SOUL.md` / `IDENTITY.md` / `TOOLS.md` 等：bootstrap 提示词文件

其中 `sessions/<agent_id>/` 下面会按渠道分目录，例如：

- `sessions/main/cli/<session_id>/transcript.jsonl`
- `sessions/main/feishu/<session_id>/transcript.jsonl`

## 启动方式

默认只需要一个命令：

```bash
uv run pooh-code
```

这个命令会同时做两件事：

1. 启动本地 CLI
2. 在后台启动飞书 websocket 长连接

其他命令：

```bash
uv run pooh-code serve      # 同时启动 CLI 和飞书，等价于默认命令
uv run pooh-code chat       # 只启动 CLI
uv run pooh-code feishu     # 只启动飞书长连接
uv run pooh-code sessions   # 查看会话列表
uv run pooh-code-login      # 执行 ChatGPT OAuth 登录
uv run pooh-code-login --check
```

## CLI 功能

CLI prompt 会实时显示当前 `session_id` 和最近一次真实请求的 `total_tokens`，例如：

```text
[352d15a7c67c 1019/400k] You >
```

这里的 `400k` 是当前默认按 `gpt-5.4` 使用的上下文窗口。

说明：

- 左侧 `session_id` 是当前槽位正在使用的会话编号
- token 数值来自 Codex API 返回的真实 `usage.total_tokens`
- 新会话在第一次模型请求前没有真实值，因此会显示 `--/400k`
- 如果你执行了 `/compact`、`/clear` 这类会改写会话的操作，终端会先回到 `--/400k`，等下一次真实模型请求完成后再显示新的真实值
- 这个数值是最近一轮真实 usage 的总量展示，不是严格意义上的输入上下文占用；输入、输出拆分请用 `/ctx` 查看

内置命令：

```text
/help
/clear
/new
/switch <session_id_prefix>
/compact
/ctx
/sessions
/skills
/prompt
/model [name]
/subagent <task>
/exit
```

说明：

- `/ctx`：查看当前会话最近一次真实 usage；第一行会和终端 prompt 使用同一口径；如果还没打过模型，会显示 `unknown`
- `/clear`：清空当前 `session_id` 的 transcript，但保留这个 `session_id`
- `/new`：在当前槽位下新建一个 `session_id`，并自动切换过去
- `/switch <session_id_prefix>`：按全局前缀匹配切换到任意已存在的 `session_id`
- `/sessions`：查看所有渠道下的全部 `session_id`，`*` 表示当前正在使用的会话
- `/compact`：手动触发上下文压缩
- `/subagent <task>`：手动调用只读搜索型子 agent

## 上下文压缩

当上下文接近阈值时，`pooh-code` 会自动把较早的会话压缩成一条系统摘要，并保留最近若干轮原始消息。这个设计参考了 Claude Code 的 compact 思路：

- 为输出保留预算
- 在接近阈值时自动 compact
- 把旧上下文改写为“可继续工作的摘要”
- 近期消息保持原样，降低语义漂移

你也可以用 `/compact` 手动执行。

## 子 Agent

当前已经加入子 agent 工具 `spawn_agent`，以及 CLI 命令 `/subagent`。

它的主要用途是：

- 代码搜索
- 只读分析
- 把搜索任务从主 agent 上下文中剥离出去

目前最适合的是 `explorer` 类型，行为参考 Claude Code 的 Explore agent：

- 只读
- 禁止写文件
- 优先使用 `glob` / `grep` / `read_file` / 只读 `bash`
- 返回压缩后的结论给主 agent

## Skills

Skills 是一种"按需加载的操作手册"。每个 skill 是 [workplace/runtime/skills/](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/skills) 下的一个子目录，目录里有一个 `SKILL.md`，包含：

- frontmatter（`name`、`description`）
- markdown 正文，描述具体步骤和边界

加载机制做了**两级递进**，让 skill 的触发对用户**可见**：

1. **元数据层**：agent 启动时扫描所有 skill，把 `name` + `description` 作为一个列表塞进 system prompt（见 [skills.py](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code/skills.py) 的 `render_metadata_for_prompt`）。完整正文**不**进 system prompt，避免无谓占用 context。
2. **工具层**：注册一个 `use_skill` 工具（见 [agent.py](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code/agent.py) 的 `_register_skill_tool`），参数是 skill 名字，返回对应 `SKILL.md` 的正文。`enum` 会锁定到当前所有已发现的 skill 名字，防止模型瞎填。

运行时流程：

1. 用户说"推送到 github"
2. 模型看到 system prompt 里的 skill 列表，命中 `github-push` 的 description
3. 模型调用 `use_skill(name="github-push")` —— **前端工具调用卡片会展示这次调用**，这就是用户能看到的"skill 被用了"的信号
4. 拿到 body 后模型按指令陆续调用 `bash` 等工具完成实际工作

目前已有的 skill：

- **github-push** —— 把本地改动统一推送到 GitHub 同名远程仓库的 `temp` 分支，自动处理 commit、remote 创建、冲突检测

注意：`use_skill` 的 `enum` 在 agent 构造时固化，新增 skill 需要重启进程才会被发现。

## 飞书

飞书配置在：

- [workplace/runtime/config/settings.json](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/config/settings.json)

当前默认使用你提供的：

- `app_id`
- `app_secret`

实现方式是飞书 websocket 长连接，不是旧式 webhook 轮询。

回发消息时，`pooh-code` 会优先使用收到事件里的 `message_id` 直接回复原消息；只有拿不到 `message_id` 时，才会退回按 `chat_id` / `open_id` 新发消息。

## Web 前端

项目自带一个零依赖的 Web 前端，代码在 [src/frontend](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend)：

- [src/frontend/server.py](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/server.py)：用 Python 标准库 `http.server` 包一层 `PoohAgent` + `CommandProcessor`，不引入新依赖
- [src/frontend/static/index.html](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/static/index.html) / [style.css](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/static/style.css) / [app.js](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/static/app.js)：原生 HTML/CSS/JS，无需构建

启动方式：

```bash
PYTHONPATH=src uv run python -m frontend.server
# 默认监听 http://127.0.0.1:8787
# 可选参数：--host 0.0.0.0 --port 8787 --config path/to/settings.json
```

Web 端固定使用 `session_key = agent:main:web:local:web-user`，与 CLI、飞书 channel 相互隔离，不会互相污染会话。

### 界面功能

- 浅色风格，左侧 sidebar + 右侧主聊天区的经典两栏布局
- 左侧：新建会话、刷新、快捷命令（`/help` `/ctx` `/sessions` `/skills` `/compact` `/clear`）、会话列表
- 会话列表只显示 web channel 下的会话（不混入 cli / feishu），点击任一条即可**切换并保留历史记录**
- 每个会话条目 hover 时右侧出现 `✕` 删除按钮，点击会弹 confirm 二次确认，确认后同步删除 [workplace/runtime/sessions/main/web/&lt;session_id&gt;/transcript.jsonl](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/sessions/main/web) 和索引记录；如果删的是最后一条会自动新建一条空白会话
- 顶栏：状态灯（就绪 / 思考中 / 错误）、实时 context usage（如 `1019/400k`）、当前 model 徽章
- 主聊天区：user / assistant / system 三种气泡，支持正常上下滚动（老版本的 flex `min-height` bug 已修）
- 输入框：Enter 发送，Shift+Enter 换行，textarea 高度自动增长
- 输入以 `/` 开头走 `/api/command` 命令路径，命令回显和输出会作为 system 气泡贴在聊天区里
- 当 `reply.compacted` 为真时，会插入一条 `[autocompact -> xxx/400k]` 系统气泡

### 流式输出 / 思考过程 / 工具调用展示

非命令消息默认走 SSE 流式接口 `POST /api/chat/stream`，前端用 `fetch` + `ReadableStream` 逐帧解析，实时增量渲染，不用等整轮回复结束：

底层 Codex SSE 事件被转成下列业务事件（见 [src/pooh_code/openai_codex.py](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code/openai_codex.py) 的 `_consume_sse` 和 [src/pooh_code/agent.py](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code/agent.py) 的 `PoohAgent.ask_stream`）：

| 事件 | 含义 |
| --- | --- |
| `text_delta` | 助手正文的 token 级增量，前端按字符追加，尾部带闪烁光标 |
| `tool_use_started` | 模型开始调用工具，前端立即插入一张 tool-block 卡片（徽章 `TOOL`、工具名、状态 `调用中…`） |
| `tool_use_done` | 工具参数就绪，卡片里填充 `INPUT` JSON，状态切到 `执行中…` |
| `tool_result` | 本地 `ToolRegistry.execute` 跑完，卡片里追加 `OUTPUT`，状态切到 `完成`；如果是错误输出会变红色并显示 `ERROR` + `失败` |
| `turn_start` | 多轮 tool_use 时在两轮之间插入一条灰色 `· turn N ·` 分隔线 |
| `compacted` | 触发了自动 compact，追加 `[autocompact -> xxx/400k]` 系统气泡 |
| `done` | 当前轮全部结束，前端置 `finished=true` 跳出 reader 循环 |
| `state` | 最后一帧带上新的 `session_id` / `usage`，用来同步右上角 |
| `error` | 任意异常，前端置错误状态并写系统气泡 |

tool-block 卡片的 `INPUT` / `OUTPUT` 都是可折叠的代码块，点击卡片头即可收起，方便长工具输出不挤占视线。

SSE 连接使用 `Connection: close` 并在服务端强制 `self.close_connection = True`，前端在收到 `done` 后主动 `reader.cancel()`，避免 reader 挂住导致输入框卡死。

### HTTP API

| Method | Path | 作用 |
| --- | --- | --- |
| GET  | `/api/state` | 当前 `session_id` / `model` / `usage` |
| GET  | `/api/messages` | 载入当前会话 transcript（已扁平化为纯文本） |
| GET  | `/api/sessions` | 列出当前 web channel 下的所有会话 |
| POST | `/api/chat` | 同步调用 `agent.ask(session_key, text)`，一次返回完整回复 |
| POST | `/api/chat/stream` | **SSE 流式**接口，调用 `agent.ask_stream`，推送 `text_delta` / `tool_use_*` / `tool_result` / `done` 等事件 |
| POST | `/api/command` | 走 `CommandProcessor`，支持 `/help` `/ctx` `/skills` `/compact` 等 |
| POST | `/api/session/new` | 新建一个 `session_id` |
| POST | `/api/session/switch` | 按 `session_id` 前缀切换（只在当前 web channel 的 slot 内匹配） |
| POST | `/api/session/clear` | 清空当前会话 transcript |
| POST | `/api/session/delete` | 删除指定 `session_id`，同步 `shutil.rmtree` 掉磁盘上的 transcript 目录；若删的是最后一条会自动创建新会话 |
| POST | `/api/session/compact` | 强制触发一次 compact |

普通接口返回 JSON，形如 `{"ok": true, ...}`，失败时为 `{"ok": false, "error": "..."}`；`/api/chat/stream` 返回 `text/event-stream`，每帧 `data: {"type": "...", ...}\n\n`，流末尾会有一行 `data: [DONE]\n\n`。

## 联网搜索

`pooh-code` 提供三个联网工具，agent 在推理过程中会自主决定何时调用：

| 工具 | 用途 | 说明 |
| --- | --- | --- |
| `web_search` | 联网搜索 | 默认多引擎并行（Tavily + Brave），按 URL 去重合并；多源命中的结果自动排前面；全部失败时降级到 DuckDuckGo。可通过 `engine` 参数指定单一引擎 |
| `web_fetch` | 抓取网页正文 | 自动识别正文区域（`<article>`/`<main>` 等），去除导航、广告、脚本等干扰内容 |
| `web_search_and_read` | 搜索 + 自动阅读 | 先多引擎搜索再自动抓取 top 结果的完整正文，适合需要深入了解的场景 |

### 多引擎策略

`web_search` 在 `engine=auto`（默认）下并行调用所有已配置 key 的引擎，合并去重。每条结果都带 `source` 字段标记来源（如 `tavily`、`brave`、`brave+tavily`）。好处：

- **可靠性**：单引擎挂掉不影响主流程
- **覆盖广度**：不同引擎索引不同内容，结果更全
- **置信加权**：多引擎都返回的 URL 会排到合并列表的最前面

配置 API Key（统一在 [workplace/runtime/config/settings.json](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/config/settings.json) 配置）：

```json
{
  "search": {
    "tavily_api_key": "tvly-xxx",
    "brave_api_key": "BSA01..."
  }
}
```

- 两个 key 都配 → 双引擎并行合并（推荐）
- 只配一个 → 单引擎 + DuckDuckGo 兜底
- 都不配 → 全部回落 DuckDuckGo

## 推理配置

模型的推理深度与可见摘要在 [settings.json](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/config/settings.json) 配置：

```json
{
  "reasoning": {
    "effort": "medium",
    "summary": "auto"
  }
}
```

### 背景

gpt-5 / Codex 这类推理模型内部会产生很长的思维链（chain-of-thought），但原始 CoT 出于安全和商业考虑**不会**直接返给开发者。API 提供了折中方案：让模型在内部推理结束后自己总结一段可读摘要返回，这就是 `reasoning.summary`。

### `effort` —— 模型真实思考多深

| 值 | 含义 |
| --- | --- |
| `low` | 轻度推理，最快，适合简单任务 |
| `medium` | 中等推理，平衡速度与质量（默认） |
| `high` | 深度推理，最慢最贵，适合复杂问题 |

### `summary` —— 对外展示多少推理过程

| 值 | 含义 |
| --- | --- |
| `none` | 不返回任何推理摘要（节省 token、最快） |
| `auto` | 模型自己决定要不要给、给多长（默认推荐） |
| `concise` | 强制返回简短摘要（通常几句话） |
| `detailed` | 强制返回详细摘要（段落级，接近完整思路） |

### 两者的区别

- **`effort`** = 模型**真实思考**多深（影响答案质量和耗时）
- **`summary`** = 思考完以后**对外展示**多少（只影响你能看到什么，不影响答案质量）

组合示例：

- `effort=high, summary=none` → 深度思考但你看不到过程
- `effort=low, summary=detailed` → 思考很浅，但把浅的过程详细写给你
- `effort=high, summary=detailed` → 深度思考 + 详细展示（最消耗 token）

前端 Web UI 会在助手气泡里以虚线框的形式实时展示推理过程（`REASONING` 标签）。

## 工具沙箱

所有内置工具（`bash` / `read_file` / `write_file` / `edit_file` / `list_dir` / `glob` / `grep`）都被强制约束在 [workplace/](/Users/wangyc/Desktop/projects/Pooh-code/workplace) 目录内，目的是把 agent 的可写范围收敛到运行时区域，避免误伤项目源码或系统文件。

实现分两层：

### A 层：Python 路径校验（跨平台）

在 [tooling.py](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code/tooling.py) 里，所有涉及路径的工具都走 `_safe_workplace_path()`：它把相对路径拼到 `WORKPLACE_DIR`，把绝对路径 `resolve()` 后检查是否仍在 workplace 子树内，越界直接抛 `ValueError`。`bash` 的 `cwd` 参数也走同一校验，默认 `.` 解析为 workplace 根。

这一层是纯 Python 实现，任何平台都生效，但**只能防住工具参数层面**的越界——bash 命令串内部的 `cat /etc/passwd`、`cd /` 等它拦不住。

### B 层：OS 级沙箱（macOS + Linux）

`bash` 工具在执行时会根据当前操作系统额外套一层 OS 级沙箱：

| 平台 | 机制 | 依赖 |
| --- | --- | --- |
| macOS | `sandbox-exec -p <profile>` | 系统自带 |
| Linux | `bwrap`（bubblewrap）新 mount namespace | `apt install bubblewrap` / `dnf install bubblewrap` |
| 其他 | 无 B 层，降级到纯 A 层 | — |

**macOS profile** 策略：
- `allow default` 起手 → `deny file-write*` → 只允许对 workplace、`/tmp`、`/var/folders`（Python tempfile 默认位置）、`/dev/null` 等写入
- 读权限全放行（不然 `python`、`git`、`rg` 等系统工具跑不起来）
- 网络放行（`web_search` / `pip` 需要）

**Linux bwrap** 策略：
- 只读绑定 `/usr /bin /sbin /lib /lib64 /etc`（提供系统工具链）
- 读写绑定 workplace
- `/tmp` 用私有 tmpfs 隔离
- `--unshare-user-try --unshare-pid --share-net --die-with-parent`
- `--chdir` 到 bash 工具请求的 cwd

注意事项：
- 部分 Linux 发行版（如 Debian 11+）默认禁用非特权 user namespace，bwrap 会启动失败。可以 `sysctl kernel.unprivileged_userns_clone=1` 打开，或回落到纯 A 层。
- 读权限没有严格隔离是有意为之——完全隔离读操作会让 Python/Git 等基础工具失效。如果未来要跑不信任的 skill，建议改用 Docker 方案。
- 沙箱对 agent 自己发起的 `read_file` 也生效：想读项目源码（比如 `src/pooh_code/*.py`）会被 A 层直接拒。如果要让 agent 读源码，需要先把相关文件软链接或复制到 workplace。

### 实测

```bash
# workplace 内写入 → OK
bash: echo hi > runtime/cache/x.txt

# workplace 外写入 → 被内核拒绝
bash: echo x > /Users/wangyc/Desktop/x.txt
# stderr: Operation not permitted

# 路径参数越界 → A 层抛错
read_file: /etc/passwd
# Error: path escapes workplace sandbox: /etc/passwd
```
