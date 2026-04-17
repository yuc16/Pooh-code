---
name: xlsx-create
description: 生成或编辑 Excel 电子表格（.xlsx 文件）。当用户提到"表格""电子表格""Excel""xlsx""数据分析""财务模型""排班表""统计报表"等需要创建或处理表格数据时使用此 skill。适用于从零创建带格式的 Excel 文件、分析现有数据并输出结果、生成带公式和图表的专业表格。只要最终交付物是 .xlsx 文件就应使用。不用于 Word 文档、PPT 或其他格式。
---

# XLSX 电子表格生成

## 核心流程

1. 检查是否有相关依赖，如果没有，那么安装依赖
2. 用 `write_file(path="scripts/...")` 编写 Python 脚本生成 .xlsx
3. 用 `bash` 在 `cwd=workplace` 下运行脚本，输出到 `output/`
4. 告知用户文件已生成

## 环境准备

使用 `openpyxl` 生成带格式的 Excel，`pandas` 做数据分析。检查是否有相关依赖，如果没有，需安装：

```bash
uv add openpyxl pandas
```

## 输出路径

所有生成的文件**必须**写入当前会话目录 `output/<session_id>/`（对应项目里的 `workplace/output/<session_id>/`）。`session_id` 从 Runtime 里的 `current_session_id` 读取。

## 关键原则：使用公式而非硬编码

**始终使用 Excel 公式**，让表格保持动态可更新。

```python
# ❌ 错误：用 Python 计算后硬编码
total = sum(values)
sheet['B10'] = total

# ✅ 正确：使用 Excel 公式
sheet['B10'] = '=SUM(B2:B9)'
```

## 快速参考

### 创建新文件（openpyxl）

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "数据表"

# 写入表头
headers = ['姓名', '部门', '金额', '日期']
for col, h in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=h)
    cell.font = Font(bold=True, color='FFFFFF', size=11)
    cell.fill = PatternFill('solid', fgColor='4472C4')
    cell.alignment = Alignment(horizontal='center', vertical='center')

# 写入数据
data = [
    ['张三', '技术部', 15000, '2024-01-15'],
    ['李四', '市场部', 12000, '2024-01-15'],
    ['王五', '技术部', 18000, '2024-01-15'],
]
for row_idx, row_data in enumerate(data, 2):
    for col_idx, value in enumerate(row_data, 1):
        ws.cell(row=row_idx, column=col_idx, value=value)

# 添加汇总公式
ws.cell(row=5, column=3, value='=SUM(C2:C4)')
ws.cell(row=5, column=1, value='合计')
ws.cell(row=5, column=1).font = Font(bold=True)

# 设置列宽
ws.column_dimensions['A'].width = 12
ws.column_dimensions['B'].width = 12
ws.column_dimensions['C'].width = 15
ws.column_dimensions['D'].width = 14

# 数字格式
for row in ws.iter_rows(min_row=2, max_row=5, min_col=3, max_col=3):
    for cell in row:
        cell.number_format = '#,##0'

# 边框
thin_border = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin'),
)
for row in ws.iter_rows(min_row=1, max_row=5, min_col=1, max_col=4):
    for cell in row:
        cell.border = thin_border

# 冻结首行
ws.freeze_panes = 'A2'

# 自动筛选
ws.auto_filter.ref = 'A1:D4'

wb.save(f'output/{session_id}/数据表.xlsx')
```

### 读取和分析数据（pandas）

```python
import pandas as pd

# 读取 Excel
df = pd.read_excel('workplace/input.xlsx')
# df = pd.read_excel('workplace/input.xlsx', sheet_name=None)  # 读取所有 sheet

# 常用分析
df.describe()        # 统计摘要
df.groupby('部门').sum()  # 分组汇总
pivot = pd.pivot_table(df, values='金额', index='部门', aggfunc='sum')

# 输出到 Excel（简单输出，无格式）
df.to_excel(f'output/{session_id}/分析结果.xlsx', index=False)
```

### 编辑现有文件

```python
from openpyxl import load_workbook

wb = load_workbook('workplace/input.xlsx')
ws = wb.active

# 修改单元格
ws['A1'] = '新值'
ws.insert_rows(2)      # 在第2行插入
ws.delete_cols(3)       # 删除第3列

# 新建 sheet
ws2 = wb.create_sheet('汇总')
ws2['A1'] = '部门汇总'

wb.save(f'output/{session_id}/修改后.xlsx')
```

## 常用格式

### 数字格式代码

| 用途 | 格式代码 |
|------|---------|
| 千分位整数 | `#,##0` |
| 保留两位小数 | `#,##0.00` |
| 货币（人民币） | `¥#,##0.00` |
| 百分比 | `0.0%` |
| 日期 | `yyyy-mm-dd` |
| 负数用括号 | `#,##0;(#,##0);"-"` |

### 颜色参考

| 用途 | 颜色代码 |
|------|---------|
| 蓝色表头 | `4472C4` |
| 绿色（正值） | `00B050` |
| 红色（负值） | `FF0000` |
| 灰色背景（隔行） | `F2F2F2` |
| 黄色高亮 | `FFFF00` |

## 图表

```python
from openpyxl.chart import BarChart, Reference, LineChart, PieChart

# 柱状图
chart = BarChart()
chart.title = '销售数据'
chart.x_axis.title = '月份'
chart.y_axis.title = '金额'
data = Reference(ws, min_col=2, min_row=1, max_row=13)
cats = Reference(ws, min_col=1, min_row=2, max_row=13)
chart.add_data(data, titles_from_data=True)
chart.set_categories(cats)
chart.width = 18
chart.height = 12
ws.add_chart(chart, 'E2')

# 饼图
pie = PieChart()
pie.title = '部门占比'
data = Reference(ws, min_col=2, min_row=1, max_row=5)
cats = Reference(ws, min_col=1, min_row=2, max_row=5)
pie.add_data(data, titles_from_data=True)
pie.set_categories(cats)
ws.add_chart(pie, 'E18')
```

## 条件格式

```python
from openpyxl.formatting.rule import CellIsRule

# 大于10000的单元格标绿色
green_fill = PatternFill('solid', fgColor='C6EFCE')
ws.conditional_formatting.add(
    'C2:C100',
    CellIsRule(operator='greaterThan', formula=['10000'], fill=green_fill)
)
```

## 重要提醒

- **当前会话的所有 agent 文件都放到 `output/<session_id>/`**
- **始终使用 Excel 公式**，不要用 Python 计算后硬编码结果
- `session_id` 从 Runtime 里的 `current_session_id` 读取；当前目录也会在 Runtime 的 `session_output_dir_relative_to_workplace` 给出
- 用 `write_file(path=f"output/{session_id}/gen_xlsx.py")` 写 Python 脚本，用 `bash` 在 `cwd=workplace` 下执行它；优先使用 `uv run python` 执行生成脚本，不要写死本机解释器绝对路径
- 最终 `.xlsx` 也写到同一个 `output/<session_id>/` 目录；不要写到其他会话目录
- 生成完毕后告知用户文件名，前端自动显示下载按钮
- 处理大数据量时优先用 pandas 读取分析，用 openpyxl 做最终格式化输出
- 注意 openpyxl 单元格索引从 1 开始（不是 0）
- 用 `data_only=True` 读取时**不要保存**，否则公式会丢失
