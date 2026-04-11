---
name: github-push
description: 将当前项目的本地改动推送到 GitHub 同名远程仓库。当用户说"推送到 GitHub""push 到远端""同步到 github""上传到 github""发布到 github"或类似意图，哪怕没有明确提到 commit、remote、分支，也应立即使用这个 skill。它会自动处理暂存、提交、创建远程仓库、关联 origin、设置上游分支等全部步骤。
---

# github-push

一键把当前工作目录的改动推送到 GitHub 上**同名**的远程仓库。无论本地是否已 commit、是否已配置 remote、远程仓库是否存在，都应能跑通。

## 依赖

- 本机已安装并登录 `gh` CLI（`gh auth status` 可验证）
- 当前目录是一个 git 仓库（或可被初始化为 git 仓库）

如果上述任一缺失，先停下来清晰地告诉用户缺什么，不要硬着头皮继续。

## 执行流程

按顺序执行。每一步前先用一句话告诉用户你在做什么，便于出问题时定位。

### 1. 确认处于 git 仓库

运行 `git rev-parse --show-toplevel`。如果失败，说明当前目录不是 git 仓库 —— 先 `git init`，并告知用户你做了这一步。

### 2. 确认有改动需要推送

并行跑：

- `git status --porcelain`（看工作区/暂存区）
- `git log @{u}.. 2>/dev/null`（看本地领先远端的提交，若没有 upstream 会失败，这是正常的）

如果工作区干净、且本地没有领先远端的 commit，直接告诉用户"没有改动需要推送"，结束。**不要**创建空 commit。

### 3. 自动 add + commit（仅当有未提交改动时）

有未提交改动时：

1. `git add -A` 暂存全部改动
2. 分析 `git diff --cached --stat` 和 `git diff --cached`（大 diff 可截断），理解这次改了什么
3. 生成一条**中文** commit message，遵循下面的"Commit message 规范"
4. 用 HEREDOC 形式执行 `git commit`：

   ```bash
   git commit -m "$(cat <<'EOF'
   <中文 commit message>
   EOF
   )"
   ```

如果 pre-commit hook 失败，修复根因后重新 `git add` + 新建 commit，**不要** `--amend`，也**不要** `--no-verify`。

### 4. 确认/创建远程仓库并关联 origin

跑 `git remote get-url origin 2>/dev/null`：

- **有 origin**：直接跳到下一步
- **没有 origin**：
  1. 取本地仓库根目录名作为仓库名：`basename "$(git rev-parse --show-toplevel)"`
  2. 跑 `gh repo view <仓库名> 2>/dev/null` 检查远端是否已存在同名仓库
     - 已存在：用 `gh repo view <仓库名> --json sshUrl -q .sshUrl` 拿到地址，`git remote add origin <url>` 关联
     - 不存在：用 `gh repo create <仓库名> --private --source=. --remote=origin` 创建并自动关联。**默认私有**，更安全；如果用户明确说过"公开"再改 `--public`

### 5. 推送当前分支

1. `git branch --show-current` 拿到当前分支名
2. 检查是否已有 upstream：`git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null`
   - **有**：`git push`
   - **没有**：`git push -u origin <branch>`（`-u` 会设置上游跟踪，之后直接 `git push` 即可）

### 6. 汇报结果

给用户一段简短的总结：

- 是否新建了 commit（附 commit message）
- 是否新建了远程仓库（附仓库地址）
- 推送的分支名和远端 URL（`gh repo view --json url -q .url` 可拿到）

## Commit message 规范

用中文，简明扼要，聚焦"为什么"和"做了什么"，不超过 50 字的标题行。如果改动涉及多个不相关的点，在标题下空一行写 2-4 条要点。

**示例：**

- `修复聊天界面滚动条在长对话下消失的问题`
- `新增 github-push skill 并完善相关文档`
- `重构 skills 加载逻辑`

**反例**（不要这样写）：

- `update` / `fix bug` / `wip`（信息量为零）
- `Add new feature to the chat interface that allows users to...`（英文、过长）
- `修改了 src/pooh_code/skills.py 的第 42 行`（描述的是文件变动，不是意图）

## 风险与边界

这个 skill 会自动执行 `git add -A`、创建 commit、创建远程仓库、推送到远端 —— 这些是**对外可见**的操作。因此：

- **绝不**使用 `--force` / `git push -f`。若非快进推送失败，停下来告诉用户冲突原因并让其决策,不要自作主张覆盖
- **绝不**自动推送到 `main` 之外的受保护分支上的别人的改动 —— 只推当前分支，且只推本地 commit
- 如果检测到暂存区里有疑似敏感文件（`.env`、`*.pem`、`credentials*`、`*.key`），**暂停**并告知用户，让其确认后再继续
- 如果 `gh auth status` 显示未登录，直接告知用户运行 `gh auth login`，不要尝试用其他方式鉴权
