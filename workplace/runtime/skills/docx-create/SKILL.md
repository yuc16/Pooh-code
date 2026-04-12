---
name: docx-create
description: 生成或编辑 Word 文档（.docx 文件）。当用户提到"Word 文档""docx""报告""信函""简历""合同""备忘录"等需要生成 .docx 格式的专业文档时使用此 skill。也适用于把现有内容整理成格式化的 Word 文档、生成带目录/页眉页脚/表格/图片的专业排版文档。只要最终交付物是 .docx 文件就应使用。不用于电子表格、PPT 或 PDF 等其他格式。
---

# DOCX 文档生成

## 核心流程

1. 检查是否有相关依赖，如果没有，那么安装依赖
2. 用 `write_file(path="scripts/...")` 编写 Python 脚本生成 .docx
3. 用 `bash` 在 `cwd=workplace` 下运行脚本，输出到 `output/`
4. 告知用户文件已生成

## 环境准备

使用 `python-docx` 库生成文档。检查是否有相关依赖，如果没有，需安装：

```bash
uv add python-docx
```

## 输出路径

所有生成的文件**必须**写入当前会话目录 `output/<session_id>/`（对应项目里的 `workplace/output/<session_id>/`）。`session_id` 从 Runtime 里的 `current_session_id` 读取。例如：

```python
output_path = f"output/{session_id}/报告.docx"
```

## 快速参考

```python
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT

doc = Document()

# 页面设置（A4）
section = doc.sections[0]
section.page_width = Cm(21)
section.page_height = Cm(29.7)
section.top_margin = Cm(2.54)
section.bottom_margin = Cm(2.54)
section.left_margin = Cm(3.17)
section.right_margin = Cm(3.17)

# 设置默认字体
style = doc.styles['Normal']
font = style.font
font.name = 'Arial'
font.size = Pt(12)

# 标题
doc.add_heading('文档标题', level=0)
doc.add_heading('一级标题', level=1)
doc.add_heading('二级标题', level=2)

# 段落
para = doc.add_paragraph('正文内容')
para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY  # 两端对齐

# 加粗和斜体
run = para.add_run('加粗文本')
run.bold = True

# 列表
doc.add_paragraph('项目一', style='List Bullet')
doc.add_paragraph('项目二', style='List Bullet')
doc.add_paragraph('第一步', style='List Number')
doc.add_paragraph('第二步', style='List Number')

# 表格
table = doc.add_table(rows=3, cols=3, style='Table Grid')
table.alignment = WD_TABLE_ALIGNMENT.CENTER
# 表头
hdr = table.rows[0].cells
hdr[0].text = '列1'
hdr[1].text = '列2'
hdr[2].text = '列3'
# 设置列宽
for cell in table.columns[0].cells:
    cell.width = Cm(4)

# 图片（如有本地图片）
# doc.add_picture(f'output/{session_id}/image.png', width=Inches(4))

# 分页
doc.add_page_break()

# 页眉页脚
header = section.header
header.paragraphs[0].text = '页眉文本'
footer = section.footer
footer.paragraphs[0].text = '页脚文本'

# 保存
doc.save(f'output/{session_id}/文档.docx')
```

## 中文字体处理

python-docx 默认字体可能不支持中文。推荐以下方式设置中文字体：

```python
from docx.oxml.ns import qn

# 设置段落中文字体
run = para.add_run('中文内容')
run.font.name = 'Arial'
run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')  # 或 '微软雅黑'

# 设置全局默认中文字体
style = doc.styles['Normal']
style.font.name = 'Arial'
style._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
```

注意：macOS 上常见中文字体有 `PingFang SC`、`STSong`、`STHeiti`。Windows 上有 `宋体`、`微软雅黑`。跨平台安全选择是 `Arial`（西文）+ 不设中文字体（让 Word 自动选择）。

## 高级功能

### 目录（需用户在 Word 中更新）

```python
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

paragraph = doc.add_paragraph()
run = paragraph.add_run()
fldChar = OxmlElement('w:fldChar')
fldChar.set(qn('w:fldCharType'), 'begin')
run._r.append(fldChar)

instrText = OxmlElement('w:instrText')
instrText.set(qn('xml:space'), 'preserve')
instrText.text = 'TOC \\o "1-3" \\h \\z \\u'
run2 = paragraph.add_run()
run2._r.append(instrText)

fldChar2 = OxmlElement('w:fldChar')
fldChar2.set(qn('w:fldCharType'), 'end')
run3 = paragraph.add_run()
run3._r.append(fldChar2)
```

### 合并单元格

```python
cell_a = table.cell(0, 0)
cell_b = table.cell(0, 2)
cell_a.merge(cell_b)  # 合并第一行的前3个单元格
```

### 设置表格单元格背景色

```python
from docx.oxml.ns import nsdecls
from docx.oxml import parse_xml

shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="4472C4"/>')
cell._tc.get_or_add_tcPr().append(shading)
```

## 重要提醒

- **当前会话的所有 agent 文件都放到 `output/<session_id>/`**
- `session_id` 从 Runtime 里的 `current_session_id` 读取；当前目录也会在 Runtime 的 `session_output_dir_relative_to_workplace` 给出
- 用 `write_file(path=f"output/{session_id}/gen_docx.py")` 写 Python 脚本，用 `bash` 在 `cwd=workplace` 下执行它，python解释器在/Users/wangyc/Desktop/projects/Pooh-code/.venv/bin/python
- 最终 `.docx` 也写到同一个 `output/<session_id>/` 目录；不要写到其他会话目录
- 生成完毕后告知用户文件名和路径，前端会自动显示下载按钮
- 对于复杂文档，先在脚本中组织好内容结构再一次性生成，避免反复修改
