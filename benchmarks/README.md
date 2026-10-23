# UPG-01 检索基线

当前提供试运行管线、人工标注题集和正式 PostgreSQL 检索/过滤窗口实验；HNSW 结果已完成 1,000/10,000 chunk、100 查询×5 轮诊断，但多 owner/多版本真实分布仍需后续阶段补充。

## 120 条正式人工标注集（2026-10-17）

`benchmarks/retrieval_labeled_v1.json` 是由用户核验通过的正式题集：`dataset_kind=human_labeled`、`review_status=approved`，共 120 题（development 40 / frozen 80，80 条有答案、40 条无答案）。题目标签已逐题对照同文件中的 10 个公开合成 chunk 核验。

正式 PostgreSQL 报告：`D:/dev-learning-baselines/2026-10-17-formal-labeled-pg-v2`。独立 `study_tasks_eval` 数据库、10 个活动 chunk、5 轮、每策略 600 次测量：keyword 的 Recall@5/MRR@5/无答案正确率为 `0.675/0.650/0.900`，vector 为 `1.000/0.918/0.000`，hybrid 为 `1.000/0.876/0.000`。向量无答案正确率为 0 暴露了当前 `min_score=-1` 阈值过宽；这些结果的语料规模仍只有 10 个合成 chunk，不能写成生产规模性能提升。

## 120 条检索候选集（2026-10-17）

`benchmarks/retrieval_candidate_v1.json` 包含 120 条候选问题：development 40 条、frozen 80 条；每个 split 含 20 条无答案题。题目由公开的 10 个合成 chunk 生成，文件明确标记 `dataset_kind=ai_generated_candidate` 和 `review_status=pending_human_review`。运行器默认拒绝这类文件，必须显式传 `--allow-candidate`，避免把未人工核对的题集当作正式验收集。

候选基线报告保存在 `D:/dev-learning-baselines/2026-10-17-formal-candidate-pg-v3`，独立 PostgreSQL、10 active chunks、120 题、5 轮、每策略 600 条测量。整体 Recall@5/MRR@5/无答案正确率：keyword=0.675/0.650/0.900，vector=1.000/0.918/0.000，hybrid=1.000/0.876/0.000。development 的 keyword/vector/hybrid Recall@5 为 0.650/1.000/1.000；frozen 为 0.683/1.000/1.000。这些数字是候选集的工程基线，不是人工验收质量，也不能直接写入简历。

## 过滤改写与 HNSW 对照（2026-10-17）

正式题集过滤窗口报告：`D:/dev-learning-baselines/2026-10-17-formal-filter-window-v1`。对每道正式题先执行精确的 ready/active_version 检索，再用候选窗口 `5/10/20/50/100` 后过滤，5 轮共 600 次/窗口；所有窗口在当前 10 个活动 chunk、单 owner/单版本范围内与精确 top-5 完全一致（mean overlap/exact match 均为 `1.0`）。P50/P95 分别约为 `1.80/2.33 ms`、`1.81/2.26 ms`、`1.80/2.28 ms`、`1.81/2.20 ms`、`1.82/2.21 ms`。这证明当前小数据范围没有观察到候选窗口丢召回，不证明大规模或多版本过滤正确性。

## 向量无答案阈值扫描（2026-10-17）

报告：`D:/dev-learning-baselines/2026-10-17-threshold-v1`。在同一 120 条人工题集、10 个合成 chunk、单 owner/单 active version、5 轮条件下扫描 `min_score`。结果为：`0.4` 的 Recall@5/无答案正确率=`1.000/0.025`，`0.5`=`0.900/0.525`，`0.6`=`0.650/0.950`，`0.7`=`0.275/1.000`。这是质量取舍曲线，不能只依据本小样本选择生产默认值；当前生产默认 `-1.0` 会保留所有向量结果，正式基线中的无答案正确率为 0。下一步应在更丰富的开发集上校准阈值，并单独评估 hybrid 的拒答策略。

## 100 查询规模 HNSW 诊断（2026-10-17）

报告：`D:/dev-learning-baselines/2026-10-17-hnsw-1000-100q-v1` 与 `D:/dev-learning-baselines/2026-10-17-hnsw-10000-100q-v1`。两组均为确定性随机向量、100 个查询、5 轮、精确扫描/默认 planner/强制 HNSW 三路对照。10,000 chunk 的 filtered_join P50/P95：精确 `28.16/33.60 ms`，默认 `29.34/35.50 ms`，强制 HNSW `2.34/3.27 ms`，但强制 HNSW top-5 重合率仅 `0.68`；默认 planner 未使用 HNSW。1,000 chunk 的 filtered_join P50/P95：精确 `3.62/4.31 ms`，默认 `4.48/5.33 ms`，强制 HNSW `3.62/4.41 ms`，重合率 `1.0`；默认 filtered_join 仍未使用 HNSW。结果证明规模、规划器与召回之间存在取舍，不构成生产性能提升百分比。

