import os
import glob
import re
import hashlib
import logging
import subprocess
import threading
from typing import Optional, Any
import atexit

import torch

from rag_config import (
    SCRIPT_DIR,
    NOTES_DIR,
    set_script_dir,
    set_notes_dir,
    _CFG_PATH as _cfg_path_default,
    _load_config as _load_config_base,
    EXCLUDED_DIRS,
    EXCLUDED_FILES,
    EXCLUDED_EXTENSIONS,
    ENGINES,
    RERANKER_MODEL,
    RERANKER_MAX_CHARS,
    RERANK_SCORE_THRESHOLD,
    HYBRID_EXTRA_K_OFFSET,
    MMR_DEFAULT_K,
    MMR_COMPARE_DEFAULT_K,
    MMR_LAMBDA,
    BM25_K1,
    BM25_B,
    HF_HUB_TIMEOUT,
    MAX_PARALLEL_SEARCHES,
    MAX_MEMORY_MB,
    QDRANT_MODE,
    QDRANT_HOST,
    QDRANT_PORT,
)

from rag_models import (
    get_device,
    get_embeddings,
    get_reranker,
    get_sparse_embedding_model,
    get_reranker_inference_lock,
    get_sparse_inference_lock,
    _clear_model_caches,
    _DocPrefixEmbeddings,
)

from rag_bm25 import (
    normalize_word,
    keyword_overlap,
    bm25_scores,
    is_garbled_chunk,
)

_LOG_LEVEL = getattr(logging, os.environ.get("RAG_LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rag")

if _LOG_LEVEL > logging.DEBUG:
    for _noisy in ("httpx", "httpcore"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

_CFG_PATH = _cfg_path_default


def _load_config() -> dict[str, Any]:
    return _load_config_base(cfg_path=_CFG_PATH)


if not os.path.isdir(NOTES_DIR):
    log.warning("NOTES_DIR does not exist: %s — check RAG_NOTES_DIR env var or script location", NOTES_DIR)


_SIM_MATRIX_WARN_THRESHOLD = 1000

def compute_cosine_sim_matrix(embeddings: list[list[float]]) -> list[list[float]]:
    n = len(embeddings)
    if n == 0:
        return []
    if n > _SIM_MATRIX_WARN_THRESHOLD:
        log.warning("compute_cosine_sim_matrix: large input (%d vectors), may be slow", n)
    emb_t = torch.tensor(embeddings)
    norms = emb_t.norm(dim=1, keepdim=True)
    normalized = emb_t / norms.clamp(min=1e-12)
    sim = normalized @ normalized.T
    return sim.tolist()


def is_excluded(source_path: Optional[str]) -> bool:
    if not source_path:
        return False
    _, ext = os.path.splitext(source_path)
    if ext.lower() in EXCLUDED_EXTENSIONS:
        return True
    filename = os.path.basename(source_path)
    if filename in EXCLUDED_FILES or filename.startswith("."):
        return True
    path_parts = source_path.replace("\\", "/").split("/")
    for part in path_parts:
        if part in EXCLUDED_DIRS:
            return True
    return False


def get_files() -> list[tuple[str, str]]:
    all_files = glob.glob(os.path.join(NOTES_DIR, "**/*.md"), recursive=True)
    result: list[tuple[str, str]] = []
    for f in all_files:
        rel = os.path.relpath(f, NOTES_DIR)
        if not is_excluded(rel):
            result.append((f, rel))
    return result


def make_chunk_id(source_path: str, chunk_index: int, content: str) -> str:
    content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:12]
    source_key = source_path.replace('/', '_').replace('\\', '_')
    return f"{source_key}:{chunk_index}:{content_hash}"


_QDrant_CLIENTS: dict[str, Any] = {}
_QDrant_CLIENTS_LOCK = threading.Lock()


def _ensure_qdrant_server() -> None:
    if QDRANT_MODE != "server":
        return
    from qdrant_client import QdrantClient
    try:
        test = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
        test.get_collections()
        test.close()
        return
    except Exception:
        pass
    script = os.path.join(SCRIPT_DIR, "qdrant_server.sh")
    if not os.path.exists(script):
        log.warning("qdrant_server.sh not found at %s — cannot auto-start Qdrant", script)
        return
    log.info("Qdrant server not reachable at %s:%s — starting...", QDRANT_HOST, QDRANT_PORT)
    result = subprocess.run(["bash", script, "start"], capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Qdrant start script failed:\n%s\n%s", result.stdout, result.stderr)
        return
    for _ in range(30):
        try:
            test = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
            test.get_collections()
            test.close()
            return
        except Exception:
            import time as _time
            _time.sleep(1)
    log.warning("Qdrant server did not become ready at %s:%s", QDRANT_HOST, QDRANT_PORT)


def load_qdrant(engine_name: str) -> tuple[Any, dict[str, Any]]:
    from qdrant_client import QdrantClient
    cfg = ENGINES.get(engine_name)
    if cfg is None:
        raise KeyError(f"Unknown engine: '{engine_name}'. Available: {', '.join(ENGINES)}")
    client = _QDrant_CLIENTS.get(engine_name)
    if client is None:
        with _QDrant_CLIENTS_LOCK:
            client = _QDrant_CLIENTS.get(engine_name)
            if client is None:
                if QDRANT_MODE == "server":
                    _ensure_qdrant_server()
                    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
                else:
                    client = QdrantClient(path=cfg["dir"])
                _QDrant_CLIENTS[engine_name] = client
    return client, cfg


def close_qdrant(engine_name: Optional[str] = None) -> None:
    if engine_name:
        client = _QDrant_CLIENTS.pop(engine_name, None)
        if client:
            client.close()
    else:
        for name in list(_QDrant_CLIENTS):
            close_qdrant(name)


atexit.register(close_qdrant)
