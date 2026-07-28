import argparse
import rag_utils

log = rag_utils.log


def check_db(engine_name: str) -> None:
    cfg = rag_utils.ENGINES[engine_name]
    log.info("--- %s ---", cfg['label'])
    log.info("  Directory: %s", cfg['dir'])
    log.info("  Collection: %s", cfg['collection'])
    log.info("  Model: %s", cfg['model'])
    try:
        vs, _ = rag_utils.load_chroma(engine_name)
        data = vs.get(include=[])
        if data is None:
            log.error("  DB returned None")
            return
        count = len(data.get("ids") or [])
        log.info("  Chunks: %d", count)
        if count > 0:
            sample = vs.get(limit=1)
            src = None
            if sample and sample.get("metadatas"):
                src = sample["metadatas"][0].get("source")
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
        check_db("mpnet")
        check_db("bge")
