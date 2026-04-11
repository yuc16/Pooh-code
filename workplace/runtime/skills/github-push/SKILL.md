---
name: github-push
description: 将当前项目的本地改动统一推送到 GitHub 同名远程仓库的 temp 分支。当用户说"推送到 GitHub""push 到远端""同步到 github""上传到 github""发布到 github"或类似意图，哪怕没有明确提到 commit、remote、分支，也应立即使用这个 skill。它会自动处理暂存、提交、创建远程仓库、关联 origin，并把本地 HEAD 推送到远端 temp 分支（远端没有则自动新建）。
---

# github-push

一键把当前工作目录的改动推送到 GitHub 上**同名**远程仓库的 **`temp` 分支**。无论本地是否已 commit、是否已配置 remote、远程仓库是否存在、远端是否已有 `temp` 分支，都应能跑通。

**为什么统一推到 `temp`**：这个 skill 的定位是"随手同步一下给云端看看",不直接污染 `main` 或任何功能分支。所有推送都落到一个公共的 `temp` 分支上,作为云端的临时中转区,避免误推到正式分支。

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
- `git fetch origin temp 2>/dev/null && git log origin/temp..HEAD --oneline 2>/dev/null`（看本地 HEAD 相比远端 temp 有哪些新 commit；远端 temp 不存在时失败是正常的，意味着首次推送）

如果工作区干净、且本地 HEAD 和远端 `temp` 完全一致，直接告诉用户"没有改动需要推送"，结束。**不要**创建空 commit。

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

### 5. 推送到远端 temp 分支

**不管本地当前在哪个分支**，一律把本地 HEAD 推到远端 `temp`。用 refspec 的形式：

```bash
git push origin HEAD:temp
```

这条命令的含义：把本地 HEAD 的内容推到 `origin` 的 `temp` 分支。远端 `temp` 不存在时会自动创建；存在时会做快进更新。**不要**改动本地当前分支，也**不要**在本地创建 `temp` 分支 —— 本地分支保持原样，`temp` 只是云端的落点。

**处理非快进推送失败**：如果远端 `temp` 上有本地没有的 commit（别人推过，或之前的会话推过不同内容），`git push origin HEAD:temp` 会失败并提示 non-fast-forward。此时**停下来**，告诉用户远端 `temp` 的 HEAD 和本地有分叉，列出两边各自最近几条 commit，让用户决定：

- 是要先 `git fetch origin temp && git merge origin/temp` 合并再推
- 还是确认远端 `temp` 上的旧内容可以丢弃，由用户显式授权后再做 `git push origin HEAD:temp --force-with-lease`

**绝不**自作主张 force push。

### 6. 汇报结果

给用户一段简短的总结：

- 是否新建了 commit（附 commit message）
- 是否新建了远程仓库（附仓库地址）
- 本地 HEAD 已推到 `origin/temp`，并附上远端 temp 分支的 URL，方便用户点开查看：
  `https://github.com/<owner>/<repo>/tree/temp`（owner/repo 从 `gh repo view --json nameWithOwner -q .nameWithOwner` 拿）

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

- **绝不**使用 `--force` / `git push -f`。若非快进推送失败，停下来告诉用户冲突原因并让其决策,不要自作主张覆盖。只有在用户明确授权后,才可以用 `--force-with-lease`（比 `-f` 更安全,会检测远端是否在你 fetch 之后被他人更新过）
- 这个 skill 的推送目标永远是远端 `temp` 分支,**绝不**推到 `main` 或任何其他分支。如果用户要的是推到具体功能分支,应提示用户这不是 github-push 的职责
- 如果检测到暂存区里有疑似敏感文件（`.env`、`*.pem`、`credentials*`、`*.key`），**暂停**并告知用户，让其确认后再继续
- 如果 `gh auth status` 显示未登录，直接告知用户运行 `gh auth login`，不要尝试用其他方式鉴权
