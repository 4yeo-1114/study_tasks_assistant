# W8-01：RAG 与关键词检索基线

## 核心数据流

```text
学习笔记/文档
  → 切分成 DocumentChunk(source, chunk_id, text)
  → KeywordRetriever 建立候选匹配
用户问题
  → tokenize 提取关键词
  → 计算问题词与每个片段的交集数量
  → 按 score 排序，返回 SearchResult
  → build_context 拼接正文和来源
  → 后续交给模型生成回答
```

检索器返回的是证据片段，不是最终答案。语言模型负责根据问题和这些证据组织自然语言回答。应用必须把来源一起保留，便于引用和检查回答是否有依据。

## 当前实现

- `DocumentChunk` 表示一个已经切好的材料片段。
- `tokenize()` 提取英文单词、数字和简单中文双字词。它是学习用基线，不是完整中文分词器。
- `KeywordRetriever.search()` 计算关键词交集数量作为相关度分数。
- `build_context()` 将命中片段拼成模型上下文；没有命中时明确返回资料不足。
- `SearchResult.score` 让评测可以检查检索排序，而不是只看最终回答措辞。

## 设计边界

关键词检索容易实现、无需 embedding 服务、结果容易解释，但只能识别词语重合。问题中的“重复确认”和材料中的“幂等执行”可能语义相关，却不一定共享关键词。

Embedding 检索把文本转成向量，能处理更多语义相似表达，但需要 embedding 模型、向量存储和相似度阈值。它也可能返回语义相似但事实不相关的片段，因此仍需要来源、阈值和固定评测。

没有命中片段时，系统不能让模型凭训练记忆补答案。应返回“当前资料没有找到依据”，或进入明确的无答案流程。

## 当前代码的学习边界

当前只完成检索基线，还没有接入真实 DeepSeek 生成，也没有引入向量数据库。下一步会加入固定问题集、命中片段检查、引用检查和无答案测试，再比较关键词与 embedding 方法。

## 固定评测基线

`knowledge/retrieval_eval.py` 将固定问题和期望来源保存为 `RetrievalEvalCase`，运行检索器后生成 `RetrievalEvalReport`。

- `top1_hit`：期望来源是否排在第一位。
- `top_k_hit`：期望来源是否出现在返回候选集合中。
- `no_answer_correct`：预期没有依据时，检索器是否返回空结果。

首位命中和候选集合命中必须分开统计。正确来源排在第三位时，Top-K 可能成功，但 Top-1 失败。比较关键词检索和 embedding 检索时，使用同一批问题、同一批资料和同一组指标。
## 引用验证与无答案保护

`knowledge/rag_grounding.py` 负责把检索证据和模型生成连接起来：

1. 没有 `SearchResult` 时，直接返回资料不足，不调用生成器。
2. 有结果时，把带来源的 `build_context()` 传给生成器。
3. 从回答中提取 `[来源: source#chunk_id]`。
4. 只接受本次检索结果中真实存在的来源；没有引用或引用伪造来源时，`supported=False`。

因此，回答是否流畅和回答是否有资料依据是两个不同指标。RAG 评测必须同时检查检索命中、来源合法性和无答案行为。

## W8-04：把检索上下文接入 DeepSeek

`generate_grounded_answer()` 负责把问题、证据和模型生成连接起来：

```text
问题
  → 已完成的 KeywordRetriever.search()
  → build_context()（正文 + [来源: source#chunk_id]）
  → system 约束 + user 问题 + user 资料
  → DeepSeek request_chat()
  → _ground_answer() 校验引用
  → GroundedAnswer
```

`system` 消息规定模型的行为边界：只能依据资料回答、资料不足时承认无法确认、主要结论要带来源。资料消息是证据上下文，不是指令，因此提示词明确说明资料中的文字只作证据。把资料单独作为消息还能减少它被误解为系统规则的风险。

没有检索结果时，函数直接返回无答案，不调用 DeepSeek，避免无依据生成和不必要的 token 消耗。`request_chat()` 只负责 HTTP 请求及响应解析；`knowledge/rag_grounding.py` 负责 RAG 业务规则和来源验证。

引用验证通过不代表每个事实都已被证明：它只检查引用是否存在且属于本次检索结果。模型仍可能误读、夸大或加入证据中没有的内容；逐条事实核验属于更严格的后续能力。


## W8-05：端到端评测

`evaluate_grounded_answers()` 在同一条评测记录中保留三层结果：

- `retrieval_ok`：检索结果是否包含期望来源；
- `answer_generated`：有依据时是否生成回答，无依据时是否保持拒答；
- `citation_supported`：回答中的来源是否属于本次检索结果。

这样可以区分：

```text
检索错：没有找回期望资料
生成错：找到了资料，但回答为空、答非所问或编造
引用错：回答存在，但来源缺失或引用了伪造来源
```

