"""Deterministic synthetic fixtures for retrieval scale experiments.

The generated records are deliberately marked synthetic.  They are useful for
measuring query growth and index plans, but are not a substitute for labeled
production documents or answer-quality evaluation.
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import text


def deterministic_vector(index: int, *, dimension: int) -> tuple[float, ...]:
    """Generate one reproducible nonzero vector without a model call."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 1 or isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
        raise ValueError("index 和 dimension 必须是正整数")
    generator = random.Random(index)
    return tuple(generator.uniform(-1.0, 1.0) for _ in range(dimension))


def neighbor_overlap(actual: list[str], exact: list[str], *, k: int) -> float:
    """Fraction of exact top-k neighbors found in an approximate top-k."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k 必须是正整数")
    denominator = min(k, len(exact))
    return len(set(actual[:k]) & set(exact[:k])) / denominator if denominator else 1.0


def build_scale_dataset(base: dict[str, Any], size: int) -> dict[str, Any]:
    """Return ``base`` with deterministic filler chunks up to ``size`` records."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("size 必须是正整数")
    chunks = [dict(item) for item in base.get("chunks", [])]
    cases = [dict(item) for item in base.get("cases", [])]
    if not chunks or not cases:
        raise ValueError("base fixture 必须包含 chunks 和 cases")
    known = {(str(item["source"]), int(item["chunk_id"])) for item in chunks}
    if len(chunks) > size:
        raise ValueError("size 不能小于基础 fixture 的 chunk 数")
    next_id = 1
    while len(chunks) < size:
        source = "synthetic-scale-filler.md"
        key = (source, next_id)
        next_id += 1
        if key in known:
            continue
        chunks.append({
            "source": source,
            "chunk_id": key[1],
            "text": "synthetic scale filler record with unrelated benchmark text",
        })
        known.add(key)
    return {
        "version": f"{base.get('version', 'fixture')}-scale-{size}",
        "dataset_kind": "synthetic_scale",
        "description": "Synthetic scale fixture; not a production quality benchmark.",
        "target_chunk_count": size,
        "chunks": chunks,
        "cases": cases,
    }


def explain_vector_sql(*, explain: bool = True) -> str:
    """Mirror the production vector query so its plan can be inspected."""
    prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" if explain else ""
    return prefix + """
    SELECT document_chunks.source, document_chunks.chunk_id, document_chunks.content,
           document_chunks.embedding <=> CAST(:query_vector AS vector) AS distance
    FROM document_chunks
    JOIN documents
      ON documents.owner_id = document_chunks.owner_id
     AND documents.source = document_chunks.source
     AND documents.document_version = document_chunks.document_version
    WHERE document_chunks.owner_id = :owner_id
      AND document_chunks.embedding_model = :embedding_model
      AND document_chunks.embedding_dimension = :embedding_dimension
      AND documents.state = 'ready'
      AND documents.active_version = document_chunks.document_version
    ORDER BY document_chunks.embedding <=> CAST(:query_vector AS vector)
    LIMIT :limit
    """


def bare_vector_sql(*, explain: bool = False) -> str:
    """Isolate pgvector ANN behavior without the document lifecycle join."""
    prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" if explain else ""
    return prefix + """
    SELECT source, chunk_id, embedding <=> CAST(:query_vector AS vector) AS distance
    FROM document_chunks
    WHERE owner_id = :owner_id
      AND embedding_model = :embedding_model
      AND embedding_dimension = :embedding_dimension
    ORDER BY embedding <=> CAST(:query_vector AS vector)
    LIMIT :limit
    """


def filtered_vector_sql(*, explain: bool = False, candidate_limit: int = 100) -> str:
    """Use an ANN candidate window before applying document lifecycle filters."""
    if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int) or candidate_limit < 1:
        raise ValueError("candidate_limit 必须是正整数")
    prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" if explain else ""
    return prefix + """
    WITH ann_candidates AS (
        SELECT source, chunk_id, content, document_version,
               embedding <=> CAST(:query_vector AS vector) AS distance
        FROM document_chunks
        WHERE owner_id = :owner_id
          AND embedding_model = :embedding_model
          AND embedding_dimension = :embedding_dimension
        ORDER BY embedding <=> CAST(:query_vector AS vector)
        LIMIT :candidate_limit
    )
    SELECT ann_candidates.source, ann_candidates.chunk_id, ann_candidates.content,
           ann_candidates.distance
    FROM ann_candidates
    JOIN documents
      ON documents.owner_id = :owner_id
     AND documents.source = ann_candidates.source
     AND documents.document_version = ann_candidates.document_version
    WHERE documents.state = 'ready'
      AND documents.active_version = ann_candidates.document_version
    ORDER BY ann_candidates.distance
    LIMIT :limit
    """


def capture_explain_plans(
    sessions: Any,
    *,
    owner_id: int,
    query_vector: list[float] | tuple[float, ...],
    model_name: str,
    dimension: int,
    limit: int = 5,
) -> dict[str, Any]:
    """Capture planner output for indexed and exact vector scans."""
    params = {
        "query_vector": "[" + ",".join(str(float(x)) for x in query_vector) + "]",
        "owner_id": owner_id,
        "embedding_model": model_name,
        "embedding_dimension": dimension,
        "limit": limit,
    }
    result: dict[str, Any] = {}
    for label, prefix in (("planner_default", ""), ("indexscan_disabled", "SET LOCAL enable_indexscan = off;")):
        with sessions.begin() as session:
            if prefix:
                session.execute(text(prefix))
            rows = session.execute(text(explain_vector_sql()), params)
            result[label] = rows.scalar()
    return result


def summarize_plan(explain: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract the actual vector-index decision from PostgreSQL's plan tree."""
    root = explain[0]["Plan"]
    nodes = [root]
    for node in nodes:
        nodes.extend(node.get("Plans", []))
    chunk_scans = [node for node in nodes if node.get("Relation Name") == "document_chunks"]
    return {
        "uses_hnsw": any(node.get("Index Name") == "ix_document_chunks_embedding_hnsw"
                         for node in nodes),
        "chunk_rows_output": sum(int(node.get("Actual Rows", 0)) *
                                   int(node.get("Actual Loops", 1)) for node in chunk_scans
                                   if node.get("Node Type") != "Bitmap Index Scan"),
        "execution_time_ms": explain[0].get("Execution Time"),
    }
