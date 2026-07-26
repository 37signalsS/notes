import rag_utils
from langchain_chroma import Chroma as ChromaStore

log = rag_utils.log

def check_db(engine_name):
    cfg = rag_utils.ENGINES[engine_name]
    db_dir = cfg["dir"]
    log.info("--- %s ---", cfg['label'])
    log.info("  Директория: %s", db_dir)
    log.info("  Коллекция: %s", cfg['collection'])
    log.info("  Модель: %s", cfg['model'])
    try:
        embeddings = rag_utils.get_embeddings(cfg["model"])
        vs = ChromaStore(
            persist_directory=db_dir,
            embedding_function=embeddings,
            collection_name=cfg["collection"]
        )
        count = vs._collection.count()
        log.info("  Чанков: %d", count)
        if count > 0:
            sample = vs._collection.get(limit=1)
            src = None
            if sample.get("metadatas"):
                src = sample["metadatas"][0].get("source")
            log.info("  Пример source: %s", src or 'N/A')
    except Exception as e:
        log.error("Ошибка: %s", e)

if __name__ == "__main__":
    check_db("bge")
    check_db("mpnet")
