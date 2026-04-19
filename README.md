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

## README 维护约定

从现在开始，凡是影响用户使用方式、前端交互、命令语义、运行架构或目录结构的**较大改动**，都要同步更新 `README.md`，不能只改代码不改文档。

适用范围至少包括：

- 新增、删除或重定义 CLI / Web 命令
- 调整 Web 前端的重要交互、布局、视觉入口
- 修改会话、产物、认证、路由、运行方式等对外行为
- 新增重要资源文件或约定目录

## 目录结构

源码现在放在 `src/pooh_code/`。

- [src/pooh_code](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code)：核心实现
- [workplace/runtime](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime)：运行时目录

`workplace/` 下有两个平级的子目录,各司其职：

- `workplace/runtime/` —— 运行时状态,本地私有,不推到任何远端
  - `config/settings.json`：本地配置
  - `sessions/`：主 agent 和子 agent transcript
  - `skills/`：本地 skills(`SKILL.md` 作为配置由主仓库 main 分支跟踪)
  - `SOUL.md` / `IDENTITY.md` / `TOOLS.md` 等：bootstrap 提示词文件
- `workplace/output/` —— **agent 产出专区**,里面有一个独立的第二 git 仓库,把 agent 生成的文件推到 GitHub 的 `temp` 分支,详见下面「双仓库架构」
  - agent 生成的所有文件都会按 `session_id` 隔离到 `workplace/output/<session_id>/`
  - 删除某个 web 会话时，会同步删除该 `session_id` 在 `workplace/output/` 下对应的目录

其中 `sessions/<agent_id>/` 下面会按渠道分目录，例如：

- `sessions/main/cli/<session_id>/transcript.jsonl`
- `sessions/main/feishu/<session_id>/transcript.jsonl`

### 双仓库架构

本项目的 git 被**物理拆成两个仓库**,解决"agent 频繁产出"和"人类维护源码"互相污染的问题:

| 仓库 | 位置 | 分支 | 谁在写 | 写什么 |
| --- | --- | --- | --- | --- |
| 主仓库 | 项目根 `.git/` | `main` | 人类开发者(手动) | `src/`、`README.md`、`workplace/runtime/skills/*/SKILL.md` 等源码/配置 |
| 产出仓库 | `workplace/output/.git/` | `temp` | agent(通过 `github-push` skill) | agent 任务执行时产出的任何文件 |

两个仓库的 `origin` 指向**同一个 GitHub repo**,但 `main` 和 `temp` 分支历史**完全独立**(`temp` 是 orphan 起源,无共同祖先)。好处:

- main 分支历史永远干净,只有人类的源码提交
- agent 的产出在云端 `temp` 分支随时可查,不污染任何正式分支
- **完全兼容沙箱**:`workplace/output/.git/` 整个在 workplace 内,agent 读写 git 对象文件不需要任何沙箱豁口；反过来,agent 物理上也碰不到项目根的 `.git/`(沙箱直接拒),杜绝误推 main 的可能

