---
name: pptx-create
description: 生成或编辑 PowerPoint 演示文稿（.pptx 文件）。当用户提到"PPT""幻灯片""演示文稿""slides""deck""pptx""汇报""展示""路演"等需要创建或修改演示文档时使用此 skill。适用于从零制作专业幻灯片、编辑现有 PPT 的内容或样式、制作项目汇报/产品介绍/工作总结等各类演示场景。只要最终交付物是 .pptx 文件就应使用。不用于 Word 文档、电子表格或其他格式。
---

# PPTX 演示文稿生成

## 核心流程

1. 检查是否有相关依赖，如果没有，那么安装依赖
2. 编写 Python 脚本生成 .pptx
3. 运行脚本，输出到 `workplace/output/`
4. 告知用户文件已生成

## 环境准备

使用 `python-pptx` 库生成演示文稿。检查是否有相关依赖，如果没有，需安装：

```bash
uv add python-pptx
```

如果安装失败，尝试：


## 输出路径

所有生成的文件**必须**写入 `workplace/output/` 目录。

## 快速参考

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Cm, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation()
prs.slide_width = Cm(33.867)   # 16:9 宽屏
prs.slide_height = Cm(19.05)

# === 封面页 ===
slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白布局

# 背景色
bg = slide.background
fill = bg.fill
fill.solid()
fill.fore_color.rgb = RGBColor(0x1E, 0x27, 0x61)  # 深蓝

# 标题
txBox = slide.shapes.add_textbox(Cm(3), Cm(6), Cm(28), Cm(4))
tf = txBox.text_frame
tf.word_wrap = True
p = tf.paragraphs[0]
p.text = '项目汇报'
p.font.size = Pt(44)
p.font.bold = True
p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
p.alignment = PP_ALIGN.LEFT

# 副标题
p2 = tf.add_paragraph()
p2.text = '2024年第四季度'
p2.font.size = Pt(20)
p2.font.color.rgb = RGBColor(0xCA, 0xDC, 0xFC)
p2.alignment = PP_ALIGN.LEFT

# === 内容页 ===
slide2 = prs.slides.add_slide(prs.slide_layouts[6])

# 页面标题
title_box = slide2.shapes.add_textbox(Cm(2), Cm(1.5), Cm(30), Cm(2))
tf = title_box.text_frame
p = tf.paragraphs[0]
p.text = '核心指标'
p.font.size = Pt(32)
p.font.bold = True
p.font.color.rgb = RGBColor(0x1E, 0x27, 0x61)

# 内容文本框
content_box = slide2.shapes.add_textbox(Cm(2), Cm(4), Cm(14), Cm(12))
tf = content_box.text_frame
tf.word_wrap = True
for item in ['月活跃用户 120 万', '收入同比增长 35%', '客户满意度 4.8/5.0']:
    p = tf.add_paragraph()
    p.text = f'• {item}'
    p.font.size = Pt(18)
    p.space_after = Pt(12)
    p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

prs.save('workplace/output/演示文稿.pptx')
```

## 设计原则

制作 PPT 时应追求专业美观，避免单调的文字堆叠。

### 配色方案

根据主题选择合适的配色，不要默认蓝色。推荐方案：

| 风格 | 主色 | 辅色 | 点缀色 |
|------|------|------|--------|
| 商务深蓝 | `1E2761` | `CADCFC` | `FFFFFF` |
| 自然绿 | `2C5F2D` | `97BC62` | `F5F5F5` |
| 暖色系 | `B85042` | `E7E8D1` | `A7BEAE` |
| 深灰极简 | `36454F` | `F2F2F2` | `212121` |
| 青色信任 | `028090` | `00A896` | `02C39A` |
| 樱桃红 | `990011` | `FCF6F5` | `2F3C7E` |

### 版式要求

- **封面和结尾**用深色背景，内容页用浅色（"三明治"结构）
- **每页都要有视觉元素**——不要纯文字页面
- **标题 32-44pt**，正文 14-18pt，标注 10-12pt
- **留白充足**——边距至少 1.5cm，内容块间距 0.5cm+
- **不要重复同一版式**——交替使用双栏、卡片、数据大字等
- **正文左对齐**，只有标题居中

### 常用版式模式

1. **双栏**：左文字 + 右图示/数据
2. **大数字**：关键数据用 48-72pt 大字展示
3. **卡片网格**：2x2 或 3x2 的信息卡片
4. **时间线**：流程步骤用箭头连接
5. **对比**：左右对比（优劣、前后、AB方案）

## 常用形状和元素

### 矩形色块（卡片）

```python
shape = slide.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE,
    Cm(2), Cm(5), Cm(13), Cm(10)
)
shape.fill.solid()
shape.fill.fore_color.rgb = RGBColor(0xF2, 0xF2, 0xF2)
shape.line.fill.background()  # 无边框
shape.shadow.inherit = False   # 无阴影
# 圆角
shape.adjustments[0] = 0.05