探针新增 `filtered_join`：先按向量取 `candidate_limit=100`，再 JOIN `documents` 检查 `ready/active_version`，最后取业务 top-k。10,000 条确定性随机向量、20 查询、5 轮报告位于 `D:/dev-learning-baselines/2026-10-17-filter-hnsw-10000`。改写 SQL 的默认计划仍未使用 HNSW，节点输出 10,000 行；强制关闭顺序扫描和排序后使用 HNSW，节点输出 5 行。filtered_join 的 P50/P95：精确 28.57/31.53 ms，默认 30.62/33.19 ms，强制 HNSW 28.45/31.28 ms；本轮单一 owner/单一 active 文档的 top-5 与精确结果均重合。强制 planner 设置只用于诊断，不能算生产优化收益；下一步需要在多文档、多版本和人工题集上验证候选窗口是否丢失有效 chunk。

## 运行

正式人工题集可先播种到独立实验库，再运行 PostgreSQL 对照：

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://.../study_tasks_eval'
.\.venv\Scripts\python.exe scripts/seed_pg_retrieval_dataset.py `
  --fixture benchmarks/retrieval_labeled_v1.json
```

播种器只接受 `human_labeled` 且 `review_status=approved` 的题集，并要求实验库中不存在同名 owner；它不会写入生产库。

从仓库根目录执行，输出路径必须是尚不存在的新目录：

```powershell
.\.venv\Scripts\python.exe scripts/run_retrieval_baseline.py --output D:/dev-learning-baselines/my-run
```

默认使用 `retrieval_smoke.json`，10 个 AI 编写的合成 chunk、12 个试运行问题，预热1轮、测量5轮。12题仍是12题，60行是重复测量数，不是60个独立场景。当前调用内存 `KeywordRetriever`，没有 PostgreSQL、embedding 或模型请求，不能将耗时写成生产检索／Agent 延迟。

## 数据与指标

每个 case 包含 `id`、`query`、`split`（smoke/development/frozen）、`relevant_chunks`。chunk 标识为 `source#chunk_id`；空标签表示无答案问题。加载时检查重复标识、未知标签、空问题与非法划分。

Recall@k：前k条命中的不同相关 chunk 数／全部相关 chunk 数。MRR@k：首个相关结果的原始排名倒数取平均。重复结果不增加召回，也不改变原始排名。无答案题从 Recall/MRR 分母排除，单独统计结果为空的比例；这不是生成阶段拒答质量。

P50/P95 使用排序样本线性插值。当前跨轮聚合相同问题；不是独立问题规模增加，也不是统计置信区间。

## UPG-04 Agent 确定性场景

