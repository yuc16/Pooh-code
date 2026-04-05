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

CLI prompt 会实时显示最近一次真实请求的输入 token 数，例如：

```text
[949/258k] You >
```

这里的 `258k` 是当前默认按 `gpt-5.4` 使用的上下文窗口。

说明：

- 左侧数值来自 Codex API 返回的真实 `usage.input_tokens`
- 新会话在第一次模型请求前没有真实值，因此会显示 `--/258k`
- 如果你执行了 `/compact`、`/clear` 这类会改写会话的操作，终端会先回到 `--/258k`，等下一次真实模型请求完成后再显示新的真实值

内置命令：

```text
/help
/clear
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

- `/ctx`：查看当前会话最近一次真实 usage；如果还没打过模型，会显示 `unknown`
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
