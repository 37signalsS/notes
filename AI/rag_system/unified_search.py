#!/usr/bin/env python3
import _venv_check; _venv_check.ensure_venv()

import argparse
import json
import threading
import time
import os
import sys
import warnings
from typing import Any, Optional

from qdrant_client import models
from qdrant_client import QdrantClient

import rag_utils

warnings.filterwarnings("ignore", message="Local mode is not recommended for collections", category=UserWarning)
log = rag_utils.log

_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE_TTL = 300
_SEARCH_CACHE_MAX = 128
_SEARCH_CACHE_VERSION = 0
_FORMAT_RESULT_MAX_CHARS = 400
_MAX_INTERMEDIATE_RESULTS = 200
_MAX_PER_SOURCE = 3


def bust_cache() -> None:
    global _SEARCH_CACHE_VERSION
    with _SEARCH_CACHE_LOCK:
        _SEARCH_CACHE_VERSION += 1
        _SEARCH_CACHE.clear()


def _get_score(r: dict) -> float:
    v = r.get("rerank_score")
    return v if v is not None else r.get("score", 0.0)


def apply_score_threshold(results: list[dict], threshold: Optional[float]) -> list[dict]:
    if threshold is None:
        return results
    return [r for r in results if _get_score(r) >= threshold]


def limit_per_source(results: list[dict], max_per_source: int = _MAX_PER_SOURCE) -> list[dict]:
    counts: dict[str, int] = {}
    filtered: list[dict] = []
    for r in results:
        source = r["source"]
        if counts.get(source, 0) >= max_per_source:
            continue
        counts[source] = counts.get(source, 0) + 1
        filtered.append(r)
    return filtered


def deduplicate(results: list[dict]) -> list[dict]:
    seen: dict[tuple[str, str], dict] = {}
    for r in results:
        key = (r["source"], r["content"])
        score = _get_score(r)
        existing = seen.get(key)
        if existing is None:
            seen[key] = r
        else:
            if score > _get_score(existing):
                seen[key] = r
    return list(seen.values())


def mmr_diversify(results: list[dict], query: str, top_k: int, lbd: float = rag_utils.MMR_LAMBDA, emb_matrix: Optional[list[list[float]]] = None) -> list[dict]:
    if not results or len(results) <= top_k:
        return results[:top_k]

    n = len(results)

    if emb_matrix:
        sim_matrix = emb_matrix
    else:
        sim_matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                s = rag_utils.keyword_overlap(results[i]["content"], results[j]["content"])
                sim_matrix[i][j] = s
                sim_matrix[j][i] = s

    selected_indices = []
    remaining = set(range(n))

    for _ in range(min(top_k, n)):
        best_score = -float("inf")
        best_idx = -1

        for i in remaining:
            rel_score = _get_score(results[i])
            if selected_indices:
                max_sim = max(sim_matrix[i][j] for j in selected_indices)
            else:
                max_sim = 0
            mmr_score = lbd * rel_score - (1 - lbd) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        remaining.remove(best_idx)
        selected_indices.append(best_idx)

    return [results[i] for i in selected_indices]


