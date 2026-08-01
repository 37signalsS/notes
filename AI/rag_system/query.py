import _venv_check; _venv_check.ensure_venv()

import sys
import argparse
import json
from typing import Any
import rag_utils
from unified_search import perform_search


def query(question: str, engine_name: str = "e5", k: int = rag_utils.MMR_DEFAULT_K, use_rerank: bool = True) -> list[dict[str, Any]]:
    results = perform_search(question, engine_names=[engine_name], top_k=k, use_rerank=use_rerank)
    return [
        {"content": r["content"], "metadata": {"source": r["source"]}}
        for r in results
    ]


if __name__ == "__main__":
    engine_list = ", ".join(rag_utils.ENGINES)
    parser = argparse.ArgumentParser(description="Simple hybrid search on a single engine")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--engine", "-e", default="e5", help=f"Engine name: {engine_list}")
    parser.add_argument("--k", type=int, default=rag_utils.MMR_DEFAULT_K, help="Number of results (default: 15)")
    parser.add_argument("--no-rerank", action="store_true", help="Disable cross-encoder reranking")
    args = parser.parse_args()

    if not args.query.strip():
        print("Error: query cannot be empty")
        sys.exit(1)

    if args.engine not in rag_utils.ENGINES:
        print(f"Unknown engine: {args.engine}. Available: {engine_list}")
        sys.exit(1)

    results = query(args.query, args.engine, args.k, use_rerank=not args.no_rerank)
    print(json.dumps(results, indent=2, ensure_ascii=False))