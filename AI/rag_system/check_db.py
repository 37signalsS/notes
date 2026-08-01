import _venv_check; _venv_check.ensure_venv()

import argparse
from typing import Any
import rag_utils

log = rag_utils.log


def check_db(engine_name: str) -> None:
    cfg = rag_utils.ENGINES[engine_name]
    log.info("--- %s ---", cfg['label'])
    log.info("  Directory: %s", cfg['dir'])
    log.info("  Collection: %s", cfg['collection'])
    log.info("  Model: %s", cfg['model'])
    try:
        client, _ = rag_utils.load_qdrant(engine_name)
        collection_name = cfg['collection']
        if not client.collection_exists(collection_name):
            log.error("  Collection does not exist")
            return
            
        info = client.get_collection(collection_name)
        log.info("  Chunks: %d", info.points_count)
        
        if info.points_count > 0:
            sample, _ = client.scroll(
                collection_name=collection_name,
                limit=1,
                with_payload=True
            )
            if sample:
                src = sample[0].payload.get("source")
                log.info("  Sample source: %s", src or 'N/A')
    except Exception as e:
        log.error("Error: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check vector DB status")
    parser.add_argument("--engine", "-e", default=None, help=f"Engine name: {', '.join(rag_utils.ENGINES)}")
    args = parser.parse_args()

    if args.engine:
        check_db(args.engine)
    else:
        check_db("e5")
        check_db("bge")
