---
name: ui-ux-pro-max
description: 提供 UI/UX 设计检索、设计系统建议和前端实现指导。当用户要求设计页面、优化体验、制定设计系统、给出现有界面评审意见，或需要把 UI/UX 建议落成 HTML/CSS/JS、React、Next.js、Vue、Svelte、Tailwind 等前端代码时使用。
---

# UI/UX Pro Max

## 目标

在当前项目里提供三类能力：

1. UI/UX 方案产出：布局、视觉方向、交互、状态设计
2. 设计知识检索：从本 skill 自带的 `data/` 知识库中检索样式、配色、字体、UX 规则和栈规范
3. 结构化设计系统建议：用本地脚本生成统一的设计系统文本输出

## 本项目内的约束

- skill 安装位置固定为 `workplace/runtime/skills/ui-ux-pro-max/`
- 所有路径都按 `workplace/` 为命令执行根目录来写
- 运行脚本时优先使用 `uv run python`
- 不要生成或写入设计系统文件；只输出到终端或对话

## 1) 需求分流

只在必要时补问关键信息：

- Target platform: web / iOS / Android / desktop
- Stack (if code changes): React/Next/Vue/Svelte, CSS/Tailwind, component library
- Goal and constraints: conversion, speed, brand vibe, accessibility level (WCAG AA?)
- What you have: screenshot, Figma, repo, URL, user journey

用户如果说“全部都要”，默认按这四个交付顺序输出：UI 方向、UX 流程、设计系统、代码实现建议。

## 2) 交付方式

输出时要具体到组件、状态、间距、字体、交互，不要停留在空泛建议。

- UI concept + layout: 明确视觉方向、网格、颜色、层级和关键页面结构
- UX flow: 说明关键路径、错误态、空态、加载态、边界情况
- Design system: 给出颜色、字体、间距、圆角、阴影、组件规则、a11y 要点
- Implementation plan: 细化到文件级修改、组件拆分和验收标准

## 3) 使用内置资料

优先读取 skill 自带内容，不要先去外部找泛泛资料：

- 设计知识库：`data/`
- 参考说明：`references/skill-content.md`

按 skill 目录内相对路径理解这些引用；只有在需要时才打开对应文件，不要整包通读。

## 4) 脚本使用

需要快速产出结构化设计系统建议时，运行：

```bash
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "saas dashboard" --design-system
```

需要域检索时，运行：

```bash
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "glassmorphism fintech" --domain style
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "animation accessibility" --domain ux
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "responsive form" --stack react
```

不要使用任何写文件参数；这个本地版本已经禁用持久化输出。

## 输出标准

- Default to ASCII-only tokens/variables unless the project already uses Unicode.
- Include: spacing scale, type scale, 2-3 font pair options, color tokens, component states.
- Always cover: empty/loading/error, keyboard navigation, focus states, contrast.
