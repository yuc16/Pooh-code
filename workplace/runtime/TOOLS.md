# 工具说明

## 当前可用内置工具

- `bash`
  - 在项目中运行 Shell 命令
- `read_file`
  - 读取文件内容
- `write_file`
  - 创建或覆盖文件
- `edit_file`
  - 按文本替换文件中的内容
- `list_dir`
  - 查看目录
- `glob`
  - 按模式匹配定位文件
- `grep`
  - 使用 ripgrep 搜索项目内容
- `web_fetch`
  - 抓取网页并提取干净正文
- `web_search`
  - 联网搜索，适合快速找候选结果
- `web_search_and_read`
  - 联网搜索并自动抓取 top 结果正文
- `use_skill`
  - 加载某个 skill 的完整说明
- `spawn_agent`
  - 启动受限子代理

## 最重要的路径规则

**所有工具操作的根目录都是 `workplace/`，不是仓库根目录。**

这意味着：

- `bash` 默认 `cwd` 是 `workplace/`
- 文件工具路径都相对于 `workplace/`
- 正确写法：
  - `runtime/...`
  - `output/...`
  - `uploads/...`
- 不要写：
  - `workplace/runtime/...`
  - `workplace/output/...`

## 输出目录规则

如果用户没有明确指定输出位置，默认把生成内容写到：

```text
output/<session_id>/
```

优先使用 runtime 注入的：

- `current_session_id`
- `session_output_dir`
- `session_output_dir_relative_to_workplace`

不要手动猜目录。

## 工具使用偏好

### 文件和搜索

- 内容搜索优先使用 `grep` / `rg`
- 批量定位文件优先使用 `glob`
- 读文件前先缩小范围
- 修改前先确认目标文件当前内容

### Shell

- `bash` 适合执行脚本、查看状态、做验证
- 输出应尽量简洁，避免无意义刷屏
- 高风险命令需要非常谨慎

### 联网

- 有具体 URL 时优先 `web_fetch`
- 需要快速找信息时用 `web_search`
- 需要深入读内容时用 `web_search_and_read`

## 技能使用规则

当用户意图明显匹配某个 skill 描述时，应先调用：

```text
use_skill(name=...)
```

再按 skill 的要求执行，不要凭记忆模糊复述。

当前 skills 目录支持热重载，新增或更新 `workplace/runtime/skills/*/SKILL.md` 后，下一次请求即可生效。

## 子代理工具规则

`spawn_agent` 只用于边界清晰的子任务，优先：

- `explorer`：只读分析、仓库检索
- `general`：更一般的受限子任务

不要把主任务整体外包给子代理。

## 风险控制

工具使用中必须避免：

- 擅自删除用户文件
- 覆盖未知改动
- 大范围危险 shell 操作
- 在未确认路径规则时写错目录

对危险操作，宁可多检查一次，也不要赌。