从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/run_agent_scenarios.py
```

运行器执行 `tests/test_agent_scenario_suite.py`：78 个参数化行为场景和 1 个场景集完整性检查，共 79 tests。旧报告的“72 个唯一场景”更正为 71 个行为场景 + 1 个完整性检查，历史原件保留。场景使用 SQLite 和 `httpx.MockTransport`，覆盖 API 授权、多轮与重开会话、显式档案、计划约束、确认幂等与冲突、工具权限和停止/重试边界，不测在线模型效果或真实费用。

新报告默认写入 `benchmarks/agent_scenarios_upg04/<UTC时间戳>/`，非空目录拒绝覆盖。逐条 JUnit、JSON、stdout/stderr、运行前源码快照 `source.zip`、SHA-256、HEAD/dirty 与 Python 环境一起保存；`source_unchanged_during_run` 检查运行期间源码是否变化。不同报告不能拼成同一版本的证据。

真实 PostgreSQL 验收另行运行（需要 Docker Linux engine）：

```powershell
.\.venv\Scripts\python.exe scripts/run_pg_agent_acceptance.py
# 在临时 PostgreSQL 上运行整个回归套件
.\.venv\Scripts\python.exe scripts/run_pg_agent_acceptance.py --full-suite
```

运行器创建无持久卷的临时 `pgvector/pgvector:pg17` 容器、随机本地端口和专用 `study_tasks_test` 库，结束自动删除自己的容器，不使用现有业务库。密码不写入报告。产物保存到 `benchmarks/pg_agent_upg04/<UTC时间戳>/`，包含源码快照、原始结果、镜像 ID、命令和环境。PG 专项现有 9 tests，覆盖迁移、检索回归、checkpoint 重开/暂停恢复、提案创建与确认并发、消息序号分配、版本竞争、失败回滚和调整幂等。最终证据与边界见 [UPG-04 验收说明](../docs/UPG04持久Agent验收.md)。

## 产物与恢复

- `dataset.json` 保存输入；`raw.json/csv` 保存逐题排名、耗时和质量；`summary.json` 保存聚合。
- `metadata.json` 保存 HEAD、dirty 状态、Python、系统、依赖、命令、配置及数据哈希；不读取环境变量凭据。
- `snapshot/source.zip` 和 manifest 保存应用源码、测试与运行配置（包含尚未提交的源文件），排除运行数据和非允许文件。源码哈希按路径和文件内容计算，不依赖文件时间戳。
- `runner.py` 保存运行入口。恢复时将快照解压到独立目录，把 runner 放到 scripts 下；使用随结果保存的 dataset 和原命令参数。依赖参照 metadata 与 requirements；模型、数据库、系统环境不包含在源码包内。

生产检索模式使用同一个 `run_scoped` 入口，对 keyword/vector/hybrid 传入同一 `owner_id` 和 `limit`。运行器会先查询当前 owner 的 `ready` 且 `active_version` 匹配的 chunk 标签，数据集引用旧版本、其他用户或不存在的 chunk 时直接失败；不会把不在用户当前资料范围内的标注算进 Recall。

已有只读生产入口：

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://.../independent_experiment_db'
.\.venv\Scripts\python.exe scripts/run_pg_retrieval_baseline.py --cases benchmarks/labeled_cases.json --owner-id 1 --output D:/dev-learning-baselines/pg-run-01
```

运行前需在独立实验库完成迁移和用户文档入库；脚本不会建库、迁移或写入记录。`labeled_cases.json` 必须是人工可核对的 `development`/`frozen` 问题，标签为该用户当前活动 chunk。可用 `--allow-smoke` 临时验证管线，但 smoke 结果不能当正式评测。预热阶段包括模型初始化；计时阶段包括现有检索器的查询向量化、SQL 与融合，不包括问答模型。URL 只通过环境变量读取，不写入报告。源码快照只收录公开 smoke JSON；传入的标注 case 文件单独保存到报告目录，需由运行者控制其访问权限。

源码快照是当前 dirty 工作区的代码证据，不等于干净 Git 提交或完整容器快照。正式规模实验还需固定 CPU/内存、数据库与模型条件。

## 自主查看

`score_ranking` 决定指标；`run_keyword` 决定计时边界；`snapshot_source` 决定复现范围；脚本 `main` 组装输入和产物。可先对照同一个问题的标签、actual_chunks 和指标，不要求指定阅读顺序。

## 合成扩容诊断（2026-10-14）

`scripts/seed_pg_retrieval_scale.py` 在全新 `study_tasks_eval` 数据库中生成 1,000 或 10,000 chunk。保留原 10 个锚点，其他 chunk 使用同一段无关合成文本和相同向量；只对 11 种唯一文本做 embedding。它适合观察扫描/排序随行数增长的变化，不能代表真实语料的向量分布、索引召回或入库吞吐。脚本仅接受这两个预设规模，重复入库会拒绝。

`run_pg_retrieval_baseline.py --capture-plans --allow-smoke` 对 12 个公开 smoke 问题运行 5 轮，并存储 `plans.json`。计划含 `planner_default` 与 `indexscan_disabled` 两种模式；`metadata.json` 的 `plan_summary` 记录实际 HNSW 使用和 chunk 节点输出行数。2026-10-14 首次报告在添加摘要字段前生成，原始 `plans.json` 保留旧模式名 `hnsw_allowed`/`exact_scan`，含义相同。执行计划内出现 `Bitmap Index Scan` 不代表使用 HNSW；应核对索引名 `ix_document_chunks_embedding_hnsw`。

| 合成 chunk | 策略 | P50 / P95 (ms) | Recall@5 | 无答案正确率 |
|---:|---|---:|---:|---:|
| 1,000 | keyword | 20.36 / 24.70 | 0.90 | 1.00 |
| 1,000 | vector | 12.56 / 17.72 | 0.90 | 0.00 |
| 1,000 | hybrid | 33.15 / 40.84 | 1.00 | 0.00 |
| 10,000 | keyword | 152.62 / 247.25 | 0.90 | 1.00 |
| 10,000 | vector | 40.60 / 79.42 | 0.90 | 0.00 |
| 10,000 | hybrid | 195.92 / 378.61 | 1.00 | 0.00 |