# 在形状内添加文字
tf = shape.text_frame
tf.word_wrap = True
tf.margin_left = Cm(0.8)
tf.margin_right = Cm(0.8)
tf.margin_top = Cm(0.5)
p = tf.paragraphs[0]
p.text = '卡片标题'
p.font.size = Pt(20)
p.font.bold = True
```

### 线条

```python
from pptx.util import Emu

line = slide.shapes.add_connector(
    1,  # straight connector
    Cm(2), Cm(4), Cm(32), Cm(4)
)
line.line.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
line.line.width = Pt(1)
```

### 表格

```python
rows, cols = 4, 3
table_shape = slide.shapes.add_table(rows, cols, Cm(2), Cm(5), Cm(30), Cm(8))
table = table_shape.table

# 设置列宽
table.columns[0].width = Cm(10)
table.columns[1].width = Cm(10)
table.columns[2].width = Cm(10)

# 填充数据
table.cell(0, 0).text = '指标'
table.cell(0, 1).text = '本期'
table.cell(0, 2).text = '上期'

# 表头样式
for col_idx in range(cols):
    cell = table.cell(0, col_idx)
    cell.fill.solid()
    cell.fill.fore_color.rgb = RGBColor(0x1E, 0x27, 0x61)
    for paragraph in cell.text_frame.paragraphs:
        paragraph.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        paragraph.font.bold = True
        paragraph.font.size = Pt(14)
```

### 图片

```python
# 插入本地图片
slide.shapes.add_picture('workplace/output/chart.png', Cm(18), Cm(4), Cm(14), Cm(10))
```

## 图表（需 matplotlib 配合）

python-pptx 内置图表功能有限，推荐先用 matplotlib 生成图表图片再插入：

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(['Q1', 'Q2', 'Q3', 'Q4'], [120, 150, 180, 210])
ax.set_title('季度营收')
fig.savefig('workplace/output/chart.png', dpi=150, bbox_inches='tight', transparent=True)
plt.close()

# 然后在 PPT 中插入
slide.shapes.add_picture('workplace/output/chart.png', Cm(17), Cm(4), Cm(15))
```

## 编辑现有 PPT

```python
prs = Presentation('workplace/input.pptx')

# 遍历幻灯片
for slide in prs.slides:
    for shape in slide.shapes:
        if shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                print(paragraph.text)
                # 替换文本
                for run in paragraph.runs:
                    if '旧文本' in run.text:
                        run.text = run.text.replace('旧文本', '新文本')

# 删除幻灯片
rId = prs.slides._sldIdLst[2].get('r:id')  # 第3张
prs.part.drop_rel(rId)
del prs.slides._sldIdLst[2]

prs.save('workplace/output/修改后.pptx')
```

## 重要提醒

- **所有文件输出到 `workplace/output/`**
- 用 `write_file` 写 Python 脚本，用 `bash` 执行它，python解释器在/Users/wangyc/Desktop/projects/Pooh-code/.venv/bin/python
- 生成完毕后告知用户文件名，前端自动显示下载按钮
- **追求设计感**——每页都要有视觉层次和配色，杜绝纯文字白底
- 使用空白布局 `prs.slide_layouts[6]` 获得最大排版自由度
- 字体推荐：标题用 `Arial Black` 或粗体 `Arial`，正文用 `Arial` 或 `Calibri`
- 如果需要生成图表，先用 matplotlib 生成 PNG 再插入 PPT
- 演示文稿默认 16:9 宽屏比例（33.867cm x 19.05cm）
