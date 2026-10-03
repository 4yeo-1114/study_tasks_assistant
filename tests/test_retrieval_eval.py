from rag import DocumentChunk, KeywordRetriever
from retrieval_eval import RetrievalEvalCase, evaluate_retriever


CHUNKS = [
    DocumentChunk("auth.md", 1, "JWT 认证用户身份，服务端从 token 提取 user_id"),
    DocumentChunk("proposal.md", 2, "confirm 使用 proposal_id 防止重复创建任务"),
    DocumentChunk("sql.md", 3, "SELECT 查询数据库记录"),
]


def test_evaluation_reports_top1_and_top_k_hits_and_no_answer_accuracy():
    cases = [
        RetrievalEvalCase("proposal", "proposal_id 重复创建任务", ("proposal.md",)),
        RetrievalEvalCase("auth", "JWT user_id", ("auth.md",)),
        RetrievalEvalCase("unknown", "Kubernetes 部署", (), expected_empty=True),
    ]

    report = evaluate_retriever(KeywordRetriever(CHUNKS), cases, limit=2)

    assert report.total == 3
    assert report.top1_hits == 2
    assert report.top_k_hits == 2
    assert report.no_answer_correct == 1
    assert report.no_answer_total == 1


def test_evaluation_exposes_wrong_rank_in_details():
    chunks = [
        DocumentChunk("weak.md", 1, "任务 状态 优先级"),
        DocumentChunk("strong.md", 2, "任务"),
    ]
    case = RetrievalEvalCase("ranking", "任务 状态 优先级", ("strong.md",))

    report = evaluate_retriever(KeywordRetriever(chunks), [case], limit=2)

    assert report.top1_hits == 0
    assert report.top_k_hits == 1
    assert "strong.md" in report.results[0].actual_sources
