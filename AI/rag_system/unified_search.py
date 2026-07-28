#!/usr/bin/env python3
import argparse
import json
import time
import os
import sys
import concurrent.futures
from typing import Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_PYTHON = os.path.join(_SCRIPT_DIR, "venv", "bin", "python3")

from langchain_chroma import Chroma as ChromaStore

import rag_utils

log = rag_utils.log

_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_TTL = 300
_SEARCH_CACHE_MAX = 128
_SEARCH_CACHE_VERSION = 0
_FORMAT_RESULT_MAX_CHARS = 400



def bust_cache() -> None:
    global _SEARCH_CACHE_VERSION
    _SEARCH_CACHE_VERSION += 1
    _SEARCH_CACHE.clear()


def _get_score(r: dict) -> float:
    v = r.get("rerank_score")
    return v if v is not None else r.get("score", 0.0)


def deduplicate(results: list[dict]) -> list[dict]:
    seen: dict[int, dict] = {}
    for r in results:
        key = hash((r["source"], r["content"]))
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


def hybrid_search(engine_name: str, query: str, top_k: int, vs: ChromaStore, cfg: dict) -> list[dict]:
    extra_k = top_k + rag_utils.HYBRID_EXTRA_K_OFFSET
    dense_query = cfg.get("query_prefix", "") + query

    entries = []
    try:
        query_emb = vs.embeddings.embed_query(dense_query)
        results = vs._collection.query(
            query_embeddings=[query_emb],
            n_results=extra_k,
            include=["documents", "metadatas", "distances", "embeddings"]
        )
        if results and results.get("documents") and results["documents"][0]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            dists = results["distances"][0]
            embs = results.get("embeddings", [[None]*len(docs)])[0]

            for doc_text, meta, dist, emb in zip(docs, metas, dists, embs):
                source = meta.get("source", "")
                if not source or rag_utils.is_excluded(source):
                    continue
                score = 1.0 / (1.0 + dist)
                entries.append({
                    "source": source,
                    "content": doc_text,
                    "dense_score": score,
                    "keyword_score": 0.0,
                    "embedding": emb
                })
    except Exception as e:
        rag_utils.log.warning("Direct collection query failed: %s, falling back", e)
        raw = vs.similarity_search_with_score(dense_query, k=extra_k)
        for doc, distance in raw:
            source = doc.metadata.get("source", "")
            if not source or rag_utils.is_excluded(source):
                continue
            score = 1.0 / (1.0 + distance)
            entries.append({
                "source": source,
                "content": doc.page_content,
                "dense_score": score,
                "keyword_score": 0.0,
                "embedding": None
            })

    if not entries:
        return []

    contents = [e["content"] for e in entries]
    bm25_raw = rag_utils.bm25_scores(query, contents)
    for e, bm25_val in zip(entries, bm25_raw):
        e["keyword_score"] = bm25_val

    n = len(entries)
    by_dense = sorted(range(n), key=lambda i: entries[i]["dense_score"], reverse=True)
    by_keyword = sorted(range(n), key=lambda i: entries[i]["keyword_score"], reverse=True)

    dense_rank = [0] * n
    keyword_rank = [0] * n
    for pos, idx in enumerate(by_dense):
        dense_rank[idx] = pos
    for pos, idx in enumerate(by_keyword):
        keyword_rank[idx] = pos

    rrf_k = rag_utils.RRF_K
    dense_w = rag_utils.RRF_DENSE_WEIGHT
    keyword_w = rag_utils.RRF_KEYWORD_WEIGHT
    scored = []
    for i, e in enumerate(entries):
        rrf = dense_w / (rrf_k + dense_rank[i])
        if e["keyword_score"] > 0:
            rrf += keyword_w / (rrf_k + keyword_rank[i])
        scored.append({
            "engine": engine_name,
            "source": e["source"],
            "content": e["content"],
            "score": round(rrf, 4),
            "dense_score": round(e["dense_score"], 4),
            "keyword_score": round(e["keyword_score"], 4),
            "embedding": e.get("embedding"),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def rerank(query: str, results: list[dict], reranker) -> list[dict]:
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
) -> list[dict]:
    if engine_names is None:
        engine_names = list(rag_utils.ENGINES.keys())

    cache_key = f"{_SEARCH_CACHE_VERSION}:{query}:{':'.join(sorted(engine_names))}:{top_k}:{use_rerank}"
    now = time.time()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SEARCH_CACHE_TTL:
        _SEARCH_CACHE[cache_key] = (now, cached[1])
        return cached[1]

    def _search_engine(name: str) -> list[dict]:
        try:
            vs, cfg = rag_utils.load_chroma(name)
            return hybrid_search(name, query, top_k, vs, cfg)
        except Exception as e:
            log.error("Search error %s: %s", name, e)
            return []

    if not engine_names:
        return []

    all_results = []
    if len(engine_names) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(engine_names)) as ex:
            for batch in ex.map(_search_engine, engine_names):
                all_results.extend(batch)
    else:
        all_results.extend(_search_engine(engine_names[0]))

    all_results = deduplicate(all_results)

    if use_rerank and len(all_results) > 1:
        reranker = rag_utils.get_reranker()
        if reranker:
            all_results = rerank(query, all_results, reranker)

    emb_matrix = None
    if len(all_results) > top_k and engine_names:
        if all(r.get("embedding") is not None for r in all_results):
            vecs = [r["embedding"] for r in all_results]
            emb_matrix = rag_utils.compute_cosine_sim_matrix(vecs)
        else:
            try:
                eng_name = engine_names[0]
                eng_cfg = rag_utils.ENGINES[eng_name]
                embedder = rag_utils.get_embeddings(
                    eng_cfg["model"],
                    doc_prefix=eng_cfg.get("doc_prefix", ""),
                )
                vecs = embedder.embed_documents([r["content"] for r in all_results])
                emb_matrix = rag_utils.compute_cosine_sim_matrix(vecs)
            except Exception:
                pass

    all_results = mmr_diversify(all_results, query, top_k, emb_matrix=emb_matrix)

    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
        oldest = min(_SEARCH_CACHE.keys(), key=lambda k: _SEARCH_CACHE[k][0])
        del _SEARCH_CACHE[oldest]
    _SEARCH_CACHE[cache_key] = (now, all_results)

    return all_results


def format_result(r: dict, max_chars: int = _FORMAT_RESULT_MAX_CHARS) -> dict:
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
    if sys.executable != _VENV_PYTHON and os.path.exists(_VENV_PYTHON) and not os.environ.get("RAG_VENV_EXEC"):
        try:
            os.environ["RAG_VENV_EXEC"] = "1"
            os.execve(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv, os.environ)
        except OSError as e:
            log.warning("Failed to re-exec into venv (%s), continuing with current interpreter", e)

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
