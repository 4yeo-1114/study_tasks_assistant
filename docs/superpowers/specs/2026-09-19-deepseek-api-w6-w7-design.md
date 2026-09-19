# W6–W7 DeepSeek API 与工具型 Agent 学习设计

- 日期：2026-09-19（Asia/Shanghai）
- 项目：`study_task_assistant`
- 学习者目标：在 2026 年 11～12 月投递 Python 后端 / Agent 开发实习前，掌握真实模型 API 调用、工具调用、安全执行和基础评测
- 时间预算：每周 15～20 小时

## 1. 调整原因与范围

原 W6 先用固定假响应学习模型接口，不能满足学习者希望实际调用模型 API 的新要求。调整后，W6 使用 DeepSeek API 学习真实 HTTP 请求、对话、流式响应与客户端封装；W7 将真实 DeepSeek 模型接入任务查询和受控写入工具，形成最小 Agent 闭环。

已有 `FakeModelClient` 保留，用于离线单元测试、超时测试和无余额时的练习，不再作为 W6 的主线。原 W7 的 RAG 内容顺延到 W8，不与首次 API 和工具循环同时引入。

## 2. 技术路线

采用混合路线：

1. 先使用 `curl` 和 Python `httpx` 直接调用 DeepSeek 的 OpenAI 兼容 HTTP 接口，观察 URL、请求头、JSON 请求体、状态码和响应体。
2. 将调用封装为 `DeepSeekClient`，隔离配置、网络错误和响应解析。
3. 工具调用阶段可使用官方文档示例采用的 OpenAI Python SDK，减少协议样板；业务层仍保留自己的模型客户端接口，避免 API SDK 侵入 `TaskService` 和 `TaskRepository`。
4. 在线验收调用真实 DeepSeek API，自动化测试使用假 HTTP 传输或 Fake Client，避免测试产生费用和依赖网络。

默认配置通过环境变量提供：

- `DEEPSEEK_API_KEY`：真实密钥，只存在于本机环境或被 Git 忽略的 `.env`，不得写入日志、测试、文档或提交。
- `DEEPSEEK_BASE_URL`：默认 `https://api.deepseek.com`。
- `DEEPSEEK_MODEL`：由环境变量指定，示例模板给出当前官方可用模型，但业务代码不散落硬编码模型名。

## 3. 组件边界与数据流

### 3.1 普通模型调用

```text
用户输入
  → Python 构造 messages
  → DeepSeekClient 构造 HTTP 请求
  → POST /chat/completions
  → DeepSeek 返回状态码和 JSON
  → 客户端解析文本、usage 或错误
  → 命令行输出结果
```

DeepSeek 的对话 API 按请求处理输入，项目负责保存需要的历史消息，并在下一次请求时重新发送。模型 token 用于计算模型输入输出；Bearer/JWT 用于项目用户认证；`DEEPSEEK_API_KEY` 用于应用向 DeepSeek 认证，三者必须明确区分。

### 3.2 工具调用

```text
已认证用户请求
  → 应用把消息和工具 schema 发给 DeepSeek
  → DeepSeek 返回 tool_calls（调用建议）
  → 应用检查白名单并用 Pydantic 校验参数
  → 应用从认证上下文注入 user_id
  → Service → Repository → PostgreSQL
  → 应用把工具结果回传给 DeepSeek
  → DeepSeek 生成最终回答
```

模型不能直接调用 Python 函数或数据库，也不能决定用户身份。模型生成的 `user_id` 或 `owner_id` 必须拒绝或忽略；真实身份只来自 `current_user_id` 的认证结果。

## 4. W6：DeepSeek API 调用（约 17 小时）

### W6-01：第一次真实请求（3 小时）

- 学习 endpoint、HTTP `POST`、`Authorization: Bearer`、`Content-Type`、请求 JSON 和响应 JSON。
- 先用 `curl` 完成一次最小请求，再用 Python 完成同一请求。
- 能指出输入消息、模型名、响应文本和 token 用量的位置。
- 验收：真实请求成功；密钥未出现在 Git diff、终端回传或学习记录中。

### W6-02：`httpx` 客户端和错误分类（4 小时）

- 封装同步 `DeepSeekClient`，设置连接与读取超时。
- 区分缺少配置、DNS/TCP/TLS、HTTP 401、HTTP 429、HTTP 5xx、超时和非法 JSON。
- 在线测试只运行最小烟雾用例；其余错误通过假传输稳定复现。
- 用户完成一个小变式：修改超时、模型或最大输出配置，并解释实际影响。

### W6-03：多轮消息与用量（3 小时）

- 理解 `system`、`user`、`assistant` 消息和客户端保存历史。
- 观察 `prompt_tokens`、`completion_tokens`、`total_tokens`，记录单次实验的真实用量，不推断长期费用。
- 验收：连续两轮提问，第二轮依赖第一轮上下文；能够解释为何第二次请求需要携带历史。