Top-K 命中只表示正确资料进入候选集合，不能证明模型一定使用了它，也不能证明最终事实正确。固定评测应保存问题、候选来源、回答、引用和每层状态，才能比较检索器或提示词修改带来的真实变化。


### 失败诊断

`diagnose_grounding_case()` 根据期望来源、实际检索结果和 `GroundedAnswer` 对失败分层：

- `retrieval`：期望来源没有被检索，或预期无资料却返回了候选；
- `generation`：已有资料但没有生成回答；
- `citation`：回答没有引用，或引用不在本次检索结果中；
- `passed`：检索命中且引用合法，但仍不代表回答的每个事实都已逐条证明。


## W8-07：查询扩展与候选合并

`knowledge/retrieval_strategy.py` 提供两个基础函数：

- `expand_query()` 保留原问题，并加入有限、明确的检索变体；
- `search_with_expansion()` 对每个变体检索，按 `(source, chunk_id)` 去重，保留同一片段的最高分，最后按分数排序并截断 `limit`。

查询扩展只改善检索输入，不生成答案。扩展词必须有边界，避免因为词太多而召回噪声。`limit` 应通过固定评测集比较多个候选值后选择，不能默认认为越大越好。


### Top-K 命中与参数对比

评测 case 通过 `expected_sources` 声明期望来源，实际检索结果通过 `actual_sources` 记录。只要期望来源出现在候选集合中，`top_k_hit` 就为真；它不代表该来源排第一，也不代表模型最终正确使用了它。

`compare_limits()` 可以用同一批 case 批量比较多个 `limit`，例如 `3、5、10`，返回每个 limit 对应的 `RetrievalEvalReport`。最终选择应综合命中率、拒答准确率、引用支持率、上下文长度和 token 成本。


## W8-09：RAG 最小闭环演示

`rag_demo.py` 使用离线生成器演示三条路径：

1. 检索命中并返回本次结果中的合法引用；
2. 检索为空，`answer_with_evidence()` 不调用生成器并返回无资料；
3. 模型输出伪造来源，引用验证失败并被诊断为 `citation`。

离线演示验证的是 RAG 编排和安全边界，不代表真实 DeepSeek 已在线验证。在线路径由 `generate_grounded_answer()` 负责，使用同样的无答案保护和引用校验。


## W8-EMBEDDING-01：接入真实 embedding 模型

`knowledge/embedding_retrieval.py` 保留向量检索的模型无关接口，并新增 `SentenceTransformerEmbeddingModel`：

```text
SentenceTransformerEmbeddingModel
  → encode(text)
  → 固定维度 float 向量
  → VectorRetriever
  → cosine_similarity
  → min_score 过滤
  → limit 截断
```

当前默认模型为 `BAAI/bge-small-zh-v1.5`，通过 `fastembed` 的 ONNX 运行时加载，适合中文学习演示。`embedding_demo.py` 展示真实模型加载和语义检索。首次运行会下载模型，后续从本地缓存加载。项目默认不依赖 PyTorch；另保留 `SentenceTransformerEmbeddingModel` 作为可选适配器。

真实 embedding 接入后，文档索引和查询必须使用同一个模型；更换模型时需要重新生成文档向量。向量检索只能负责语义召回，仍需保留来源、阈值、固定评测和引用校验。


## W8-EMBEDDING-02：比较关键词和真实向量检索

`knowledge/retrieval_eval.py` 新增 `evaluate_searcher()` 和 `compare_retrievers()`。它们只要求检索结果对象具有 `.chunk` 属性，因此可以同时评估：

- `KeywordRetriever` 返回的 `SearchResult`；
- `VectorRetriever` 返回的 `VectorSearchResult`。

`embedding_demo.py` 使用同一批文档和评测 case 对比两种检索器。这样测试的是检索策略差异，评测层不需要知道具体分数如何计算。

注意：关键词分数和向量余弦分数不是同一量纲，不能直接比较分数大小，只比较各自的命中、拒答和最终支持指标。


### 首次对比结果

`embedding_demo.py` 使用同一批文档运行两种检索：

- 语义问题“重复确认会不会重复创建任务？”：关键词检索没有命中 `proposal.md`，embedding 检索命中 `proposal.md#1`。
- 无依据问题“量子计算如何扩容？”：关键词检索正确返回空结果；embedding 在 `min_score=0.25` 下返回了 `database.md#1`，说明阈值过低或小样本语义相似造成误召回。

这个结果说明 embedding 提高了语义召回能力，但不能默认提高无答案准确率。下一步需要在固定评测集上调整 `min_score`，观察召回和误召回之间的平衡。


### W8-EMBEDDING-03：阈值对比

`compare_vector_thresholds()` 使用同一批评测 case，对多个 `min_score` 运行向量检索：

```text
同一 VectorRetriever
  → min_score=0.20
  → min_score=0.25
  → min_score=0.40
  → 分别统计 Top-K 与无答案准确率
```

