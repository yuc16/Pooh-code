---
name: github-push
description: 把 agent 产出专区 workplace/output/ 里的改动推送到 GitHub 的 temp 分支。当用户说"推送到 github""push 到远端""同步到 github""上传到 github""发布一下""把结果发上去"或任何表达"把 agent 刚刚生成的东西送到云端"意图时,哪怕没明确提 commit、remote、分支,也应立即使用此 skill。它处理 workplace/output/ 内的暂存、提交、推送到远端 temp 分支,**绝不**触碰项目主仓库 src/main 分支。
---

# github-push

**只负责一件事**:把 `workplace/output/` 里的 agent 产出推送到 GitHub 远端 `temp` 分支。

## 为什么这样设计

本项目有两个物理隔离的 git 仓库:

| 仓库 | 位置 | 分支 | 谁在用 |
| --- | --- | --- | --- |
| 主仓库 | 项目根 `.git/` | `main` | 人类开发者手动维护项目源码 |
| 产出仓库 | `workplace/output/.git/` | `temp` | agent 推送自己生成的文件 |

两者在 GitHub 上指向**同一个 repo**(`yuc16/Pooh-code`),但分支历史完全独立(orphan 起源)。这样 agent 频繁产出的文件不会污染 main 分支的源码提交历史,用户也能通过切到 temp 分支看到 agent 最近的所有产出。

**你(agent)永远不应尝试对项目根的 main 分支做 commit/push**。main 分支是用户自己的阵地,沙箱也会直接拦住你。

## 前提假设

- `workplace/output/` 目录已存在,里面有一个独立的 git 仓库(已 `git init`、已配 `origin`、已有初始 commit)。这是由项目一次性 bootstrap 完成的,你不需要管
- 如果进到 `workplace/output/` 后 `git status` 报"not a git repository",立刻**停下**并告诉用户"产出仓库未初始化,请先运行 bootstrap",不要自己 init

## 执行流程

所有 git 命令必须在 `workplace/output/` 目录下执行。用 `bash` 工具的 `cwd` 参数指定,或者命令前加 `cd workplace/output &&`。每一步前用一句话告诉用户你在做什么。

### 1. 进入产出目录并核对身份

```bash
cd workplace/output && git rev-parse --show-toplevel && git remote get-url origin
```

确认:
- `rev-parse` 返回的路径以 `workplace/output` 结尾(不是项目根)
- `origin` 指向 `github.com/<user>/Pooh-code`(或用户配置的其他仓库)

如果任一项不对,**停下**告诉用户,不要继续。

### 2. 看看有没有改动需要推送

并行跑:

- `git status --porcelain` —— 工作区/暂存区的未提交改动
- `git fetch origin temp && git log origin/temp..HEAD --oneline` —— 本地 HEAD 比远端 temp 超前的 commit

如果两边都空(工作区干净 + 本地 HEAD 和远端 temp 完全一致),告诉用户"产出仓库里没有改动需要推送",结束。**不要**创建空 commit。

### 3. 暂存并生成中文 commit message(仅当有未提交改动时)

1. `git add -A`
2. 看 `git diff --cached --stat` 和 `git diff --cached`(大 diff 可截断),理解这次改了什么。**绝大多数情况下这些都是 agent 自己刚刚生成的文件**,你对它们的内容应该有清晰的认知
3. 生成一条**中文** commit message,遵循下面的"Commit message 规范"
4. 用 HEREDOC 形式 commit:

   ```bash
   git commit -m "$(cat <<'EOF'
   <中文 commit message>
   EOF
   )"
   ```

### 4. 推送到远端 temp 分支

```bash
git push origin HEAD:temp
```

这是快进更新。远端 `temp` 已由 bootstrap 创建,正常情况下应成功。

**处理非快进失败**:如果 push 提示 non-fast-forward,说明远端 `temp` 有本地没有的 commit(可能是之前的会话推过别的内容,或者被外部修改过)。此时**停下来**:

1. 列出本地和远端各自最近几条 commit(`git log HEAD --oneline -5` 和 `git log origin/temp --oneline -5`)
2. 告诉用户分叉了,让他决定:
   - 先 `git fetch origin temp && git merge origin/temp` 合并再推
   - 或显式授权 `git push origin HEAD:temp --force-with-lease` 覆盖旧内容

**绝不**自作主张 force push。

### 5. 汇报结果

简短总结:

- 本次 commit 的 message
- 推送的 commit 哈希(`git rev-parse --short HEAD`)
- 远端 temp 分支的查看地址:`https://github.com/<owner>/<repo>/tree/temp`
  (owner/repo 从 `git remote get-url origin` 解析,或用 `gh repo view --json nameWithOwner -q .nameWithOwner`)

## Commit message 规范

用中文,简明扼要,聚焦"这次产出了什么"和"对应什么任务",标题行不超过 50 字。多项不相关改动时在标题下空一行写 2-4 条要点。

**示例:**

- `生成用户要求的销售数据分析报告`
- `输出本周飞书值班排班表 v2`
- `新增实验脚本和对应的运行日志`

**反例:**

- `update` / `wip` / `fix`(信息量为零)
- `修改了 workplace/output/reports/foo.md 的第 3 行`(描述的是文件变动,不是意图)
- 任何英文标题

## 风险与边界

- **物理边界**:这个 skill 的所有 git 操作都必须在 `workplace/output/` 里。如果你发现自己在项目根跑 git 命令,你就已经错了,立即停下
- **分支边界**:推送目标永远是远端 `temp`,**绝不**推到 `main` 或任何其他分支
- **绝不 force push**。冲突时停下让用户决策
- **敏感文件检测**:如果暂存区里出现 `.env`、`*.pem`、`credentials*`、`*.key`、`id_rsa*` 等疑似敏感文件,**暂停**并告知用户,让其确认后再继续。一般情况下 agent 不应该把这类文件写到 output 里
- **沙箱前提**:本 skill 不需要任何沙箱豁口,因为 `workplace/output/` 整个都在沙箱允许写入的范围内(写入 `workplace/output/.git/index` 等同于写入 workplace 内的普通文件)