### W6-04：流式响应（3 小时）

- 学习 SSE、数据块、结束标记/完成事件和中途异常。
- 比较非流式与流式响应的首字时间、完整结果和错误处理差异。
- 验收：能逐块输出文本，并在中断时给出明确错误，不把半截输出当成完整成功。

### W6-05：工程化封装与复盘（4 小时）

- 统一配置、响应类型、异常类型、安全日志与测试替身。
- 全量测试默认离线；真实 API 烟雾测试由显式环境开关启用。
- 两道基础题、一次五分钟闭卷讲解和一次真实 API 故障定位。

**W6 通过标准**：学习者能独立发起并解释一次真实 DeepSeek 请求；能说明 API Key、项目 JWT 和模型 token 的区别；能依据证据定位常见网络/API/解析错误；能完成一个客户端小变式并验证。

## 5. W7：DeepSeek 工具调用与 Agent 循环（约 18 小时）

### W7-01：第一次 Tool Call（3 小时）

- 定义最小函数工具 JSON Schema，向 DeepSeek 发送 `tools`。
- 读取 `tool_calls[].id/name/arguments` 和 `finish_reason`。
- 验收：模型提出工具调用后数据库保持不变；学习者解释“建议”和“执行”的边界。

### W7-02：任务只读工具（4 小时）

- 接入 `list_tasks`、`get_task`，建立工具白名单和 Pydantic 参数模型。
- 身份由后端认证上下文注入，查询始终按当前用户过滤。
- 用户完成一个筛选参数小变式，验证正常、无结果、非法参数和跨用户场景。

### W7-03：完整 Agent 循环（4 小时）

- 实现“模型建议 → 工具执行 → 工具结果回传 → 最终回答”。
- 加最大步骤数、单步/整体超时、未知工具和重复工具调用停止条件。
- 验收：一次请求的数据流可从 API 日志追到模型、工具、Service、Repository 和最终回答。

### W7-04：确认后写入（4 小时）

- `propose_task` 只产生服务器保存的待确认提案。
- 真实用户确认后才调用 `create_task`；提案绑定当前用户、会过期且只能执行一次。
- 验证未确认不写库、确认后只新增一条、重放不重复、他人提案不能执行。

### W7-05：可靠性与评测（3 小时）

- 对超时、429 和部分 5xx 设置有限重试；写操作不得盲目重试。
- 日志包含请求 ID、阶段和耗时，不包含 API Key、JWT、密码和完整敏感提示。
- 固定评测覆盖正常查询、无结果、非法工具、非法参数、越权、未确认写入、重复确认、超时和步数上限。

**W7 通过标准**：真实 DeepSeek 能触发只读任务工具并得到最终回答；所有模型参数经过校验；身份不能由模型伪造；写操作有真实用户确认和幂等保护；循环有停止条件；学习者完成一个工具参数变式并能依据日志定位一次失败。

## 6. 错误处理规则

- 配置缺失：启动或首次调用前报明确配置错误，不打印密钥。
- 401/403：停止并提示检查 API Key 或账户权限，不自动重试。
- 429：读取服务端提示，采用有上限的退避；学习练习不进行高频重试。
- 连接、读取超时：返回可区分的异常；未拿到完整模型结果时不得执行工具。
- 5xx：只对安全的模型读取调用有限重试；数据库写入由提案幂等机制单独保护。
- 非法 JSON、未知工具、非法工具参数：拒绝执行并记录安全的结构化原因。
- 达到最大 Agent 步数：明确停止，不继续消耗 token 或调用工具。

## 7. 测试与证据

- 单元测试：假 HTTP 传输/Fake Client，不访问网络，不消耗额度。
- 集成测试：使用临时数据库验证用户隔离、确认与幂等。
- 在线烟雾测试：显式启用，只发送最小请求；测试输出不包含密钥。
- 用户证据：实际运行命令与去敏后的输出、一次错误定位说明、一次独立小变式、一次完整数据流口述。
- AI 可完成 SDK 样板、错误类、测试框架和重复工具注册；学习者负责配置、运行、解释、排错和关键变式。

## 8. 文档依据

- DeepSeek 第一次 API 调用：<https://api-docs.deepseek.com/>
- Chat Completions：<https://api-docs.deepseek.com/api/create-chat-completion/>
- Tool Calls：<https://api-docs.deepseek.com/guides/tool_calls/>
- 多轮对话：<https://api-docs.deepseek.com/guides/multi_round_chat/>

官方接口、模型名和计费可能变化；进入对应单元时重新核对官方文档。课程代码通过环境变量隔离模型名和基础 URL，以减少这类变化造成的修改范围。
