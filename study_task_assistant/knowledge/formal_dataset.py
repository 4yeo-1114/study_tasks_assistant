"""Build the versioned 120-case retrieval candidate set.

The cases are generated from the public smoke fixture and must be human
reviewed before being called an acceptance set.
"""

from __future__ import annotations

from typing import Any


_QUERY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "auth.md#1": (
        "JWT 中的 user_id 从哪里提取", "服务端如何处理 token 里的用户标识",
        "用户身份字段由哪一侧注入", "token 和 owner_id 的关系是什么",
        "怎样避免模型自行生成 user_id", "认证请求如何得到用户编号",
        "user_id 是客户端传入还是服务端解析", "JWT 身份来源怎么确定",
    ),
    "auth.md#2": (
        "SQL 怎样限制只能读自己的资料", "owner_id 过滤解决什么问题",
        "如何避免跨用户查询", "查询条件怎样隔离用户数据",
        "用户范围过滤应该放在哪里", "文档检索怎样防止越权",
        "数据库读取如何绑定当前用户", "跨账号读取为什么会被拦截",
    ),
    "proposals.md#1": (
        "pending proposal 什么时候创建任务", "用户确认前任务会写入吗",
        "提案状态 pending 表示什么", "创建任务需要经过哪一步确认",
        "任务提案怎样等待用户同意", "确认按钮对应哪个状态",
        "模型生成任务建议后如何处理", "正式任务在确认前是否存在",
    ),
    "proposals.md#2": (
        "怎样避免重复确认写入两条任务", "幂等键防止什么问题",
        "confirm 事务如何保证只写一次", "重复点击确认会发生什么",
        "任务确认的重复提交怎么处理", "idempotency_key 用在什么地方",
        "同一个提案再次确认是否重复创建", "确认接口如何避免重试副作用",
    ),
    "retrieval.md#1": (
        "RRF 如何融合关键词和向量排名", "混合检索是否直接相加分数",
        "关键词召回与向量召回怎样合并", "RRF 的排序依据是什么",
        "两路检索结果如何做排名融合", "RRF 和分数相加有什么区别",
        "混合检索的候选如何去重", "向量和关键词排名怎么合成",
    ),
    "retrieval.md#2": (
        "怎样用 EXPLAIN 检查 pgvector HNSW", "HNSW 索引需要验证什么",
        "向量索引是否被使用如何确认", "PostgreSQL 执行计划怎么看 HNSW",
        "pgvector 的 HNSW 索引如何排查", "检索计划中应该出现哪个索引名",
        "向量查询为什么要看 EXPLAIN", "如何判断数据库走了向量索引",
    ),
    "ingestion.md#1": (
        "Embedding 是逐块生成还是一次完成", "向量编码当前在哪个事务里",
        "文档切块后如何生成 embedding", "入库时向量化的顺序是什么",
        "每个 chunk 的向量怎样计算", "embedding 写入事务有什么影响",
        "批量向量化和数据库写入如何衔接", "当前入库是否把编码放在事务内",
    ),
    "ingestion.md#2": (
        "文档版本什么时候变成 ready", "active_version 的作用是什么",
        "新版本入库失败旧版本会怎样", "如何激活一个文档版本",
        "ready 状态和 active_version 有什么关系", "重建文档失败是否丢失旧数据",
        "哪个版本会参与检索", "文档版本切换如何保证可用",
    ),
    "fitness.md#1": (
        "训练量怎样计算", "重量和次数如何得到训练量",
        "个人纪录应该比较哪些动作", "同一动作的 PR 怎么判断",
        "力量训练的总量公式是什么", "训练进步统计是否跨动作比较",
        "动作组记录需要哪些数值", "训练量能否用重量乘次数表示",
    ),
    "fitness.md#2": (
        "体重趋势应该按什么方式展示", "为什么使用周均体重",
        "体重数据能直接证明增肌吗", "体重记录如何计算趋势",
        "周平均体重有什么作用", "能否根据体重判断体脂变化",
        "体重曲线应该避免什么结论", "体重统计和肌肉增长的关系",
    ),
}


def build_formal_candidate(base: dict[str, Any]) -> dict[str, Any]:
    known = {f"{row['source']}#{row['chunk_id']}" for row in base.get("chunks", [])}
    if set(_QUERY_TEMPLATES) != known:
        raise ValueError("基础 fixture 的 chunk 集合与候选题模板不一致")
    cases: list[dict[str, Any]] = []
    positive = []
    for chunk_id, queries in _QUERY_TEMPLATES.items():
        for index, query in enumerate(queries, start=1):
            positive.append({
                "id": f"p-{chunk_id.replace('#', '-')}-{index:02d}",
                "query": query,
                "relevant_chunks": [chunk_id],
            })
    no_answer_topics = [
        "Redis 集群如何部署", "Kubernetes 滚动升级怎么做", "OAuth 回调地址如何配置",
        "图片 OCR 文字怎样提取", "步数设备如何同步", "血压数据怎么分析",
        "MySQL 分库分表怎么设计", "消息队列怎样保证顺序", "GraphQL 查询如何写",
        "GPU 显存不足怎么处理", "Docker Swarm 和 Kubernetes 区别", "CSS 网格布局怎么调",
        "Transformer 注意力公式是什么", "B 树索引怎样维护", "Redis 过期策略有哪些",
        "Kafka 消费者如何扩容", "OAuth2 access token 如何刷新", "图片压缩质量怎么设置",
        "跑步配速如何安排", "心率区间如何计算", "蛋白质摄入量怎么估计",
        "睡眠阶段如何检测", "体脂秤数据是否准确", "深蹲膝盖疼怎么办",
        "Linux 内核参数怎么修改", "TCP 拥塞控制如何工作", "TLS 握手包含哪些步骤",
        "向量数据库如何分片", "BM25 的公式怎么推导", "大模型温度参数如何选择",
        "React 状态管理怎么做", "FastAPI WebSocket 怎么写", "PostgreSQL 主从复制怎么配",
        "CI/CD 流水线如何部署", "OCR 模型如何训练", "运动手表如何导出 FIT 文件",
        "卧推肩痛应该怎样处理", "增肌期热量盈余怎么计算", "训练后如何安排拉伸",
        "医学诊断模型如何评估",
    ]
    no_answer = [{"id": f"n-{index:03d}", "query": query, "relevant_chunks": []}
                 for index, query in enumerate(no_answer_topics, start=1)]
    if len(positive) != 80 or len(no_answer) != 40:
        raise AssertionError(f"candidate case count positive={len(positive)} no_answer={len(no_answer)}")
    development = positive[:20] + no_answer[:20]
    frozen = positive[20:] + no_answer[20:]
    for case in development:
        cases.append({**case, "split": "development"})
    for case in frozen:
        cases.append({**case, "split": "frozen"})
    return {
        "version": "retrieval-candidate-v1",
        "dataset_kind": "ai_generated_candidate",
        "review_status": "pending_human_review",
        "description": "120-case candidate set generated from public synthetic chunks; not yet acceptance data.",
        "chunks": base["chunks"],
        "cases": cases,
    }
