# UI/UX Pro Max Reference

这个文件是给当前项目内 agent 用的快速参考，不是上游安装文档。

## 运行方式

命令统一从 `workplace/` 目录执行，使用 `uv run python`，不要写绝对路径：

```bash
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "<query>" --design-system
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain style
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "<query>" --stack react
```

## 推荐工作流

### 1. 先生成结构化设计系统建议

```bash
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "beauty spa wellness service elegant" --design-system -p "Serenity Spa"
```

这一步会聚合 `product`、`style`、`color`、`landing`、`typography` 五类数据，输出：

- pattern
- style
- colors
- typography
- key effects
- anti-patterns

### 2. 按需补充细分检索

```bash
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "animation accessibility" --domain ux
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "elegant luxury serif" --domain typography
uv run python runtime/skills/ui-ux-pro-max/scripts/search.py "layout responsive form" --stack html-tailwind
```

## 可用检索域

| Domain | 用途 |
|--------|------|
| `product` | 产品类型推荐 |
| `style` | UI 风格、效果、关键词 |
| `color` | 配色方案 |
| `typography` | 字体组合 |
| `landing` | 页面结构、CTA 策略 |
| `chart` | 图表类型建议 |
| `ux` | UX 规则、反模式、可访问性 |
| `react` | React/Next 性能建议 |
| `web` | Web 交互与语义化建议 |

## 可用栈

`html-tailwind`、`react`、`nextjs`、`astro`、`vue`、`nuxtjs`、`nuxt-ui`、`svelte`、`swiftui`、`react-native`、`flutter`、`shadcn`、`jetpack-compose`

## 约束

- 不要使用任何写文件持久化参数；本项目内版本已禁用
- 不要把这个 skill 当成依赖安装器；它不是 npm/pip 包
- 需要引用数据或参考文档时，优先用 skill 目录内相对路径：`data/`、`references/`
