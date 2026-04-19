---
name: skill-install-review
description: 审查并适配准备安装到当前agent的第三方 skill。当用户提到“检查这个 skill 能不能装”“审查新 skill”“适配到我agent里”“看看有没有危险”“把这个 skill 安装到我的agent”等场景时使用。适用于在安装前检查安全性、依赖、路径、运行方式，并把 skill 调整为符合当前项目 runtime 约束的版本。
---

# skill-install-review

## 目标

只做一件事：在第三方 skill 安装到 `workplace/runtime/skills/` 之前，完成安全审查、项目适配和最小验证。

## 适用场景

- 用户给一个外部 skill 目录、压缩包解压目录或仓库副本，让你判断能不能装
- 用户要把一个现成 skill 改造成适合当前项目 runtime 的版本
- 用户要求检查新 skill 有没有危险逻辑、依赖冲突、绝对路径或不适合 Linux/`uv` 的写法

## 本项目里的事实

- skill 发现目录是 `workplace/runtime/skills/`
- skill 至少需要一个 `SKILL.md`
- 当前项目实际使用 `uv run`、`uv add`
- 服务器目标环境是 Linux，因此 skill 不能依赖本机绝对路径
- 路径说明优先按 `workplace/` 为命令执行根目录来写

## 默认执行流程

### 1. 先看结构，不急着安装

先检查候选 skill 目录结构，至少确认：

- 有没有 `SKILL.md`
- 有没有 `scripts/`、`references/`、`assets/`、`data/`
- 有没有 `package.json`、`pyproject.toml`、`requirements.txt`、shell 脚本或其他可执行入口

优先用快速只读命令：

- `find`
- `rg --files`
- `sed -n`

### 2. 审查可执行部分和危险点

重点看三类内容：

- 运行时代码：`scripts/*.py`、`*.sh`、`*.js`
- 说明文件里的命令示例：`SKILL.md`、`references/*`
- 依赖与安装文件：`pyproject.toml`、`package.json`、`requirements.txt`

优先搜索这些危险特征：

- 写文件、删文件、改权限
- 子进程、shell 执行
- 网络请求、下载、上传
- 安装钩子
- 环境变量读取
- 绝对路径

常用搜索模式示例：

```bash
rg -n "(postinstall|preinstall|subprocess|os\.system|exec\(|spawn\(|requests|httpx|urllib|socket|open\(|write\(|rm -rf|chmod|chown|/Users/|/home/|C:\\\\)" <skill-dir>
```

### 3. 判断哪些能力值得保留

不要默认整包照搬。拆成三类判断：

- `提示词/说明`：通常应保留，这是 skill 的核心
- `数据/参考资料`：有价值时保留
- `脚本/自动化能力`：只在确实必要、且安全可控时保留

### 4. 适配到当前项目

把 skill 改成符合当前项目的版本：

- 安装路径改为 `workplace/runtime/skills/<skill-name>/`
- 文档中的命令统一按 `workplace/` 为根来写
- Python 脚本调用优先写成 `uv run python runtime/skills/<skill-name>/scripts/...`
- 禁止写绝对路径
- 如果需要额外安装第三方依赖，使用`uv add`安装

### 5. 清理上游噪音

默认清理这些内容：

- `.DS_Store`
- `__pycache__/`
- 与当前项目无关的 README、发布元信息、商店元数据
- 重复数据目录
- 会误导 agent 的旧说明文档

不要保留会让 agent 读到过时指令的文件。

### 6. 最小验证

安装或修改后，至少做这些验证：

1. `SKILL.md` 存在，且 frontmatter 有 `name` 和 `description`
2. `name` 与目录名一致
3. 脚本可编译或可运行
4. 文档中的关键命令能在当前仓库下执行
5. 危险参数已经删除或报错
6. 没有残留绝对路径

常用验证方式：

```bash
uv run python3 -m py_compile workplace/runtime/skills/<skill-name>/scripts/*.py
uv run python runtime/skills/<skill-name>/scripts/<entry>.py --help
rg -n "/Users/|/home/|C:\\\\|--persist|output-dir|python3 " workplace/runtime/skills/<skill-name>
```

如果当前 skill 要在 `workplace/` 目录下运行脚本，验证命令也要在 `workplace/` 下执行。

## 输出要求

完成后给用户的结论至少包括：

- 这个 skill 能不能装
- 风险点是什么
- 你改了什么
- 还剩什么边界或注意事项
- 现在应该如何触发这个 skill

如果没有发现问题，也要明确说明“未发现明显危险逻辑”，不要只给笼统结论。

## 风险边界

- 不要盲目执行第三方 skill 里的安装命令
- 不要默认保留写文件、联网、子进程能力
- 不要把本机路径写进文档或代码
- 不要因为“原项目这么写”就照搬到当前 runtime
- 如果发现明显恶意行为或高风险逻辑，先停下来告诉用户，不要继续安装

## 最小模板

当你实际执行这类任务时，优先按这个顺序汇报：

1. 结构判断：它是什么 skill，包含什么
2. 风险审查：有没有危险逻辑
3. 项目适配：需要改哪些路径、命令、依赖
4. 验证结果：什么已验证通过，什么没验证
