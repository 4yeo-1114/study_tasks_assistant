import json
from collections.abc import Callable, Sequence
from time import perf_counter
from dataclasses import dataclass

from rag import KeywordRetriever, SearchResult
from rag_grounding import GroundedAnswer
from embedding_retrieval import VectorRetriever


@dataclass(frozen=True)
class RetrievalEvalCase:
    name: str
    query: str
    expected_sources: tuple[str, ...]
    expected_empty: bool = False


@dataclass(frozen=True)
class RetrievalEvalResult:
    name: str
    passed: bool
    actual_sources: tuple[str, ...]
    top1_hit: bool
    top_k_hit: bool
    no_answer_correct: bool
    expected_empty: bool
    details: str


@dataclass(frozen=True)
class RetrievalEvalReport:
    results: tuple[RetrievalEvalResult, ...]
#把一个方法变成“像访问普通属性一样”来调用。
    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def top1_hits(self) -> int:
        return sum(result.top1_hit for result in self.results if not result.no_answer_correct)

    @property
    def top_k_hits(self) -> int:
        return sum(result.top_k_hit for result in self.results if not result.no_answer_correct)

    @property
    def no_answer_correct(self) -> int:
        return sum(result.no_answer_correct for result in self.results)

    @property
    def no_answer_total(self) -> int:
        return sum(result.expected_empty for result in self.results)

##测评函数 要传入检索器以及cases 最后生成报告
def evaluate_retriever(
    retriever: KeywordRetriever,
    cases: list[RetrievalEvalCase],
    *,
    limit: int = 3,
) -> RetrievalEvalReport:
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    results = []
    for case in cases:
        matches = retriever.search(case.query, limit=limit)
        actual_sources = tuple(item.chunk.source for item in matches)
        actual_empty = not actual_sources
        #没有证据时拒接编造
        no_answer_correct = case.expected_empty and actual_empty
        #有证据且第一个证据就是case期待的证据
        top1_hit = bool(actual_sources) and actual_sources[0] in case.expected_sources
        top_k_hit = bool(set(actual_sources) & set(case.expected_sources))

        #是否通过case 要分有证据和无证据
        passed = (
            no_answer_correct
            if case.expected_empty
            else top_k_hit

        )
        #返回测评细节
        details = "passed" if passed else (
            f"expected={case.expected_sources!r} actual={actual_sources!r}"
        )
        #构造测评结果
        results.append(RetrievalEvalResult(
            name=case.name,
            passed=passed,
            actual_sources=actual_sources,
            top1_hit=top1_hit,
            top_k_hit=top_k_hit,
            no_answer_correct=no_answer_correct,
            expected_empty=case.expected_empty,
            details=details,
        ))
    #返回报告
    return RetrievalEvalReport(tuple(results))

@dataclass(frozen=True)
class GroundingEvalResult:
    """One end-to-end case split into retrieval, generation and citation checks."""

    name: str
    retrieval_ok: bool
    answer_generated: bool
    citation_supported: bool
    passed: bool
    details: str


