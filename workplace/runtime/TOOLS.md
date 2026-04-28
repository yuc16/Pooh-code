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
  - 抓取网页并提取干净正文（Jina Reader 优先，SPA / JS 页也能解析）
- `web_search`
  - 智能多引擎联网搜索（Tavily / Brave / Bocha / Exa / Search1API + DDG 兜底，按 query 智能路由）
- `deep_research`
  - 深度研究：迭代 search → read → reason，输出带引用的研究答案（Jina DeepSearch）
- `paper_search`
  - 通过 OpenAlex 检索论文并返回结构化元数据
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

按"用户在让你做什么"决策，不要默认全用 `web_search`：

- 有具体 URL 时 → `web_fetch`
- 找候选资料、列出来源、需要 snippet 概览 → `web_search`（auto 路由会自动挑引擎）
- **以下任何一类，必须用 `deep_research` 而不是 `web_search`**：
  - 用户说 "调研 / 研究 / 帮我查清楚 / 深入了解 / 给我一份带引用的分析"
  - 用户问的问题需要**综合多个来源**才能回答（"X 公司有没有可量化的产品效益数据"、"Y 技术现在的主流方案对比"、"Z 政策的最新变化与影响"）
  - 用户明确要 "带出处 / 带链接 / 带引用 / 写成一段"
  - 一次 `web_search` 拿到的 snippet 看下来还不够形成结论 → 升级到 `deep_research`，不要循环抓 5 篇网页硬拼
- 涉及论文、文献、参考文献、综述时 → `paper_search` 优先

#### web_search 的引擎选择

`auto`（默认）会并跑 **Tavily + Brave + Bocha** 三家，覆盖中英文双向。多数任务直接 auto 就够。

但是**当用户的问题对"信息所在地"有明确倾向时，你应该主动 override `engine` 参数**，而不是依赖 auto——因为 auto 不知道用户在想什么。判断标准是"这条问题的一手资料最可能在哪"，而不是"实体国别"。

| 引擎 | 强项 | 什么时候 **主动指定** |
| --- | --- | --- |
| `bocha`（博查） | 中文社区/媒体 — 知乎、微信公众号、小红书、CSDN、百度系、中文行业研报 | 用户问的是国内特定信息：经销商网络、国内行情价、国内政策、中文社区怎么看、行业公众号深度文、品牌中文舆情 |
| `brave` | 独立索引（不依赖 Google/Bing） — 干净的 snippet，对长尾技术站、被 SEO 严重污染的话题反而更准 | 主流引擎被广告/SEO 污染严重的 query（"X 怎么样"、"Y vs Z"）；想避开 Google 偏见交叉验证 |
| `tavily` | LLM 友好——返回 `answer` 字段 + 高相关度结果，可加 `search_depth="advanced"` 提质 | 想要快速一句话答案 + 来源；通用问答；想用 advanced 深度时 |
| `exa` | 神经/语义检索 + findSimilar | 关键词难以命中但语义清楚："找类似的博客"、"与这篇论文最相关的工作"、"用这个 idea 做的产品有哪些" |
| `search1api` | Google/Bing 元搜索聚合 | 前面三家都召回稀疏时再用作兜底加宽 |
| `duckduckgo` | 无 key 兜底 | 正常情况不选 |

**判断"实体国别 ≠ 信息所在地"的关键例子**：

- "比亚迪海外销量分析" → 一手在英文（BYD IR、JATO、InsideEVs），**不要**仅用 `bocha`，让 auto 跑或显式 `engine="tavily"` / `brave`
- "比亚迪国内销售网络" → 一手在中文，可显式 `engine="bocha"`
- "NVIDIA H100 中国行情价" → 一手在中文，显式 `engine="bocha"`
- "NVIDIA Hopper 架构原理" → 一手在英文白皮书，显式 `engine="brave"` 或 auto

**不要循环重跑同一个 engine 想拼出更多结果**——结果稀疏时要么换 engine 验证（`brave` ↔ `tavily` 是常用组合），要么升级到 `deep_research`。

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
