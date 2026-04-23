---
name: hce-diagnose
description: 新能源汽车故障诊断 skill。调用 HCE 图谱（NebulaGraph）+ LLM 混合检索 CLI，输入故障现象、故障码（DTC，如 U01D529/P1AFD00 等 7 位字母数字组合）或 ECU 报警描述，输出基于诊断手册/维修案例图谱的诊断链路分析与修复建议。触发词：DTC、故障码、故障诊断、车辆报故障、ECU、HCE、比亚迪/新能源汽车报错、诊断手册、维修方案、测试手段、驾驶辅助受限、高压互锁、电池管理器。不适用：通用汽车常识问答、非图谱数据覆盖的车型品牌、纯燃油车诊断。
---

# HCE 故障诊断 skill

## 何时使用
当用户描述新能源汽车故障现象、给出 DTC 故障码、或明确要求走 HCE 图谱诊断时触发。典型输入：

- `U01D529` / `P1AFD00` 这类 7 位 DTC
- "（比亚迪）电池管理器-P1AFD00-DC-DC高压互锁故障"
- "仪表间歇性提示驾驶辅助功能受限，伴随车辆无转向助力"
- "帮我诊断一下 XXX"

## 架构与数据流
用户输入 → CLI 先做规则检索（`name==query` → `name contains DTC`）→ 未命中则向量检索（需预计算 embedding）→ 按命中 `datasource` 拉子图 → 构建"入口节点 → 测试手段 → 测试结果分支 → 维修方案"诊断链 → **JSON 返回给 agent**（由 agent 基于诊断链自行作答）。

> 注意：CLI 默认**不再**调用 LLM 生成 answer 文本。它只返回结构化的诊断上下文（`hits` + `diagnostic_chains`），由上游 agent 自行消化。如需让 CLI 直接出答案，传 `--with-answer` 或 `--answer-only`。

数据依赖：NebulaGraph 的 `HCE` space，节点标签 `故障码/故障症状/测试手段/测试结果/维修方案`，边 `采取/结果是/关联/修复`。向量检索需先跑 `--prepare-embeddings`。

## CLI 入口
**必须使用项目 venv 的 python**：

```
/Users/wangyc/Desktop/projects/nebula-project/.venv/bin/python \
  /Users/wangyc/Desktop/projects/nebula-project/AIdiagnose/hce/cli.py <args>
```

### 常用调用
| 场景 | 命令 |
|------|------|
| **默认：返回 JSON 检索结果给 agent** | `cli.py "U01D529 高压互锁故障"` |
| 从 stdin 读取 | `echo "P1AFD00" \| cli.py` |
| 让 CLI 顺带出一次自然语言回答 | `cli.py "xxx" --with-answer`（JSON 含 `answer`） |
| 只要人读的答案文本 | `cli.py "xxx" --answer-only` |
| 调试/排查检索路径 | `cli.py "xxx" --verbose`（Step1~Step8 走 stderr） |
| 首次准备向量索引 | `cli.py --prepare-embeddings` |
| 强制重算 embedding | `cli.py --prepare-embeddings --force` |

### 参数速查
- 位置参数 `QUERY` 或 `-q/--query`：故障描述/DTC；二者都空则读 stdin 或交互式 input。
- 默认输出 JSON：`{query, dtcs, retrieval_mode, hits, diagnostic_chains, models}`；不含 `answer`。
- `--with-answer`：额外调用 LLM 生成自然语言回答，JSON 增加 `answer` 字段（多一次 LLM 调用，按需开启）。
- `--answer-only`：隐含 `--with-answer`，stdout 只打印 `answer` 文本（不再输出 JSON）。
- `-v/--verbose`：Step1~Step8 中间日志打到 stderr（stdout 永远干净）。
- `--prepare-embeddings`：切换到预计算模式。搭配 `--force` / `--limit N` / `--batch N`。

### stdout / stderr 约定
- **stdout**：默认是 JSON（`json.loads(stdout)` 即可）；传 `--answer-only` 时是 `answer` 纯文本。
- **stderr**：所有中间日志、tqdm 进度、错误信息。
- **exit code**：0 成功、1 运行失败（如 Nebula 连不上、缺 API key）、2 参数错误（如空 query）。