每格只有 12 题 × 5 轮、单次环境运行；质量数字来自重复的 12 个合成标签，不可用于简历。两个规模的默认计划都对可见 chunk 排序，12 个问题中 HNSW 使用次数为 0。1,000 和 10,000 chunk 报告分别保存在 `D:/dev-learning-baselines/2026-10-14-upg01-scale-1000` 和 `D:/dev-learning-baselines/2026-10-14-upg01-scale-10000`。原始 JSON/CSV、计划、环境、源码哈希都在报告内；容器运行时 Git 不可用，`git_head` 为 `unavailable`。下一步用真实分布的合成语料和精确检索对照核实 HNSW，再优化关键词 SQL 路径。

## 精确检索与 HNSW 探针（2026-10-14）

`scripts/run_pg_hnsw_probe.py` 使用 `random.Random(chunk_id)` 生成可复现的 512 维向量，不调用 FastEmbed，也不代表真实文档语义。它在同一独立库中比较关闭索引的精确扫描、默认规划器和仅用于诊断的强制 HNSW；同时比较只查 `document_chunks` 的 bare SQL 与保留 `documents` 生命周期 JOIN 的生产 SQL。每次记录 top-k 与精确结果的重合率，计划摘要记录实际 HNSW 索引名和 chunk 节点输出行数。

10,000 条、20 个探针、5 轮的报告：`D:/dev-learning-baselines/2026-10-14-hnsw-probe-10000-full`。默认计划在 bare/生产 JOIN 中都未使用 HNSW，chunk 节点各输出 10,000 行；强制模式使用 HNSW，节点输出 5 行。这不是索引内部距离比较次数。脚本测得 P50/P95：bare 精确 29.95/41.80 ms、默认 32.20/44.63 ms、强制 HNSW 3.18/4.45 ms；生产 JOIN 精确 32.71/41.48 ms、默认 35.99/44.93 ms、强制 HNSW 33.11/48.92 ms。bare 强制 HNSW 的 top-5 平均重合率仅 0.69，生产 JOIN 为 1.00；因此这些数据只能说明“索引可被强制使用且存在召回取舍”，不能作为产品优化百分比。

默认不使用 HNSW 是当前数据和 SQL 下的规划器选择，不等于索引无效。下一步应先在正式问题集上验证过滤改写和 `ef_search`/索引参数，再报告 Recall@5、MRR@5、P95 的变化。强制 planner 设置只存在于诊断脚本，不改变生产请求配置。

## UPG-03 PostgreSQL 全文候选检索（2026-10-20）

正式报告：`D:/dev-learning-baselines/2026-10-20-upg03-fts-or-labeled-v1`。实验使用独立 `study_tasks_eval` PostgreSQL/pgvector 数据库，`BAAI/bge-small-zh-v1.5`（512 维、1 线程），120 条人工核验题（development 40 / frozen 80）、10 个 active 合成 chunk；每策略预热 1 轮，计时 5 轮，共 600 条测量。计时范围为查询向量化、SQL 与融合，不含回答模型生成。

| 策略 | Recall@5 | MRR@5 | 无答案正确率 | P50 / P95 (ms) |
|---|---:|---:|---:|---:|
| PostgreSQL FTS keyword | 0.925 | 0.879 | 0.800 | 3.41 / 4.82 |
| pgvector | 1.000 | 0.918 | 0.000 | 11.39 / 15.51 |
| RRF hybrid | 1.000 | 0.914 | 0.000 | 15.12 / 20.67 |

首次运行报告 `D:/dev-learning-baselines/2026-10-20-upg03-fts-labeled-v1` 暴露 FTS 候选筛选使用 `plainto_tsquery` 的 AND 语义，导致包含核心词但不包含全部问题 token 的相关 chunk 在排序前被排除，关键词 Recall@5 为 0。修复为基于受限 `tokenize()` 输出构造 OR `to_tsquery`，再在候选窗口中按共享 token 确定性排序；该失败报告保留作为故障证据，修复后用新目录重跑得到上表。真实 PostgreSQL 回归测试包含“相关词 + 无关词”场景，防止恢复为 AND 截断。

这组数据能证明当前实现的功能与这 10 条语料上的检索质量，不能证明生产规模性能、端到端 Agent 延迟或“检索提速百分比”。`plans.json` 显示该规模的向量查询未使用 HNSW，chunk 节点输出 10 行；HNSW 的规模与召回取舍仍以此前独立诊断报告为准。