@dataclass(frozen=True)
class GroundingEvalReport:
    results: tuple[GroundingEvalResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(item.passed for item in self.results)

    @property
    def retrieval_failures(self) -> int:
        return sum(not item.retrieval_ok for item in self.results)

    @property
    def citation_failures(self) -> int:
        return sum(
            item.retrieval_ok and not item.citation_supported
            for item in self.results
        )


#测评我们的检索器和生成器
def evaluate_grounded_answers(
    retriever: KeywordRetriever,
    cases: list[RetrievalEvalCase],
    answerer: Callable[[str, list[SearchResult]], GroundedAnswer],
    *,
    limit: int = 3,
) -> GroundingEvalReport:
    """Evaluate retrieval and grounded generation without hiding failure layers."""
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    evaluated: list[GroundingEvalResult] = []
    for case in cases:
        matches = retriever.search(case.query, limit=limit)
        actual_sources = tuple(item.chunk.source for item in matches)
        retrieval_ok = (
            not actual_sources
            if case.expected_empty
            else bool(set(actual_sources) & set(case.expected_sources))
        )

        answer = answerer(case.query, matches)
        answer_generated = bool(answer.text.strip()) and not (
            case.expected_empty and not matches
        )
        citation_supported = answer.supported
        passed = (
            retrieval_ok
            and (not case.expected_empty or not answer_generated)
            and (case.expected_empty or answer_generated)
            and (case.expected_empty or citation_supported)
        )
        details = "passed" if passed else (
            f"retrieval_ok={retrieval_ok} "
            f"answer_generated={answer_generated} "
            f"citation_supported={citation_supported} "
            f"actual={actual_sources!r}"
        )
        evaluated.append(
            GroundingEvalResult(
                name=case.name,
                retrieval_ok=retrieval_ok,
                answer_generated=answer_generated,
                citation_supported=citation_supported,
                passed=passed,
                details=details,
            )
        )
    return GroundingEvalReport(tuple(evaluated))



@dataclass(frozen=True)
class GroundingDiagnosis:
    layer: str
    reason: str

#这个类直接传入检索结果和生成结果 然后判断错误是出现在哪一层
def diagnose_grounding_case(
    case: RetrievalEvalCase,
    matches: list[SearchResult],
    answer: GroundedAnswer,
) -> GroundingDiagnosis:
    """Classify one RAG result so failures can be fixed at the right layer."""
    actual_sources = {item.chunk.source for item in matches}
    expected_sources = set(case.expected_sources)

    if case.expected_empty:
        if matches:
            return GroundingDiagnosis(
                "retrieval",
                "该问题预期没有依据，但检索返回了候选资料",
            )
        return GroundingDiagnosis("passed", "无资料时保持无答案保护")

    if not actual_sources & expected_sources:
        return GroundingDiagnosis(
            "retrieval",
            "期望来源没有进入检索结果",
        )
    if not answer.text.strip():
        return GroundingDiagnosis("generation", "已有资料但模型没有生成回答")
    if not answer.citations:
        return GroundingDiagnosis("citation", "回答没有包含来源引用")
    if not answer.supported:
        return GroundingDiagnosis("citation", "回答引用了本次检索结果之外的来源")
    return GroundingDiagnosis("passed", "检索命中且引用来源合法")


def compare_limits(
    retriever: KeywordRetriever,
    cases: list[RetrievalEvalCase],
    limits: list[int],
) -> dict[int, RetrievalEvalReport]:
    """Run the same evaluation cases with several candidate limits."""
    if not limits:
        raise ValueError("limits 不能为空")
    if len(set(limits)) != len(limits):
        raise ValueError("limits 不能包含重复值")
    return {
        limit: evaluate_retriever(retriever, cases, limit=limit)
        for limit in limits
    }


def evaluate_searcher(
    searcher: Callable[[str, int], Sequence[object]],
    cases: list[RetrievalEvalCase],
    *,
    limit: int = 3,
) -> RetrievalEvalReport:
    """Evaluate any retriever whose results expose a ``chunk`` attribute."""
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    evaluated: list[RetrievalEvalResult] = []
    for case in cases:
        raw_matches = list(searcher(case.query, limit))
        actual_sources = tuple(item.chunk.source for item in raw_matches)
        no_answer_correct = case.expected_empty and not actual_sources
        top1_hit = bool(actual_sources) and actual_sources[0] in case.expected_sources
        top_k_hit = bool(set(actual_sources) & set(case.expected_sources))
        passed = no_answer_correct if case.expected_empty else top_k_hit
        details = "passed" if passed else (
            f"expected={case.expected_sources!r} actual={actual_sources!r}"
        )
        evaluated.append(
            RetrievalEvalResult(
                name=case.name,
                passed=passed,
                actual_sources=actual_sources,
                top1_hit=top1_hit,
                top_k_hit=top_k_hit,
                no_answer_correct=no_answer_correct,
                expected_empty=case.expected_empty,
                details=details,
            )
        )
    return RetrievalEvalReport(tuple(evaluated))


def compare_retrievers(
    retrievers: dict[str, Callable[[str, int], Sequence[object]]],
    cases: list[RetrievalEvalCase],
    *,
    limit: int = 3,
) -> dict[str, RetrievalEvalReport]:
    """Run the same cases against multiple retrieval strategies."""
    if not retrievers:
        raise ValueError("retrievers 不能为空")
    return {
        name: evaluate_searcher(searcher, cases, limit=limit)
        for name, searcher in retrievers.items()
    }


def compare_vector_thresholds(
    retriever: VectorRetriever,
    cases: list[RetrievalEvalCase],
    min_scores: list[float],
    *,
    limit: int = 3,
) -> dict[float, RetrievalEvalReport]:
    """Compare embedding thresholds on the same fixed evaluation cases."""
    if not min_scores:
        raise ValueError("min_scores 不能为空")
    if len(set(min_scores)) != len(min_scores):
        raise ValueError("min_scores 不能包含重复值")
    return {
        #为什么这里要传lambda函数
        # lambda 的作用正是一个接口适配层（Wrapper）：把原本需要 3 个参数的 search 方法，
        # 包装成一个只暴露 2 个参数的标准函数，以便塞给 evaluate_searcher
        min_score: evaluate_searcher(
            lambda query, requested_limit: retriever.search(
                query, limit=requested_limit, min_score=min_score
            ),
            cases,
            limit=limit,
        )
        for min_score in min_scores
    }


@dataclass(frozen=True)
class RetrievalTelemetry:
    """Runtime facts for one retrieval case, separate from
    quality results."""

    case_name: str
    elapsed_ms: float
    candidate_count: int


@dataclass(frozen=True)
class TelemetryReport:
    results: tuple[RetrievalEvalResult, ...]
    #telemetry 性能指标
    telemetry: tuple[RetrievalTelemetry, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def top1_hits(self) -> int:
        return sum(item.top1_hit for item in self.results if not item.no_answer_correct)

    @property
    def top_k_hits(self) -> int:
        return sum(item.top_k_hit for item in self.results if not item.no_answer_correct)


def _as_eval_case(case: RetrievalEvalCase | dict) -> RetrievalEvalCase:
    if isinstance(case, RetrievalEvalCase):
        return case
    return RetrievalEvalCase(
        name=str(case["name"]),
        query=str(case["query"]),
        expected_sources=tuple(case.get("expected_sources", ())),
        expected_empty=bool(case.get("expected_empty", False)),
    )


def evaluate_searcher_with_telemetry(
    searcher: Callable[[str, int], Sequence[object]],
    cases: Sequence[RetrievalEvalCase | dict],
    *,
    limit: int = 3,
) -> TelemetryReport:
    """Evaluate retrieval quality while recording latency and candidate count."""
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    results: list[RetrievalEvalResult] = []
    telemetry: list[RetrievalTelemetry] = []
    for raw_case in cases:
        case = _as_eval_case(raw_case)
        started = perf_counter()
        matches = list(searcher(case.query, limit))
        elapsed_ms = (perf_counter() - started) * 1000
        actual_sources = tuple(item.chunk.source for item in matches)
        no_answer_correct = case.expected_empty and not actual_sources
        top1_hit = bool(actual_sources) and actual_sources[0] in case.expected_sources
        top_k_hit = bool(set(actual_sources) & set(case.expected_sources))
        passed = no_answer_correct if case.expected_empty else top_k_hit
        details = "passed" if passed else (
            f"expected={case.expected_sources!r} actual={actual_sources!r}"
        )
        results.append(RetrievalEvalResult(
            name=case.name,
            passed=passed,
            actual_sources=actual_sources,
            top1_hit=top1_hit,
            top_k_hit=top_k_hit,
            no_answer_correct=no_answer_correct,
            expected_empty=case.expected_empty,
            details=details,
        ))
        telemetry.append(RetrievalTelemetry(case.name, elapsed_ms, len(matches)))
    return TelemetryReport(tuple(results), tuple(telemetry))


def report_to_json(report: TelemetryReport) -> str:
    """Serialize quality and runtime measurements for CI or later analysis."""
    return json.dumps(
        {
            "total": report.total,
            "passed": sum(item.passed for item in report.results),
            "results": [
                {
                    "name": item.name,
                    "passed": item.passed,
                    "actual_sources": item.actual_sources,
                    "top1_hit": item.top1_hit,
                    "top_k_hit": item.top_k_hit,
                    "no_answer_correct": item.no_answer_correct,
                    "details": item.details,
                }
                for item in report.results
            ],
            "telemetry": [
                {
                    "case_name": item.case_name,
                    "elapsed_ms": round(item.elapsed_ms, 3),
                    "candidate_count": item.candidate_count,
                }
                for item in report.telemetry
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def report_to_markdown(report: TelemetryReport) -> str:
    """Render a compact human-readable evaluation report."""
    telemetry = {item.case_name: item for item in report.telemetry}
    lines = [
        f"# Retrieval Evaluation ({sum(item.passed for item in report.results)}/{report.total})",
        "",
        "| case | passed | top1 | top-k | candidates | elapsed_ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in report.results:
        timing = telemetry[item.name]
        lines.append(
            f"| {item.name} | {item.passed} | {item.top1_hit} | "
            f"{item.top_k_hit} | {timing.candidate_count} | {timing.elapsed_ms:.3f} |"
        )
    return "\n".join(lines)
