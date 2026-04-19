---
name: skill-creator
description: 创建或更新本项目 agent 的 skill。当用户提到"新增 skill""创建技能""写一个新 skill""更新某个 skill""给 agent 加一个能力手册""新增 SKILL.md"等意图时使用。适用于在 workplace/runtime/skills/ 下新建或修改 skill，使当前项目里的 agent 能在后续请求中直接使用新技能。
---

# Skill 创建与更新

## 目标

只做一件事：在 `workplace/runtime/skills/` 下创建或更新可被当前项目 agent 自动发现的 skill。

如果任务对象是“外部/第三方 skill 导入到当前项目”，不要直接按本文创建或覆盖；应使用 `skill-install-review`。

## 本项目里的事实

- skill 的发现目录是 `workplace/runtime/skills/`
- 每个 skill 至少需要一个 `SKILL.md`
- 当前项目只读取 `SKILL.md` 的 frontmatter 中的 `name` 和 `description`
- services 已支持 skill 热刷新：新增、修改、删除 `SKILL.md` 后，不需要重启，下一次请求就会生效

## 默认做法

除非用户明确要求，否则：

1. 把 skill 创建在 `workplace/runtime/skills/<skill-name>/`
2. 先创建 `SKILL.md`
3. 当任务确实需要时，再额外增加 `scripts/`、`references/`、`assets/`
4. 不要创建 README、CHANGELOG、安装说明之类的多余文件

## 命名规则

- 目录名和 `name` 一致
- 只用小写字母、数字、连字符
- 名字尽量短，直接表达动作或领域
- 优先使用动词或明确能力词，例如：
  - `docx-create`
  - `github-push`
  - `skill-creator`

## 执行流程

### 1. 先理解这个 skill 要解决什么

在动手前先提炼三件事：

- 这个 skill 具体做什么
- 用户会怎么触发它
- 哪些内容是模型本来就会的，哪些内容才值得写进 skill

如果用户描述很模糊，优先从他的话里提炼出 2 到 4 个典型触发场景，再据此写 description。

### 2. 决定 skill 需要多大自由度

- 如果只是通用步骤和判断原则，用文字说明即可
- 如果某个过程容易写错、且会反复重复，给它配脚本
- 如果有固定模板、规范、表结构、API 文档，放进 `references/` 或 `assets/`

默认假设模型已经很强，只补充它不知道的项目内规则、路径约束、模板、流程和边界。

### 3. 创建目录和 `SKILL.md`

目录结构通常保持最小：

```text
workplace/runtime/skills/<skill-name>/
└── SKILL.md
```

当确实需要时再扩展：

```text
workplace/runtime/skills/<skill-name>/
├── SKILL.md
├── scripts/
├── references/
└── assets/
```

### 4. 写 frontmatter

`SKILL.md` 顶部必须有：

```yaml
---
name: skill-name
description: 这里写清楚 skill 做什么，以及用户在什么情况下应该触发它
---
```

要求：

- `description` 必须同时写“能力”和“触发场景”
- 把“什么时候该用这个 skill”写进 `description`
- 不要把触发规则只写在正文里，因为触发前模型只看得到 frontmatter 元数据

### 5. 写正文

正文只保留真正有用的操作信息，优先写：

- 核心目标
- 执行流程
- 路径约束
- 环境约束
- 风险边界
- 必要的最小示例

避免：

- 大段常识解释
- 重复 frontmatter 已表达的内容
- 无关文档
- 用户不需要的背景故事

### 6. 优先贴近本项目的实际

如果 skill 是给这个项目里的 agent 用，正文里优先写本项目自己的约束，例如：

- 文件该落到哪里
- 应该调用哪些现有工具
- 哪些目录不能碰
- 前端/后端/输出目录的约定
- 当前仓库已有的依赖、模板、脚本

不要写成脱离本项目环境的泛泛教程。

### 7. 创建或更新后做最小验证

至少检查：

1. `SKILL.md` 是否存在
2. frontmatter 是否包含 `name` 和 `description`
3. `name` 和目录名是否一致
4. 正文是否真的能指导 agent 执行，不是空模板
5. 没有引入多余文件

如果是更新已有 skill，额外检查新内容是否和原有规则冲突。

## 推荐模板

```markdown
---
name: my-skill
description: 说明这个 skill 做什么，以及用户在哪些场景下应该触发它。
---

# my-skill

## 目标

一句话说清楚要完成什么。

## 核心流程

1. 第一步
2. 第二步
3. 第三步

## 关键约束

- 路径约束
- 工具约束
- 输出约束

## 示例

给一个最小可执行例子。

## 风险与边界

- 什么能做
- 什么不能做
```

## 更新已有 skill 时

- 先读现有 `SKILL.md`
- 尽量在原结构上收敛修改，不要无意义重写
- 如果新增了脚本或参考文件，要在 `SKILL.md` 里明确说明何时读取、何时执行
- 如果 skill 触发词变了，优先更新 `description`

## 完成后的交付

完成后告诉用户：

- skill 名字
- skill 路径
- 本次新增或修改了什么
- 该 skill 现在如何触发

如果这个 skill 是创建在 `workplace/runtime/skills/` 下，可直接说明：它会在下一次请求时自动生效，无需重启服务。
