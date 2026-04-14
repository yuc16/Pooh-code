# 启动与执行流程

本文件描述 `pooh-code` 的运行链路和默认执行节奏，用于约束代理在当前仓库中的工作方式。

## 启动顺序

1. 从 `workplace/runtime/config/settings.json` 和环境变量加载配置
2. 按固定顺序加载 runtime 引导文件：
   - `SOUL.md`
   - `IDENTITY.md`
   - `TOOLS.md`
   - `USER.md`
   - `BOOTSTRAP.md`
   - `AGENTS.md`
   - `MEMORY.md`
3. 扫描 `workplace/runtime/skills/`，注册技能元数据和 `use_skill` 工具
4. 从 JSONL transcript 恢复当前会话历史
5. 构建 system prompt，并把运行时信息注入 `## Runtime`
6. 进入模型 + 工具循环，直到产出最终回复

## Runtime 注入信息

system prompt 中会动态注入运行时 JSON，至少包括：

- `project_root`
- `runtime_root`
- `output_root`
- `cwd`
- `timezone`
- `local_time`

在有会话上下文时，还会额外注入：

- `session_key`
- `current_session_id`
- `session_output_dir`
- `session_output_dir_relative_to_workplace`

代理必须优先使用这些运行时字段，而不是凭空猜测路径。

## 默认执行节奏

处理用户任务时，遵循下面节奏：

1. 先理解用户目标和约束
2. 先读代码、读文件、看结构，再下修改结论
3. 如果任务与某个 skill 描述明显匹配，先调用 `use_skill`
4. 优先做最小必要分析，不做泛泛而谈的空总结
5. 需要动手时，直接产出文件、脚本、修改或命令，而不是停留在建议层
6. 每次有意义的变更后，优先做本地验证
7. 最终回答只保留高价值结果、验证情况和剩余风险

## 会话与输出

- 会话内容按 `session_id` 管理
- 默认运行产物写入 `workplace/output/<session_id>/`
- agent 生成的临时脚本、中间 JSON、最终 Office 文件都允许放在对应会话目录下
- 前端文件面板会按 `session_id` 归档展示输出产物

## 命令能力

以下 slash command 已内置：

```text
/help /clear /new /switch <session_id_prefix> /compact /ctx /sessions /skills /prompt /model [name] /subagent <task> /exit
```

在 Web 前端和 CLI 场景中，都应把这些命令视为系统级入口，而不是普通自然语言请求。

## 失败处理

- 工具失败时，应优先读取错误并继续迭代，不要直接放弃
- 网络或上游模型抖动时，应先识别是否属于瞬时问题
- 若因路径、权限、上下文不一致导致失败，应先自查 runtime 约束
- 真正无法继续时，再向用户说明阻塞点
