# AI 工程模式学习计划调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有学习路线切换为 AI 主写、学习者主导需求审查和验证的加速模式，同时保留 Agent 开发所需的基础能力门槛。

**Architecture:** 保留原始学习日志作为不可改写的历史证据；由 `AGENTS.md` 定义后续教学行为，由总学习计划定义范围和时间线，由 `学习进度.md` 保存当前事实与唯一下一任务。三份文件统一采用 L0～L4 能力证据，并把 W1～W2 记为功能覆盖完成、能力继续随用随验。

**Tech Stack:** Markdown、Git；学习技术栈为 Python 3.10+、FastAPI、PostgreSQL、SQLAlchemy/Alembic、pytest、Docker Compose、Linux、LLM API、工具调用、RAG 与评测。

## Global Constraints

- 每周预算保持 15～20 小时。
- 目标保持 2026 年 11～12 月开始投递 Python 后端 / Agent 应用开发实习。
- AI 可完成约 70%～80% 的代码，学习者保留每周一次 20～40 行关键变式。
- 不把 AI 完成的功能直接记录为学习者独立掌握。
- 保留既有 `学习记录/` 内容，不回写历史贡献。
- Kubernetes、复杂微服务、模型训练和复杂多 Agent 暂缓。

---

### Task 1: 固化教学规则

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-09-11-ai-engineering-learning-mode-design.md`
- Produces: 后续 Agent 每次会话必须遵守的 AI 工程模式、自动修复规则与 L0～L4 验收方法。

- [ ] **Step 1: 增加 AI 工程模式章节**

写明 AI 与学习者分工、允许 AI 直接生成的内容、学习者必须主导的活动，以及代码量不是进度指标。

- [ ] **Step 2: 修改单次教学流程**

将默认流程改为概念地图、AI 构建、代码审查、故障实验、关键变式、证据验收；保留用户提交后由 AI 自动修复同轮遗留问题的规则。

- [ ] **Step 3: 加入 L0～L4 能力证据**

明确 L0 接触、L1 理解、L2 操作、L3 排错、L4 修改；允许功能完成与能力等级分开记录。

- [ ] **Step 4: 更新当前接手入口**

删除“第一次接手从 W1-T01 开始”的过期指令，改为从 `学习进度.md` 的唯一下一任务进入。

- [ ] **Step 5: 检查教学规则一致性**

Run: `rg -n "AI 工程模式|L0|L4|自动修复|W1-T01" AGENTS.md`

Expected: 能找到新模式和等级；W1-T01 只作为示例或历史出现，不再强制从它开始。

### Task 2: 更新总学习路线

**Files:**
- Modify: `Agent开发实习学习与求职计划_2026.md`

**Interfaces:**
- Consumes: 设计中的必学技术栈与加速时间线。
- Produces: W3 起可执行的 2026-09-11 加速路线。

- [ ] **Step 1: 在文档顶部增加更新说明**

声明 2026-09-11 起新章节覆盖原计划中冲突的手写比例、日期和教学流程，原 W1～W2 内容仅作历史参考。

- [ ] **Step 2: 增加 AI 工程模式和周时间分配**

写明每周 17 小时基准：项目/审查 7 小时、概念 3 小时、故障/测试 3 小时、SQL/算法 2 小时、复盘/求职 2 小时。

- [ ] **Step 3: 增加 W3 起加速时间线**

覆盖 FastAPI/HTTP、PostgreSQL/ORM/权限、Linux/Docker/CI、模型 API/工具调用、Agent 可靠性、安全、RAG、评测和投递。

- [ ] **Step 4: 增加每单元闭环和掌握门槛**

每单元包含解释、操作、排错、变式；核心项至少 L3，Python/HTTP/SQL/Git/测试/工具调用各保留一项 L4。

- [ ] **Step 5: 更新当前启动清单**

将旧 W1 启动内容标为历史，当前入口设为 FastAPI/HTTP 单元。

- [ ] **Step 6: 检查必要技术栈覆盖**

Run: `rg -n "FastAPI|PostgreSQL|Docker|工具调用|RAG|评测|L4" Agent开发实习学习与求职计划_2026.md`

Expected: 每个关键词都有明确学习和验收上下文。

### Task 3: 迁移当前进度

**Files:**
- Modify: `学习进度.md`
- Create: `学习记录/2026-09-11-04.md`

**Interfaces:**
- Consumes: 既有 W1～W2 证据和新设计。
- Produces: 功能完成与能力证据分离后的当前状态，以及唯一下一任务 `W3-AI-01`。

- [ ] **Step 1: 保留历史任务证据**

不更改已有贡献事实；将 W1～W2 总结为功能覆盖完成、能力随用随验，单项状态继续保留待验收。

- [ ] **Step 2: 新增能力矩阵**

根据现有运行和口头证据保守记录 Python/SQLite/pytest 为 L2；Git、HTTP、后端、Agent 等没有充分证据的项目保持 L0/L1。

- [ ] **Step 3: 设置当前任务**

当前阶段改为 FastAPI 与 HTTP；唯一下一任务为 `W3-AI-01`：建立请求数据流概念图，由 AI 创建最小 API 和测试，学习者负责运行、解释和 404/422 故障定位。

- [ ] **Step 4: 创建调整日志**

记录用户批准 AI 工程模式、没有将前两周功能直接提升为独立掌握，以及后续手写最小量。

- [ ] **Step 5: 验证三份状态一致**

Run: `rg -n "W3-AI-01|AI 工程模式|L0|L4" AGENTS.md Agent开发实习学习与求职计划_2026.md 学习进度.md 学习记录/2026-09-11-04.md`

Expected: 教学规则、总路线、动态进度和本次日志对当前模式及下一任务描述一致。

### Task 4: 最终文档验证

**Files:**
- Test: `AGENTS.md`
- Test: `Agent开发实习学习与求职计划_2026.md`
- Test: `学习进度.md`
- Test: `学习记录/2026-09-11-04.md`

**Interfaces:**
- Consumes: Tasks 1～3 的文档结果。
- Produces: 可供后续 Agent 无歧义执行的学习状态。

- [ ] **Step 1: 检查格式问题**

Run: `git diff --check`

Expected: 无错误。

- [ ] **Step 2: 扫描占位和冲突**

Run: `rg -n "TBD|TODO|从 W1-T01 开始|所有代码必须自己写" AGENTS.md Agent开发实习学习与求职计划_2026.md 学习进度.md`

Expected: 不存在未处理占位或与 AI 工程模式冲突的活动指令。

- [ ] **Step 3: 检查变更范围**

Run: `git status --short`

Expected: 计划涉及的文档可识别；现有用户代码和学习日志没有被无关修改。

- [ ] **Step 4: 提交文档调整**

Run: `git add AGENTS.md Agent开发实习学习与求职计划_2026.md 学习进度.md 学习记录/2026-09-11-04.md docs/superpowers/plans/2026-09-11-ai-engineering-learning-mode.md`

Run: `git commit -m "docs: adopt AI engineering learning mode"`

Expected: 提交仅包含本轮计划与跟踪文档。