def hybrid_search(engine_name: str, query: str, top_k: int, client: QdrantClient, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    collection_name = cfg["collection"]
    dense_query = cfg.get("query_prefix", "") + query
    
    dense_emb = rag_utils.get_embeddings(cfg["model"], rag_utils.get_device(), cfg.get("doc_prefix", "")).embed_query(dense_query)
    
    sparse_model = rag_utils.get_sparse_embedding_model()
    sparse_iter = list(sparse_model.embed([query]))[0]
    sparse_vector = models.SparseVector(indices=sparse_iter.indices.tolist(), values=sparse_iter.values.tolist())

    try:
        results = client.query_points(
            collection_name=collection_name,
            prefetch=[
                models.Prefetch(
                    query=dense_emb,
                    using="dense",
                    limit=top_k + rag_utils.HYBRID_EXTRA_K_OFFSET
                ),
                models.Prefetch(
                    query=sparse_vector,
                    using="sparse",
                    limit=top_k + rag_utils.HYBRID_EXTRA_K_OFFSET
                )
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k + rag_utils.HYBRID_EXTRA_K_OFFSET,
            with_payload=True,
            with_vectors=["dense"]
        )
    except Exception:
        rag_utils.log.exception("Qdrant query failed")
        return []

    scored: list[dict[str, Any]] = []
    for point in results.points:
        source = point.payload.get("source", "")
        if not source or rag_utils.is_excluded(source):
            continue
        content = point.payload.get("page_content", "")
        if rag_utils.is_garbled_chunk(content):
            continue
        scored.append({
            "engine": engine_name,
            "source": source,
            "content": point.payload.get("page_content", ""),
            "score": round(point.score, 4),
            "embedding": point.vector.get("dense") if point.vector else None
        })

    return scored[:top_k]


def rerank(query: str, results: list[dict[str, Any]], reranker: Optional[Any]) -> list[dict[str, Any]]:
    if not results or reranker is None:
        return results

    pairs = [(query, r["content"][:rag_utils.RERANKER_MAX_CHARS]) for r in results]
    try:
        scores = reranker.predict(pairs)
        for r, s in zip(results, scores):
            r["rerank_score"] = round(float(s), 4)
        results.sort(key=lambda x: x["rerank_score"], reverse=True)
    except Exception as e:
        log.error("Reranker error: %s", e)

    return results


def perform_search(
    query: str,
    engine_names: Optional[list[str]] = None,
    top_k: int = 50,
    use_rerank: bool = True,
) -> list[dict[str, Any]]:
    if engine_names is None:
        engine_names = list(rag_utils.ENGINES.keys())

    if not engine_names:
        return []

    now = time.time()
    with _SEARCH_CACHE_LOCK:
        cache_key = f"{_SEARCH_CACHE_VERSION}:{query}:{':'.join(sorted(engine_names))}:{top_k}:{use_rerank}"
        cached = _SEARCH_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _SEARCH_CACHE_TTL:
            _SEARCH_CACHE[cache_key] = (now, cached[1])
            return cached[1]

    def _search_engine(name: str) -> list[dict[str, Any]]:
        try:
            cfg = rag_utils.ENGINES.get(name)
            if cfg is None:
                return []
            client, cfg = rag_utils.load_qdrant(name)
            return hybrid_search(name, query, top_k, client, cfg)
        except Exception as e:
            log.error("Search error %s: %s", name, e)
            return []

    all_results: list[dict[str, Any]] = []
    for name in engine_names:
        all_results.extend(_search_engine(name))

    all_results = deduplicate(all_results)

    if len(all_results) > _MAX_INTERMEDIATE_RESULTS:
        all_results = all_results[:_MAX_INTERMEDIATE_RESULTS]

    if use_rerank and len(all_results) > 1:
        reranker = rag_utils.get_reranker()
        if reranker:
            all_results = rerank(query, all_results, reranker)
            all_results = apply_score_threshold(all_results, rag_utils.RERANK_SCORE_THRESHOLD)

    if len(all_results) > top_k:
        mixed_dims = len({len(r.get("embedding", [])) for r in all_results if r.get("embedding")}) > 1
        if mixed_dims:
            mmr_per_engine: list[dict[str, Any]] = []
            for name in engine_names:
                eng_results = [r for r in all_results if r["engine"] == name]
                if eng_results:
                    mmr_per_engine.extend(mmr_diversify(eng_results, query, max(top_k // len(engine_names), 5)))
            all_results = deduplicate(mmr_per_engine) if mmr_per_engine else all_results
        else:
            emb_matrix = None
            try:
                if all(r.get("embedding") is not None for r in all_results):
                    vecs = [r["embedding"] for r in all_results]
                    emb_matrix = rag_utils.compute_cosine_sim_matrix(vecs)
                else:
                    eng_name = engine_names[0]
                    eng_cfg = rag_utils.ENGINES[eng_name]
                    embedder = rag_utils.get_embeddings(
                        eng_cfg["model"],
                        doc_prefix=eng_cfg.get("doc_prefix", ""),
                    )
                    vecs = embedder.embed_documents([r["content"] for r in all_results])
                    emb_matrix = rag_utils.compute_cosine_sim_matrix(vecs)
            except Exception as e:
                log.warning("MMR embedding computation failed: %s", e)
            all_results = mmr_diversify(all_results, query, top_k, emb_matrix=emb_matrix)

    all_results = limit_per_source(all_results)

    with _SEARCH_CACHE_LOCK:
        if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
            oldest = min(_SEARCH_CACHE.keys(), key=lambda k: _SEARCH_CACHE[k][0])
            del _SEARCH_CACHE[oldest]
        _SEARCH_CACHE[cache_key] = (now, all_results)

    return all_results


def format_result(r: dict[str, Any], max_chars: int = _FORMAT_RESULT_MAX_CHARS) -> dict[str, Any]:
    content = r["content"]
    truncated = len(content) > max_chars
    out = {
        "engine": r["engine"],
        "source": r["source"],
        "content": content[:max_chars] + ("..." if truncated else ""),
    }
    v = r.get("rerank_score")
    if v is not None:
        out["rerank_score"] = v
    else:
        out["score"] = r["score"]
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hybrid search across RAG engines")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--exclude", "-e", help="Comma-separated source filters to exclude")
    parser.add_argument("--top-k", type=int, default=50, help="Number of results (default: 50)")
    parser.add_argument("--no-rerank", action="store_true", help="Disable cross-encoder reranking")
    args = parser.parse_args()

    try:
        results = perform_search(args.query, top_k=args.top_k, use_rerank=not args.no_rerank)
        if args.exclude:
            excludes = [x.strip() for x in args.exclude.split(",") if x.strip()]
            results = [r for r in results if not any(ex == part for ex in excludes for part in r["source"].replace("\\", "/").split("/"))]
        output = [format_result(r) for r in results]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
