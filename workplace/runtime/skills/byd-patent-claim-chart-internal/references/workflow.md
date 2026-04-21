# 核心 Workflow

这个 skill 的核心不是“抓网页”，而是用白名单站点完成一份可交付的 `.xlsx` claim chart。

## 目标

最终结果必须回答：

- 目标专利是否属于比亚迪有权中文专利
- 实际分析了哪些权利要求
- 每条权利要求拆出了哪些技术特征
- 每项技术特征在竞品上是否有公开证据
- 证据链接是否全部来自大为专利或汽车之家
- 匹配判断属于 `明确匹配`、`部分匹配`、`可能匹配`、`证据不足` 或 `明显不匹配`

## 推荐顺序

### 1. 确认分析对象

先锁定：

- 专利号
- 专利名称
- 权利人/受让人是否与比亚迪相关
- 需要分析的权利要求范围

如果用户没有限定，默认分析全部权利要求。

### 2. 拉取专利和权利要求

从大为专利获取：

- 专利基础信息
- 全部中文权利要求

注意：

- 这一步只是拿原文，不等于完成分析
- 不要只看主权项
- 从属权利要求也要覆盖

### 3. 拆解全部技术特征

按“可以单独拿证据核验的一条技术点”拆分。常见拆分维度包括：

- 结构特征
- 连接关系
- 参数范围
- 控制逻辑
- 功能限定
- 位置或材料限定

不要：

- 把整条权利要求压成一句总结
- 只挑少量特征
- 只分析权利要求 1

### 4. 选竞品并找证据

从汽车之家收集：

- 站内搜索结果
- 文章或论坛详情页证据摘录
- 车系页信息
- 参数配置接口字段

如果证据不足，直接写：

- `证据不足`
- `无法确认`

### 5. 做技术特征映射

每一行都应该只对应：

- 一条权利要求中的一个技术特征
- 一个竞品对应特征描述
- 至少一个白名单来源链接

判断口径统一为：

- `明确匹配`
- `部分匹配`
- `可能匹配`
- `证据不足`
- `明显不匹配`

### 6. 生成 `.xlsx`

最终文件应基于模板输出，并保留这些模块：

- 报告标题
- 专利/竞品基本信息
- 分析口径与边界
- 结论统计区
- 逐条权利要求技术特征对比主表

## 脚本的定位

这两个脚本只负责最小取数：

- `fetch_dawei_patent_claims.py`
  用途：按公开号拉专利详情和中文权利要求，或按关键词检索“比亚迪中文有权专利”候选列表
- `fetch_autohome_series_params.py`
  用途：按 agent 给出的关键词搜索汽车之家，并补抓文章详情、车系页和参数页

默认做法是直接按命令模板执行，不先阅读源码。

只有在以下情况才需要读脚本：

- 命令执行失败，需要定位报错
- 站点接口、字段或认证方式发生变化
- 需要修改脚本能力或输出格式

不要把脚本输出直接当成最终分析结论。

## 跨平台命令约定

- 所有命令都用单行示例，避免 bash 续行语法
- `<python_cmd>` 表示当前环境可用的 Python 命令
- Windows 常见为 `python`
- Linux 常见为 `python3` 或 `python`
- 路径优先使用 repo 内相对路径

## 命令模板

按主题词搜索比亚迪中文有权专利：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_dawei_patent_claims.py --keyword "<主题词>" --page-size 10 --output workplace/output/<session_id>/byd_patents.json
```

按公开号拉目标专利：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_dawei_patent_claims.py --pnm <专利号> --output workplace/output/<session_id>/<专利号>.json
```

搜索汽车之家并补抓车系参数：

```text
<python_cmd> workplace/runtime/skills/byd-patent-claim-chart-internal/scripts/fetch_autohome_series_params.py --keyword "<关键词1>" --keyword "<关键词2>" --max-results 8 --max-series 3 --output workplace/output/<session_id>/<竞品名>_autohome.json
```

如果用户已经给出 `series_id`，再加：

```text
--series-id <series_id>
```

如果只是调试，再加：

```text
--include-raw
```

## 脚本契约

### `fetch_dawei_patent_claims.py`

适用场景：

- 已知专利号，需要拉专利详情和中文权利要求
- 只知道技术主题，需要先筛“比亚迪中文有权专利”候选

最少参数：

- 详情模式：`--pnm <专利号>`
- 检索模式：至少一个 `--keyword "<主题词>"`
- 如需落盘：`--output <json_path>`

默认行为：

- `--keyword` 模式会自动强制加入 `CAS=(比亚迪)` 和 `CC=(CN)`
- `--pnm` 模式返回单件专利详情
- 有 `secrets.local.json` 时优先用该文件中的大为凭证，否则读取环境变量

成功后优先读取这些字段：

- 顶层：`mode`
- 详情模式：`patent_no`、`title`、`claims_zh`、`main_claim`、`claim_count`、`ownership_check`
- 检索模式：`result_count`、`patents`
- 候选专利列表中的重点字段：`patent_no`、`title`、`abstract`、`is_byd_cn_owned`

常见失败先排查：

- 报 `缺少 DAWEISOFT_TOKEN 或 DAWEISOFT_DEVICE_ID`：凭证缺失
- 报 `无法解析 ... secrets.local.json`：本地凭证文件格式错误
- 报 `未找到 <专利号> 对应记录`：专利号错误、站点无记录或凭证无权限
- 返回 `claims_zh` 为空：站点字段缺失或该记录没有可用中文权利要求，需人工复核

### `fetch_autohome_series_params.py`

适用场景：

- 已经从专利标题和全部权利要求提炼出检索关键词
- 需要从汽车之家收集候选车系、文章证据、车系页和参数页证据

最少参数：

- 至少一个 `--keyword "<关键词>"`
- 如需限制范围，可加 `--series-id <id>`
- 如需落盘：`--output <json_path>`

可选但常用参数：

- `--max-results <n>`
- `--max-series <n>`
- `--patent-json <dawei_json_path>`
- `--topic-text "<主题描述>"`
- `--include-raw`

默认行为：

- 先按每个关键词调用汽车之家搜索
- 自动汇总 `candidate_series`
- 再对命中的车系抓车系页和参数页
- 如果文章或论坛结果可抓详情页，会补 `detail`

成功后优先读取这些字段：

- 顶层：`explicit_search_terms`、`selected_series_ids`
- 搜索层：`search_queries`
- 每个搜索结果里的重点字段：`candidate_series`、`results`
- `results` 中优先看：`title`、`url`、`detail.content_preview`、`detail.evidence_snippets`
- 车系证据层：`series_evidence`
- `series_evidence` 中优先看：`series_name`、`brand_name`、`hot_spec_id`、`matched_param_fields`、`explicit_param_hits`、`source_links`

常见失败先排查：

- 报 `请先让 agent 生成关键词，再通过 --keyword 传入`：没有传关键词
- 报 `未找到 __NEXT_DATA__`：汽车之家页面结构变化或返回异常页
- `selected_series_ids` 为空：关键词无效、搜索未命中或候选车系抽取失败
- `matched_param_fields` 为空：不代表该车系一定不相关，只表示当前关键词没有命中公开参数字段

## 交付前检查

交付前至少确认：

1. 是否真的是比亚迪有权中文专利
2. 是否覆盖全部应分析权利要求
3. 是否拆了每条权利要求的全部技术特征
4. 是否每条竞品特征都有白名单来源证据
5. 是否没有把推断写成既成事实
6. 是否没有直接下法律侵权结论
