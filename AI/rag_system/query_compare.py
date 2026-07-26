import sys
import json
import time
import rag_utils
from langchain_chroma import Chroma as ChromaStore

def get_engine(engine_type):
    cfg = rag_utils.ENGINES[engine_type]
    embeddings = rag_utils.get_embeddings(cfg["model"])
    vs = ChromaStore(
        persist_directory=cfg["dir"],
        embedding_function=embeddings,
        collection_name=cfg["collection"]
    )
    return vs

def test_query(question, engine_type, k=30):
    start_time = time.time()
    vs = get_engine(engine_type)

    search_query = rag_utils.BGE_QUERY_PREFIX + question if engine_type == "bge" else question
    results = vs.max_marginal_relevance_search(search_query, k=k, fetch_k=60)

    duration = time.time() - start_time
    output = []
    for res in results:
        source = res.metadata.get("source", "")
        if rag_utils.is_excluded(source):
            continue
        output.append({
            "content": res.page_content[:200] + "...",
            "source": source
        })

    return {"engine": engine_type, "time": f"{duration:.2f}s", "results": output}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python query_compare.py 'engine' 'question'")
        print("Engine: 'bge' or 'mpnet'")
        sys.exit(1)

    engine = sys.argv[1]
    question = sys.argv[2]

    if engine not in rag_utils.ENGINES:
        print(f"Неизвестный движок: {engine}. Доступны: {', '.join(rag_utils.ENGINES.keys())}")
        sys.exit(1)

    res = test_query(question, engine)
    print(json.dumps(res, indent=2, ensure_ascii=False))