阈值越低，通常召回更多，但误召回风险更高；阈值越高，通常结果更干净，但可能漏掉真正相关资料。阈值必须通过固定评测选择。


### 阈值评测结果

当前固定样例运行了 `min_score=0.20、0.25、0.40、0.55`：

- `0.20`、`0.25`：能命中语义相关的 `proposal.md`，但无依据问题误召回 `database.md`；
- `0.40`：仍命中 `proposal.md`，无依据问题返回空结果；
- `0.55`：语义问题仍命中 `proposal.md`，并且无依据问题返回空结果，候选更少。

当前小样本下优先选择 `0.40` 作为起始阈值，因为它保留了语义召回，同时恢复了无答案保护。正式项目不能只凭两个 case 固定阈值，还要用更多真实问题验证漏召回率、误召回率和最终引用支持率。


### 阈值评测结果

当前固定样例运行了 `min_score=0.20、0.25、0.40、0.55`：

- `0.20`、`0.25`：能命中语义相关的 `proposal.md`，但无依据问题误召回 `database.md`；
- `0.40`：仍命中 `proposal.md`，无依据问题返回空结果；
- `0.55`：语义问题仍命中 `proposal.md`，并且无依据问题返回空结果，候选更少。

当前小样本下优先选择 `0.40` 作为起始阈值，因为它保留了语义召回，同时恢复了无答案保护。正式项目不能只凭两个 case 固定阈值，还要用更多真实问题验证漏召回率、误召回率和最终引用支持率。


## W8-EMBEDDING-04：索引持久化

`knowledge/embedding_retrieval.py` 新增 `VectorIndex`：

```python
index = retriever.index
index.save("embedding_index.json")
loaded = VectorIndex.load("embedding_index.json")
retriever = VectorRetriever.from_index(loaded, model)
```

索引文件保存：

- `model_name`：建立索引时使用的模型；
- `dimension`：向量维度；
- 每个 chunk 的 `source`、`chunk_id`、`text`；
- 每个 chunk 的 `vector`。

`VectorRetriever.from_index()` 会先检查查询模型名是否和索引记录一致。模型不一致时直接拒绝查询，避免在不同向量空间中计算相似度。

新增 chunk 时可以增量编码并追加；修改文档、切块规则、模型版本或模型配置时，需要重建受影响的向量。


## W8-EMBEDDING-06：最小 pgvector 存储接口

新增 `storage/pgvector_store.py`，把 PostgreSQL 向量表的关键业务边界写成接口：

- `PgVectorConfig`：固定模型名和向量维度；
- `create_table_sql()`：创建 `document_chunks` 表，保存 owner、来源、正文、向量、模型和文档版本；
- `PgVectorStore.insert_chunk()`：校验维度后写入一个分块；
- `PgVectorStore.search()`：在 SQL 的 `WHERE owner_id = :owner_id` 中完成权限过滤，再按 pgvector 距离排序；
- `_as_pgvector()`：把 Python 数字序列转换成 pgvector 文本格式。

SQL 查询返回的是 pgvector 的 cosine distance；接口转换为 `score = 1 - distance`，因此上层仍可复用 `VectorSearchResult`。

这只是最小接口设计，当前环境没有执行 PostgreSQL `vector` 扩展迁移；真实接入前还需要安装扩展、写 Alembic migration、建立索引并配置数据库。


### W8-EMBEDDING-07：Alembic 迁移

新增 `migrations/versions/0005_pgvector_chunks.py`：

- PostgreSQL 才执行 `CREATE EXTENSION vector` 和 `document_chunks` 表创建；
- SQLite 直接跳过，保留现有本地测试和旧功能；
- 表中保存 `owner_id`、来源、正文、向量、模型名、维度和文档版本；
- `UNIQUE(owner_id, source, chunk_id, document_version)` 防止同一用户同一版本重复写入；
- downgrade 删除表和索引，但不删除共享的 vector 扩展。

迁移文件里的向量维度固定为 512，与当前 `BAAI/bge-small-zh-v1.5` 配置一致。以后更换模型或维度，应新增迁移或重新建立索引，不能直接修改历史迁移。
## W8-EMBEDDING-10：接回 RAG 编排层

`generate_grounded_answer_from_retriever()` 位于 `knowledge/rag_grounding.py`，负责把带
`owner_id` 的检索器接到已有的引用校验和 DeepSeek 生成流程：

```text
question + JWT user_id
  → retriever.search(owner_id=...)
  → evidence results
  → 无结果：直接拒答，不调用模型
  → 有结果：build_context(source + content)
  → DeepSeek
  → 校验引用是否来自本次结果
```

`PgVectorRetriever` 和内存 `VectorRetriever` 都返回带 `.chunk` 的结果对象，
因此 `build_context()` 不再依赖某个具体结果类，而是读取统一的 `.chunk` 接口。
这样替换存储后，RAG 的无答案保护、来源保留和引用校验仍然有效。