主仓库的 `.gitignore` 把 `workplace/output/` 整个忽略,避免嵌套 repo 被主仓库当成 untracked 或 submodule 误处理。

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
/tools
/skills
/prompt
/model [name]
/subagent <task>
/exit
```

说明：

- `/ctx`：查看当前会话最近一次真实 usage；第一行会和终端 prompt 使用同一口径；如果还没打过模型，会显示 `unknown`
- `/help`：输出格式化后的命令总览表
- `/tools`：输出当前可用工具及工具说明
- `/skills`：输出当前已加载 skill 及说明
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

- **github-push** —— 把 `workplace/output/` 里 agent 自己产出的文件 commit 并推送到 GitHub 的 `temp` 分支(独立于主仓库 main 分支)。**只操作产出仓库,不触碰项目源码**,详见上面「双仓库架构」
- **docx-create** —— 使用 `python-docx` 生成专业 Word 文档（.docx），支持标题、表格、列表、页眉页脚、目录、图片等完整排版功能
- **xlsx-create** —— 使用 `openpyxl` + `pandas` 生成或编辑 Excel 电子表格（.xlsx），支持公式、图表、条件格式、数据分析等
- **pptx-create** —— 使用 `python-pptx` 生成专业 PowerPoint 演示文稿（.pptx），内置配色方案和版式指南，支持形状、表格、图表等丰富元素

现在 skills 已改成按请求自动刷新：新增目录、修改 `SKILL.md`、删除 skill 后，无需重启服务，下一次请求、下一次 `/skills`、以及下一次生成 system prompt 时都会重新扫描 [workplace/runtime/skills](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/skills) 并更新 `use_skill` 工具的可选列表。

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

Web 端走「邮箱 + 密码」账号体系，每个用户自己的 `session_key` 形如 `agent:main:web:user:u<id>`，用户之间彼此不可见；CLI 和飞书 channel 仍然使用各自的固定 key，不走登录流程。

### 账号与登录（仅 Web）

- 数据层：SQLite 单文件 [private/auth.db](/Users/wangyc/Desktop/projects/Pooh-code/private)（**故意放在项目根目录下的 `private/` 而不是 `workplace/`**，这样 agent 的沙箱根本看不到/改不了 `auth.db`；`private/` 整目录已加入 `.gitignore`），两张表：`users(id, email unique, pwd_hash, created_at)` 和 `auth_tokens(token, user_id, created_at, expires_at, ua)`；代码见 [src/pooh_code/auth_db.py](/Users/wangyc/Desktop/projects/Pooh-code/src/pooh_code/auth_db.py)
- 密码哈希：`hashlib.scrypt`（stdlib，无新依赖），N=2^14，每用户独立 16 字节随机盐，存储格式 `scrypt$<salt_hex>$<digest_hex>`
- Token：登录/注册后服务端生成 32 字节 `secrets.token_urlsafe`，存进 `auth_tokens` 表（TTL 30 天），以 `pooh_token` cookie（`HttpOnly; SameSite=Lax; Path=/`）发给浏览器；退出登录时 DB 删除 token 并清 cookie，可随时踢下线
- 中间件：所有 `/api/*` 路由（除 `/api/auth/*`）都要求已登录，未登录直接 401；`GET /` 未登录时 302 跳 `/login`
- 登录页：独立 HTML [src/frontend/static/login.html](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/static/login.html)，支持登录 / 注册两种模式切换
- 前端：[app.js](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/static/app.js) 的 `api()` 收到 401 自动跳回 `/login`；侧栏底部显示当前邮箱与「退出」按钮
- 会话越权保护：所有 `POST /api/session/*` 如果请求体指定了 `session_id`，会校验它必须属于当前用户的 `session_key`，否则 403
- 产物归档隔离：`/api/files` 只返回当前用户拥有的 session 对应的产物分组（不是所有用户共用），`/api/download` 也会校验文件所在的 `session_id` 属于当前用户，否则 403——彻底阻止横向越权查看其他用户的文件
- 老数据：之前 `local:web-user` 槽位下的 session 直接作废（不会迁移到任何账号），新用户注册后从空会话开始

| POST | `/api/auth/register` | 邮箱 + 密码 + 可选邀请码注册并自动登录 |
| POST | `/api/auth/login` | 邮箱 + 密码登录，成功后写 `pooh_token` cookie |
| POST | `/api/auth/logout` | 登出，DB 删 token + 清 cookie |
| GET  | `/api/auth/me` | 返回当前登录用户（未登录 401） |

### 界面功能

- **暖调米白书卷气主题**（Newsreader 衬线 + Geist 无衬线 + JetBrains Mono 等宽 + 琥珀 accent），基于 oklch 色彩空间的低饱和度米白纸张配色，不再提供深色主题切换
- **三栏布局**：左侧会话栏（2fr）/ 中间聊天区（7fr）/ 右侧 Minimap（1fr）；两条 `col-divider` 分隔条可鼠标拖拽调整三栏比例，结果持久化到 `localStorage.pooh.cols.v1`
- 左侧栏：顶部是品牌 logo + 刷新按钮 + 搜索框（⌘K 聚焦）+ "新建会话"按钮（⌘N 新建）、会话列表（`.convo` 行）、底部用户卡片（头像 + 邮箱 + 退出按钮）
- 首页左上角、登录页品牌区、浏览器页签 favicon 与 touch icon 现在统一使用 [src/frontend/static/logo.jpg](/Users/wangyc/Desktop/projects/Pooh-code/src/frontend/static/logo.jpg)；首页和登录页左上角 logo 不再带边框、底色或阴影方框，直接贴合页面背景显示，并带版本参数以避免浏览器长期缓存旧图
- 每个会话条目 `.convo`：**紧凑单行**布局——标题 + 时间（右对齐贴到 token 进度条右缘）同一行，下方一条 token 进度条（来自 `list_sessions` 返回的 `usage` 字段，≥75% 转为红色警示），**不再显示"N 产物"徽标**以减少视觉噪音；**点击标题可展开内嵌的产物列表**（来自 `/api/files` 对应 `session_id` 分组，每条可直接点击下载），再次点击切换收起
- 会话列表按日期分组（今天 / 昨天 / N 天前 / 年月），只显示 web channel 下的会话（不混入 cli / feishu）；搜索框可按标题或 `session_id` 实时过滤
- **双击标题**可直接重命名（Enter 确认，Escape 取消），修改后写入 `sessions.json`
- hover 会话时右侧出现 `✕` 删除按钮，确认后同步删除 [workplace/runtime/sessions/main/web/&lt;session_id&gt;/transcript.jsonl](/Users/wangyc/Desktop/projects/Pooh-code/workplace/runtime/sessions/main/web) 、索引记录，以及 [workplace/output/&lt;session_id&gt;](/Users/wangyc/Desktop/projects/Pooh-code/workplace/output) 下对应的产物目录；如果删的是最后一条会自动新建一条空白会话
- 切换会话时，前端会先本地切换高亮与标题，再静默刷新 `/api/sessions`，避免顶部误报“加载会话失败”
- 中间栏顶栏：**当前会话标题**（优先展示 `label`，未命名时 fallback 到 `session_id` 前 8 位；**不再有 `—` 分隔符**）；**双击标题可直接在顶栏重命名**（与左栏双击行为一致，写入 `sessions.json` 后同步刷新）；model 徽章（带呼吸灯 pulse，`busy` 态橙色脉动、`err` 态红色）、"压缩上下文"按钮（等价于 `/compact`）、"停止"按钮
- 右侧 Minimap 已重构为**当前会话的用户提问导航列表**：只列出 `.msg.u`（用户消息），以带序号 + 问题摘要的导航条呈现，点击跳转到该消息；滚动时自动高亮当前可见的问题作为 active 项。相比旧的"缩放预览 + 拖拽 viewport"方案，导航更清晰、可读、更像侧边目录
- **主页面 Agent 状态面板**：顶栏下方常驻一条高可见度状态条，把 Agent 当前在做什么实时外显：
  - 状态等级按颜色区分——`idle`（灰）/ `busy`（蓝）/ `thinking` 推理中（紫）/ `tool` 工具调用（橙）/ `error`（红），每个级别配独立的标题、详情文本和秒级计时器
  - 状态栏现在是**中栏顶部常驻的页面内固定信息条**，不再是可关闭的悬浮卡片；始终贴在聊天 header 下方展示当前运行状态，横向宽度与中栏 header 对齐，文字也统一使用 header 的字体体系
  - 事件粒度映射到 SSE 流：`turn_start` → "第 N 轮"、`reasoning_delta` → "思考中 · 模型正在进行推理"、`tool_use_started`/`tool_use_done` → "调用/执行工具: &lt;name&gt;"、`tool_result` → "工具已返回"、`text_delta` → "生成回复中"、`done` → "完成"、`cancelled` → "已取消"、`truncated` → "已截断"、`compacted` → "上下文已压缩"
  - 运行 slash 命令（例如 `/compact`）时也有独立反馈：成功显示「命令完成」，失败则明确提示「当前会话仍在运行中，请先点击停止或等待本轮完成」——解决之前用户不知道为何命令没反应的问题
  - 兜底机制：即便 SSE 流提前关闭未收到 `done` 事件，前端也会在 `finally` 里强制把「思考中」落定为「已思考」并用已接收到的文本渲染 Markdown，避免"agent 已回答完但前端卡在思考中需要手动刷新"的旧 bug
  - 8 秒无事件会追加"响应延迟较高，已等候 Xs"提示，让用户知道不是前端卡了
- 主聊天区：user / assistant / system 三种气泡（`.msg.u` / `.msg.a` / `.msg.s`）
  - **user 气泡**：保留头像 + 衬线体"你"角色名，正文放在柔和的米白 → 淡琥珀渐变 bubble 内（无硬边框，只有极淡的内阴影和 1px 微光边），不再是旧版那种突兀的"琥珀色方块"
  - **assistant / system 气泡**：**不再显示头像与"Pooh Code / 系统"角色名**，回答内容直接贴左呈现——减少视觉干扰，让阅读焦点始终在正文上
  - 在聊天区内**选中任意一段消息文本并完成选区**后，会在选区附近浮出一个“引用到输入框”按钮；点击后把该段文字以 `[引用: "..."]\n\n` 的**纯文本前缀**注入输入框（保留原样，不再强行 Markdown 化成 `> blockquote`），发送后在对方气泡里会以**独立 DOM 节点 `.quote`**（左侧淡琥珀竖线 + 灰色正文，**不显示"你"角色名**）渲染，避免引用块被 Markdown 解析器误判为代码块
- hover 消息时气泡下方保留 `复制 / 时间戳` 操作；新消息显示 `HH:MM`（跨日则显示 `MM-DD HH:MM`）；历史消息因 transcript 暂未透传 `ts` 给前端，默认留空
- 纯工具调用的 assistant 消息会默认收成一条紧凑的“已处理 / N 个工具调用”折叠摘要；连续多条工具消息之间不再留大块空白，且这类纯工具消息不再额外显示 `复制 / 时间戳`
- 生成的文件**不再在 assistant 气泡里重复展示下载卡片**；前端只保留左侧会话栏下对应 session 的产物归档入口，避免同一文件在聊天区和左栏重复出现
- 输入以 `/` 开头走 `/api/command` 命令路径，命令回显和输出会作为 system 气泡贴在聊天区里；`/help`、`/tools`、`/skills` 现在会以**可拖拽列宽的命令面板**渲染，左列可左右拖动，便于长 skill 名保持单行显示
- 聊天框底部在 `/help` 前新增了一个**图片生成**模式按钮；开启后发送入口不再走 `PoohAgent.ask_stream`，而是改调 AIHubMix 的图片模型 `gemini-3.1-flash-image-preview-free`。顶栏模型徽章会立即切到图片模型名，关闭该模式后恢复显示主文本模型 `gpt-5.4`
- transcript 现在会给每条消息额外落 `mode` 和 `model` 字段：普通文本链路记为 `mode=text`，图片生成链路记为 `mode=image_generation`，方便后续做统计、筛选或回放时明确区分同一 `session_id` 下的不同模型记录
- 用户消息里的附件不会再退化成原始解析正文：图片会渲染成带缩略图、文件名和体积信息的暖色卡片，PDF/Word/Excel/PPT 等文档在刷新后也会保持为文件卡片而不是把提取出的全文直接铺在用户消息里；图片卡片支持站内大图预览，点击背景或按 `Esc` 可关闭
- 输入框：Enter 发送，Shift+Enter 换行，⌘↵ 发送；textarea 高度自动增长；附件栏与引用条会自动收起/展开；composer 下方一排 chip 提供 `图片生成` `/help` `/tools` `/skills` `/clear` `/compact` 快捷入口，其中 slash 命令 **点击即直接发送执行**；`图片生成` 是一个可切换模式，启用后 placeholder 会变成“描述你想生成的图片…”，并把同一会话里的生成结果同时写进聊天区和左栏该 session 的产物归档；**agent 运行时输入框保持可用**——用户可随时输入并发送「插话」消息（走 `POST /api/session/inject`），消息会被推入运行中 session 的注入队列，agent 在当前工具执行完、下一轮 LLM 调用前自动读取并追加到 transcript，SSE 流会发一条 `injected` 事件通知前端（在助手气泡中内联显示琥珀色 USER 标签 + 插话内容）；placeholder 会切换为"继续发送消息，Agent 将在下一轮看到"提示；运行时也仍有 `停止` 按钮可用
- composer 已从聊天滚动容器中拆出，固定挂在中栏底部；同时聊天滚动区底部留白会跟随 composer 实际高度动态同步，避免流式输出（SSE）期间正文被底部输入框压住，看起来像“输入框插进回复中间”
- 文件上传：输入框左侧的 📎 按钮或拖放文件到输入区域均可添加附件；支持图片（png/jpg/gif/webp）、视频（mp4/mov/avi/webm）、PDF、Office 文档（docx/xlsx/pptx）、CSV、纯文本等；附件会显示为预览条，可单独移除。各类型文件的处理方式：
  - **图片** → base64 编码直接发给多模态 LLM
  - **视频** → 由于当前主流多模态模型（GPT-4o、GPT-4.1 等）尚不支持直接接收视频，需要拆解为模型能理解的格式：ffmpeg 提取关键帧（每 10 秒一帧，最多 4 帧）转为图片 + ffmpeg 提取音频后用 `faster-whisper` 本地模型语音转文字，最终以「关键帧图片 + 带时间戳的语音文本」形式发给 LLM
  - **PDF** → PyPDF2 / pdfplumber 提取文本
  - **Office 文档** → python-docx / openpyxl / python-pptx 提取文本和表格
  - **CSV/TSV** → pandas 读取表格数据
  - **纯文本** → 直接读取
- 当 `reply.compacted` 为真时，会插入一条 `[autocompact -> xxx/400k]` 系统气泡
- 产物归档现在直接内嵌到会话条目中：每个 `.convo` 行可展开显示该会话在 `workplace/output/<session_id>/` 下的所有文件（按类型图标着色：code / doc / image / table / chart），点击直接下载
- Web 前端的每条请求都显式绑定到一个 `session_id`；因此可以让会话 A 在后台继续跑，同时切到会话 B 再发起另一条任务，两条任务互不串 transcript
- 点击 `停止` 会调用 `/api/session/cancel` 给当前 `session_id` 发送取消信号；取消是 best-effort，会在上游 SSE/工具循环检测到后尽快结束
- transcript 读取时会自动修复“末尾只有 `assistant.tool_use`、但没有对应 `tool_result`”的坏记录，避免异常中断后下一轮继续对话时报错

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
| `truncated` | 跑满 `max_turns` 上限模型仍在要求工具调用，循环被强制截断；前端追加一条 `⚠️ 已达到 max_turns=N 上限...` 系统气泡，同时 `final_text` 末尾也会带上截断提示 |
| `cancelled` | 当前会话收到了取消请求，前端追加“已请求取消”提示，等待服务端尽快收尾 |
| `done` | 当前轮全部结束，前端置 `finished=true` 跳出 reader 循环 |
| `state` | 最后一帧带上新的 `session_id` / `usage`，用来同步右上角 |
| `error` | 任意异常，前端置错误状态并写系统气泡 |

tool-block 卡片的 `INPUT` / `OUTPUT` 都是可折叠的代码块，点击卡片头即可收起，方便长工具输出不挤占视线。

SSE 连接使用 `Connection: close` 并在服务端强制 `self.close_connection = True`，前端在收到 `done` 后主动 `reader.cancel()`，避免 reader 挂住导致输入框卡死。

取消时 transcript 的行为是：

- 已经完整落盘的 `user` / `assistant` / `tool_result` 会保留
- 前端那条“已发送取消请求”只是 UI 提示，不会写入 transcript
- 如果异常中断恰好发生在 `assistant(tool_use)` 已写入、`tool_result` 还没写入的窗口，`SessionStore.load_messages()` 会在下次读取时自动删掉这条悬空的 assistant 记录并回写 jsonl，保证上下文继续可用

### 文件下载

产物文件统一归档到左栏会话下方的 artifacts 列表，不再在 assistant 气泡里重复插一份下载卡片。

`/api/download?path=<相对路径>` 支持下载 `workplace/output/` 下的任意非隐藏文件，包括 Office 三件套、`.py`、PDF、CSV、图片、文本等。默认返回 `Content-Disposition: attachment`；当图片附件用于聊天区缩略图和大图预览时，会改用 `/api/download?path=<相对路径>&inline=1` 以内联方式返回。

### HTTP API

| Method | Path | 作用 |
| --- | --- | --- |
| GET  | `/api/state?session_id=<id>` | 当前 `session_id` / `model` / `usage` / `running`；`session_id` 可选，默认取当前激活会话 |
| GET  | `/api/messages?session_id=<id>` | 载入指定会话 transcript（已扁平化为纯文本）；`session_id` 可选 |
| GET  | `/api/sessions` | 列出当前 web channel 下的所有会话 |
| GET  | `/api/files` | 列出 `workplace/output/` 下的所有文件（跳过 `.git` 等隐藏目录），并按 `session_id` 分组返回 |
| GET  | `/api/download?path=<rel>[&inline=1]` | 下载或内联预览 `workplace/output/` 中的任意非隐藏文件；图片缩略图和 lightbox 走 `inline=1` |
| POST | `/api/upload` | multipart/form-data 文件上传，保存到 `workplace/uploads/`，返回服务端路径列表；单次上传限 100MB |
| POST | `/api/chat` | 同步调用 `agent.ask_for_session(session_key, text, session_id=...)`；同一 `session_id` 不允许重复并发 |
| POST | `/api/chat/stream` | **SSE 流式**接口；请求体里显式带 `session_id` 和可选 `files`（上传后的服务端路径数组），不同会话可并行跑，同一会话只允许一个运行中的任务 |
| POST | `/api/image/generate` | 图片生成接口；请求体里显式带 `session_id` 和 `text`，服务端调用 AIHubMix 的 `gemini-3.1-flash-image-preview-free`，把生成图片落到 `workplace/output/<session_id>/` 并同步回聊天区 |
| POST | `/api/command` | 走 `CommandProcessor`，支持 `/help` `/ctx` `/skills` `/compact` 等；请求体里可带 `session_id` |
| POST | `/api/session/new` | 新建一个 `session_id` |
| POST | `/api/session/switch` | 按 `session_id` 前缀切换（只在当前 web channel 的 slot 内匹配） |
| POST | `/api/session/clear` | 清空当前会话 transcript；运行中的会话不允许清空 |
| POST | `/api/session/rename` | 重命名会话标题；请求体 `{session_id, label}`，写入 `sessions.json` |
| POST | `/api/session/cancel` | 给指定 `session_id` 发送取消信号 |
| POST | `/api/session/inject` | 向正在运行的 `session_id` 注入一条用户消息（不中断推理，agent 下一轮自动读取） |
| POST | `/api/session/delete` | 删除指定 `session_id`，同步删除磁盘上的 transcript 目录和 `workplace/output/<session_id>/` 产物目录；若删的是最后一条会自动创建新会话 |
| POST | `/api/session/compact` | 强制触发一次 compact；运行中的会话不允许 compact |

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