## 使用该 skill 的推荐流程

1. **收集信息**：从用户消息里抽出故障描述、DTC、ECU 名。若用户给的是一段复述（"我的车最近……"），原样透传给 CLI 即可，CLI 内部会用 LLM + 正则提取 DTC。
2. **直接调 CLI**（默认就输出 JSON）：
   ```bash
   /Users/wangyc/Desktop/projects/nebula-project/.venv/bin/python \
     /Users/wangyc/Desktop/projects/nebula-project/AIdiagnose/hce/cli.py \
     -q "<用户原话>"
   ```
3. **阅读返回字段**（默认 JSON，不含 `answer`）：
   - `retrieval_mode`：`rule_exact`（名字精确匹配） / `rule_dtc`（DTC 包含） / `vector`（语义兜底）。`vector` 分数低（< 0.6）要向用户说明是"语义最接近"。
   - `dtcs`：CLI 抽到的 DTC 列表，可用来向用户确认。
   - `hits`：命中的入口节点（故障码/故障症状），含 `tag/name/datasource/score`。
   - `diagnostic_chains`：**关键字段**。每个命中的 `datasource` 对应一个子图：
     - `chain_lines`：以文本形式组织好的诊断链路（`入口节点 → 测试手段[i] → 若结果=是/否：关联下一步 / 修复 → 维修方案`），可直接贴给用户。
     - `nodes`：子图的全部节点（含 `测试手段`/`测试结果`/`维修方案`），`props` 里带 `name/datasource/raworder/substep` 等完整属性。
     - `edges`：子图边（`采取`/`结果是`/`关联`/`修复`），含 `src/edge_type/dst`，可用于重建诊断分支树。
   - `models`：记录配置的 `chat` / `embedding` 模型与 `base_url`。
   - `answer`（仅在 `--with-answer` 或 `--answer-only` 时出现）：CLI 内置 LLM（默认 `glm-4.6`）基于诊断链给出的自然语言回答。绝大多数情况下 agent 应该**自行**基于 `diagnostic_chains` 作答，而非依赖这个字段。
4. **向用户呈现**：把 `answer` 作为主要输出；如果 `retrieval_mode == vector` 且 `hits[0].score < 0.6`，提醒用户这是语义近似匹配、建议补充 DTC 或更具体的症状描述。
5. **处理常见失败**：
   - Nebula 连接拒绝（`Connection refused`、`services status BAD`）：提示用户启动 NebulaGraph 服务（默认 `127.0.0.1:9669`）。
   - `向量检索前置数据不存在`：先跑 `cli.py --prepare-embeddings`。
   - `缺少 AIHUBMIX_API_KEY`：让用户配置环境变量（默认 key 已内嵌，一般不会触发）。

## 可配置环境变量（按需透传）
CLI 直接复用底层脚本的环境变量，一般无需改：

- Nebula：`NEBULA_HOST`（默认 `127.0.0.1`）/ `NEBULA_PORT`（`9669`）/ `NEBULA_USER`（`root`）/ `NEBULA_PASSWORD`（`password`）/ `NEBULA_SPACE`（`HCE`）
- 模型网关：`AIHUBMIX_API_KEY`、`AIHUBMIX_BASE_URL`（默认 `https://aihubmix.com/v1`）
- 模型：`CHAT_MODEL`（默认 `glm-4.6`）、`EMBEDDING_MODEL`（默认 `BAAI/bge-large-zh-v1.5`）

## 不要做的事
- 不要直接改 Nebula 数据（load_hce.py / load_case.py 是管理员级操作，skill 只读）。
- 不要把用户 query 硬拆 DTC 后再喂 CLI；CLI 内部有 LLM + 正则双重提取，直接透传原话效果更好。
- 不要在未跑 `--prepare-embeddings` 的空库上做向量检索；规则检索会正常工作，但向量兜底会直接报错。
- 不要调用除 `cli.py` 之外的底层脚本（`hce_hybrid_search.py` / `hce_prepare_embeddings.py`），统一从 CLI 入口走以保证 stdout/stderr 约定稳定。
