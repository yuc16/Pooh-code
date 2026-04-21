---
name: byd-patent-claim-chart-internal
description: 针对比亚迪有权的中文专利，在内网受限环境下检索可能相关的竞品，并输出逐条权利要求技术特征与竞品特征的对比表。适用于用户提到"比亚迪专利""中文专利""竞品侵权筛查""claim chart""内网环境""只能用大为专利和汽车之家""权利要求比对""技术特征对比"等场景。只允许使用大为专利和汽车之家作为信息来源，竞品特征必须附明确公开链接。
---

# 比亚迪中文专利竞品比对（内网版）

## 任务定义

这个 skill 用于在**内网受限环境**下完成比亚迪中文专利的 claim chart 初筛。默认目标不变：

1. 锁定一件**比亚迪有权的中文专利**
2. 覆盖**应分析的全部权利要求**
3. 将每条权利要求拆成**可逐项核验的技术特征**
4. 仅使用白名单站点收集竞品公开证据
5. 生成固定为 `.xlsx` 的技术特征对比表

脚本只是最小取数辅助；核心工作仍然是权利要求拆解、证据映射和表格交付。

## 硬性边界

- 只允许使用 `大为专利` 和 `汽车之家`
- 不要用全网搜索、外部搜索引擎或其它网站补证据
- 证据不足时直接写 `证据不足` 或 `无法确认`
- 不要只分析权利要求 1，除非用户明确缩小范围
- 不要把推断包装成明确证据
- 不要直接下“构成侵权”“一定侵权”等法律结论
- 如果专利权属不清、不是中文专利、或不是比亚迪相关专利，先提醒用户确认

## 先读什么

按下面顺序读取；脚本默认直接执行，不默认当阅读材料：

1. `references/workflow.md`
   作用：任务顺序、输出口径、交付检查
2. `references/data-sources.md`
   作用：大为专利和汽车之家的接口、字段和证据边界
3. `secrets.local.json`
   作用：大为专利认证信息；若不存在，再使用环境变量 `DAWEISOFT_DEVICE_ID` 和 `DAWEISOFT_TOKEN`
4. `assets/byd_patent_claim_chart_template.xlsx`
   作用：最终 `.xlsx` 模板

## 默认直接执行的工具

下面两个脚本默认按文档约定直接执行，而不是先读源码：

- `scripts/fetch_dawei_patent_claims.py`
  用途：按公开号拉权利要求，或按关键词检索“比亚迪中文有权专利”候选列表
- `scripts/fetch_autohome_series_params.py`
  用途：按 agent 给出的关键词做汽车之家站内搜索，并补抓文章详情、车系页和参数页

只有在以下情况才需要看脚本源码：

- 命令执行失败，需要定位报错
- 站点接口或返回字段发生变化，需要补丁
- 需要扩展脚本输入输出，而现有命令模板不够用

脚本的最小参数、关键输出字段和常见失败排查，见 `references/workflow.md` 中的“脚本契约”。

## 跨平台约定

这个 skill 需要兼容 Linux 和 Windows 用户，执行时遵守下面几点：

- 命令示例统一写成**单行**，不要依赖 bash 的反斜杠续行
- 命令中的 `<python_cmd>` 表示当前环境可用的 Python 命令
- Windows 常见为 `python`
- Linux 常见为 `python3` 或 `python`
- 路径优先使用 repo 内相对路径，例如 `workplace/runtime/...`
- 不要假设 `/tmp`、`~`、`$PWD`、shell alias 或 bash-only 语法存在
- 如果需要输出中间 JSON，统一写到当前会话输出目录，例如 `workplace/output/<session_id>/`

## 输入预期

优先使用以下任一输入：

- 专利号
- 专利全文或权利要求文本
- 专利名称 + 专利号
- 指定的竞品或车型范围

如果用户没有给全，优先补齐：

1. 专利号或完整权利要求
2. 要分析的权利要求范围
3. 竞品或车型范围

如果用户没有限定权利要求范围，默认处理：

- 全部独立权利要求
- 全部从属权利要求

## 执行原则

### 大为专利

- 优先通过接口取数，不依赖网页全文搜索
- 默认直接执行脚本，不必先阅读脚本实现
- 按关键词检索时，查询必须被硬性限制为**比亚迪中文有权专利**
- 按公开号拉详情时，优先读取中文权利要求 `CL.CLZH`
- 认证信息优先读 `secrets.local.json`，否则读环境变量

### 汽车之家

- 优先使用站内搜索、车系页和参数接口
- 默认直接执行脚本，不必先阅读脚本实现
- 检索关键词必须由 agent 根据专利标题和全部权利要求生成
- 脚本返回的是证据素材，不等于已经完成特征映射
- 汽车之家未明确公开的特征，直接写 `证据不足`

## 命令模板

如果只给技术主题，先搜比亚迪中文有权专利候选：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_dawei_patent_claims.py --keyword "电池" --page-size 10 --output workplace/output/<session_id>/byd_battery_patents.json
```

如果已知公开号，直接拉专利详情和中文权利要求：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_dawei_patent_claims.py --pnm CN203964454U --output workplace/output/<session_id>/cn203964454u.json
```

如果需要搜汽车之家并补抓车系参数：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_autohome_series_params.py --keyword "热泵空调 小米SU7" --keyword "PTC 小米SU7" --max-results 8 --max-series 3 --output workplace/output/<session_id>/xiaomi_su7_autohome.json
```

如果用户已经明确给了 `series_id`，可以显式缩小范围：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_autohome_series_params.py --keyword "热泵空调 小米SU7" --series-id 6962 --max-results 8 --max-series 1 --output workplace/output/<session_id>/xiaomi_su7_autohome.json
```

需要调试原始返回时，再额外加 `--include-raw`。

## 输出要求

最终交付固定为 `.xlsx`，优先复用 `assets/byd_patent_claim_chart_template.xlsx`。主表至少包含：

| 权利要求 | 特征编号 | 权利要求技术特征 | 竞品/型号 | 竞品对应特征 | 证据摘要 | 证据链接 | 匹配判断 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

要求：

- 一条技术特征一行
- 同一条权利要求下的全部技术特征必须完整展开
- 所有竞品特征都要附白名单来源链接
- 备注列专门写争议点、缺口和推断点
- 不要把最终 claim chart 混进中间取数 JSON

## 交付前检查

至少确认以下事项：

1. 是否真的是比亚迪有权中文专利
2. 是否只使用了大为专利和汽车之家
3. 是否覆盖了应分析的全部权利要求
4. 是否把每条权利要求的全部技术特征拆到了可逐项比对的粒度
5. 是否每条竞品特征都有公开证据链接
6. 是否清楚区分了明确证据与推断
7. 是否避免直接下侵权法律结论
8. 如果生成了文件，是否写入当前会话输出目录
