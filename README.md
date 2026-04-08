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
[352d15a7c67c 1019/258k] You >
```

这里的 `258k` 是当前默认按 `gpt-5.4` 使用的上下文窗口。

说明：

- 左侧 `session_id` 是当前槽位正在使用的会话编号
- token 数值来自 Codex API 返回的真实 `usage.total_tokens`
- 新会话在第一次模型请求前没有真实值，因此会显示 `--/258k`
- 如果你执行了 `/compact`、`/clear` 这类会改写会话的操作，终端会先回到 `--/258k`，等下一次真实模型请求完成后再显示新的真实值
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
- 顶栏：状态灯（就绪 / 思考中 / 错误）、实时 context usage（如 `1019/258k`）、当前 model 徽章
- 主聊天区：user / assistant / system 三种气泡，支持正常上下滚动（老版本的 flex `min-height` bug 已修）
- 输入框：Enter 发送，Shift+Enter 换行，textarea 高度自动增长
- 输入以 `/` 开头走 `/api/command` 命令路径，命令回显和输出会作为 system 气泡贴在聊天区里
- 当 `reply.compacted` 为真时，会插入一条 `[autocompact -> xxx/258k]` 系统气泡

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
| `compacted` | 触发了自动 compact，追加 `[autocompact -> xxx/258k]` 系统气泡 |
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

## 当前实现边界

现在这版已经覆盖了 Claude Code 最核心的运行链路，但还不是 1:1 完整复刻。已经做好的部分是：

- 主 agent 循环
- 工具调用
- 会话持久化
- 上下文显示
- 上下文压缩
- 搜索型子 agent
- 飞书长连接
- ChatGPT OAuth

还没有完整复刻的部分主要是：

- Ink/TUI 级别的复杂终端 UI
- IDE bridge
- MCP 全量生态
- 完整多代理编排与后台任务系统
- Claude Code 全量 slash commands

如果继续往下补，建议下一阶段优先做：

1. 更完整的 `spawn_agent` 参数和后台执行
2. 更接近 cc 的 compact prompt 和恢复策略
3. 权限模型与审批流
4. `/review`、`/commit`、`/resume` 这类高频命令
