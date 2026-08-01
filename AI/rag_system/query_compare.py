import sys
import argparse
import json
import time
from typing import Any
import rag_utils
from unified_search import perform_search

_FORMAT_RESULT_MAX_CHARS = 300


def test_query(question: str, engine_type: str, k: int = 30, use_rerank: bool = False, max_chars: int = _FORMAT_RESULT_MAX_CHARS) -> dict[str, Any]:
    start = time.time()
    results = perform_search(question, engine_names=[engine_type], top_k=k, use_rerank=use_rerank)
    duration = time.time() - start

    for r in results:
        content = r["content"]
        if len(content) > max_chars:
            r["content"] = content[:max_chars] + "..."

    return {"engine": engine_type, "time": f"{duration:.2f}s", "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare search results from different engines")
    parser.add_argument("engine", help=f"Engine name: {', '.join(rag_utils.ENGINES)}")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--k", type=int, default=rag_utils.MMR_COMPARE_DEFAULT_K, help="Number of results (default: 30)")
    parser.add_argument("--rerank", action="store_true", help="Apply cross-encoder reranking")
    parser.add_argument("--max-chars", type=int, default=_FORMAT_RESULT_MAX_CHARS, help="Max content length per result")
    args = parser.parse_args()

    if args.engine not in rag_utils.ENGINES:
        print(f"Unknown engine: {args.engine}. Available: {', '.join(rag_utils.ENGINES)}")
        sys.exit(1)

    res = test_query(args.query, args.engine, k=args.k, use_rerank=args.rerank, max_chars=args.max_chars)
    print(json.dumps(res, indent=2, ensure_ascii=False))