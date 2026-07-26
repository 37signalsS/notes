import os
import sys
import json
import rag_utils
from langchain_chroma import Chroma as ChromaStore

log = rag_utils.log

def load_chroma(engine_name):
    cfg = rag_utils.ENGINES[engine_name]
    embeddings = rag_utils.get_embeddings(cfg["model"])
    return ChromaStore(
        persist_directory=cfg["dir"],
        embedding_function=embeddings,
        collection_name=cfg["collection"]
    ), cfg

def deduplicate(results):
    seen = set()
    unique = []
    for r in results:
        key = (r["source"], r["content"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

def hybrid_search(engine_name, query, top_k, vs, cfg):
    extra_k = top_k + 50
    # BGE-M3 требует инструкции для запроса
    dense_query = rag_utils.BGE_QUERY_PREFIX + query if engine_name == "bge" else query
    raw = vs.similarity_search_with_score(dense_query, k=extra_k)

    entries = []
    for doc, distance in raw:
        source = doc.metadata.get("source", "")
        if rag_utils.is_excluded(source):
            continue
        # L2 distance → relevance score: 1 / (1 + distance) → [0, 1]
        score = 1.0 / (1.0 + distance)
        kw_score = rag_utils.keyword_overlap(query, doc.page_content)
        entries.append({
            "doc": doc,
            "source": source,
            "content": doc.page_content,
            "dense_score": score,
            "keyword_score": kw_score
        })

    if not entries:
        return []

    # Normalise dense scores to [0, 1] (higher = better)
    dense_vals = [e["dense_score"] for e in entries]
    dmin, dmax = min(dense_vals), max(dense_vals)
    drange = dmax - dmin if dmax > dmin else 1.0

    for e in entries:
        e["dense_norm"] = (e["dense_score"] - dmin) / drange

    # Sort by dense for dense rank, by keyword for keyword rank
    n = len(entries)
    by_dense = sorted(enumerate(entries), key=lambda x: x[1]["dense_score"], reverse=True)
    by_keyword = sorted(enumerate(entries), key=lambda x: x[1]["keyword_score"], reverse=True)

    dense_rank = [0] * n
    keyword_rank = [0] * n
    for pos, (idx, _) in enumerate(by_dense):
        dense_rank[idx] = pos
    for pos, (idx, _) in enumerate(by_keyword):
        keyword_rank[idx] = pos

    # Документы без совпадений по ключевым словам получают худший keyword_rank
    for i, e in enumerate(entries):
        if e["keyword_score"] == 0:
            keyword_rank[i] = n - 1

    RRF_K = 60
    DENSE_W = 1
    KEYWORD_W = 3
    scored = []
    for i, e in enumerate(entries):
        rrf = DENSE_W / (RRF_K + dense_rank[i]) + KEYWORD_W / (RRF_K + keyword_rank[i])
        scored.append({
            "engine": engine_name,
            "source": e["source"],
            "content": e["content"],
            "score": round(rrf, 4),
            "dense_score": round(e["dense_score"], 4),
            "keyword_score": round(e["keyword_score"], 4)
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def try_load_reranker():
    try:
        from sentence_transformers import CrossEncoder
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            return CrossEncoder(rag_utils.RERANKER_MODEL)
        except Exception:
            os.environ.pop("HF_HUB_OFFLINE", None)
            return CrossEncoder(rag_utils.RERANKER_MODEL)
    except ImportError:
        log.warning("Reranker: sentence-transformers не установлен")
        return None
    except Exception:
        log.warning("Reranker: не удалось загрузить модель")
        return None

def rerank(query, results, reranker):
    if not results or reranker is None:
        return results

    pairs = [(query, r["content"][:512]) for r in results]
    try:
        scores = reranker.predict(pairs)
        for r, s in zip(results, scores):
            r["rerank_score"] = round(float(s), 4)
        results.sort(key=lambda x: x["rerank_score"], reverse=True)
    except Exception as e:
        log.error("Reranker ошибка: %s", e)

    return results

def perform_search(query, engine_names=None, top_k=50, use_rerank=True):
    if engine_names is None:
        engine_names = list(rag_utils.ENGINES.keys())

    all_results = []

    for name in engine_names:
        try:
            vs, cfg = load_chroma(name)
            results = hybrid_search(name, query, top_k, vs, cfg)
            all_results.extend(results)
        except Exception as e:
            log.error("Search ошибка %s: %s", name, e)

    all_results = deduplicate(all_results)

    if use_rerank and len(all_results) > 1:
        reranker = try_load_reranker()
        if reranker:
            all_results = rerank(query, all_results, reranker)

    return all_results

def format_result(r):
    out = {
        "engine": r["engine"],
        "source": r["source"],
        "content": r["content"][:400] + "..."
    }
    if "rerank_score" in r:
        out["rerank_score"] = r["rerank_score"]
    else:
        out["score"] = r["score"]
    return out

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Query required"}))
        sys.exit(1)

    query = sys.argv[1]
    cmd_excludes = sys.argv[2].split(",") if len(sys.argv) > 2 else []

    try:
        results = perform_search(query)
        if cmd_excludes:
            results = [r for r in results if not any(ex in r["source"] for ex in cmd_excludes if ex)]
        output = [format_result(r) for r in results]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
