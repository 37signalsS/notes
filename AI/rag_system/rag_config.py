import os
import logging
from typing import Any

import yaml

log = logging.getLogger("rag")

_SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
_NOTES_DIR: str = os.environ.get("RAG_NOTES_DIR") or os.path.normpath(os.path.join(_SCRIPT_DIR, "../../"))
if not os.path.isdir(_NOTES_DIR):
    log.warning("NOTES_DIR does not exist: %s — check RAG_NOTES_DIR env var or script location", _NOTES_DIR)

SCRIPT_DIR = _SCRIPT_DIR
NOTES_DIR = _NOTES_DIR


def set_script_dir(path: str) -> None:
    global SCRIPT_DIR, _SCRIPT_DIR, _CFG_PATH
    _SCRIPT_DIR = SCRIPT_DIR = path
    _CFG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")


def set_notes_dir(path: str) -> None:
    global NOTES_DIR, _NOTES_DIR
    _NOTES_DIR = NOTES_DIR = path


_CFG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

_EXCLUDED_DIRS_DEFAULT = [".git", ".obsidian", "venv", "rag_system"]
_EXCLUDED_FILES_DEFAULT = ["GEMINI.md", "MEMORY.md", ".DS_Store"]
_EXCLUDED_EXTENSIONS_DEFAULT = [".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".py"]

ENGINES_DEFAULT: dict[str, Any] = {
    "e5": {
        "dir": os.path.join(SCRIPT_DIR, "qdrant_db"),
        "collection": "notes_rag_v2",
        "model": "intfloat/multilingual-e5-base",
        "chunk_size": 2000,
        "chunk_overlap": 150,
        "batch_size": 100,
        "label": "E5",
        "query_prefix": "query: ",
        "doc_prefix": "passage: ",
    },
    "bge": {
        "dir": os.path.join(SCRIPT_DIR, "qdrant_bge"),
        "collection": "notes_bge",
        "model": "BAAI/bge-m3",
        "chunk_size": 2000,
        "chunk_overlap": 150,
        "batch_size": 100,
        "label": "BGE-M3",
        "query_prefix": "Represent this query for searching relevant passages: ",
        "doc_prefix": "Represent this document for searching relevant passages: ",
    },
}

RERANKER_MODEL_DEFAULT = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_MAX_CHARS_DEFAULT = 2048
RRF_K_DEFAULT = 60
RRF_DENSE_WEIGHT_DEFAULT = 2
RRF_KEYWORD_WEIGHT_DEFAULT = 2
HYBRID_EXTRA_K_OFFSET_DEFAULT = 50
MMR_DEFAULT_K_DEFAULT = 15
MMR_COMPARE_DEFAULT_K_DEFAULT = 30
MMR_LAMBDA_DEFAULT = 0.5
BM25_K1_DEFAULT = 2.5
BM25_B_DEFAULT = 0.75
HF_HUB_TIMEOUT_DEFAULT = 180

QDRANT_MODE_DEFAULT = "local"
QDRANT_HOST_DEFAULT = "localhost"
QDRANT_PORT_DEFAULT = 6333
QDRANT_DEFAULTS = {
    "mode": QDRANT_MODE_DEFAULT,
    "host": QDRANT_HOST_DEFAULT,
    "port": QDRANT_PORT_DEFAULT,
}


def _resolve_engine_dirs(cfg: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, engine_cfg in cfg.items():
        ec = dict(engine_cfg)
        d = ec.get("dir")
        if d and not os.path.isabs(d):
            ec["dir"] = os.path.join(SCRIPT_DIR, d)
        resolved[name] = ec
    return resolved


def _merge_config(file_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "excluded_dirs": file_cfg.get("excluded", {}).get("dirs", _EXCLUDED_DIRS_DEFAULT),
        "excluded_files": file_cfg.get("excluded", {}).get("files", _EXCLUDED_FILES_DEFAULT),
        "excluded_extensions": file_cfg.get("excluded", {}).get("extensions", _EXCLUDED_EXTENSIONS_DEFAULT),
        "engines": file_cfg.get("engines", ENGINES_DEFAULT),
        "reranker_model": file_cfg.get("reranker", {}).get("model", RERANKER_MODEL_DEFAULT),
        "reranker_max_chars": file_cfg.get("reranker", {}).get("max_chars", RERANKER_MAX_CHARS_DEFAULT),
        "rrf_k": file_cfg.get("rrf", {}).get("k", RRF_K_DEFAULT),
        "rrf_dense_weight": file_cfg.get("rrf", {}).get("dense_weight", RRF_DENSE_WEIGHT_DEFAULT),
        "rrf_keyword_weight": file_cfg.get("rrf", {}).get("keyword_weight", RRF_KEYWORD_WEIGHT_DEFAULT),
        "hybrid_extra_k_offset": file_cfg.get("hybrid", {}).get("extra_k_offset", HYBRID_EXTRA_K_OFFSET_DEFAULT),
        "mmr_default_k": file_cfg.get("mmr", {}).get("default_k", MMR_DEFAULT_K_DEFAULT),
        "mmr_compare_default_k": file_cfg.get("mmr", {}).get("compare_default_k", MMR_COMPARE_DEFAULT_K_DEFAULT),
        "mmr_lambda": file_cfg.get("mmr", {}).get("lambda", MMR_LAMBDA_DEFAULT),
        "bm25_k1": file_cfg.get("bm25", {}).get("k1", BM25_K1_DEFAULT),
        "bm25_b": file_cfg.get("bm25", {}).get("b", BM25_B_DEFAULT),
        "hf_hub_timeout": file_cfg.get("hf_hub_timeout", HF_HUB_TIMEOUT_DEFAULT),
        "qdrant": {**QDRANT_DEFAULTS, **(file_cfg.get("qdrant") or {})},
    }


def _load_config(cfg_path: str = None) -> dict[str, Any]:
    if cfg_path is None:
        cfg_path = _CFG_PATH
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                file_cfg = yaml.safe_load(f) or {}
            merged = _merge_config(file_cfg)
            merged["engines"] = _resolve_engine_dirs(merged["engines"])
            return merged
        except (OSError, yaml.YAMLError) as e:
            log.warning("Failed to load config.yaml: %s — using defaults", e)
    fallback = _merge_config({})
    fallback["engines"] = _resolve_engine_dirs(fallback["engines"])
    return fallback


_cfg: dict[str, Any] = _load_config()

EXCLUDED_DIRS: list[str] = _cfg["excluded_dirs"]
EXCLUDED_FILES: list[str] = _cfg["excluded_files"]
EXCLUDED_EXTENSIONS: list[str] = _cfg["excluded_extensions"]
ENGINES: dict[str, Any] = _cfg["engines"]
RERANKER_MODEL: str = _cfg["reranker_model"]
RERANKER_MAX_CHARS: int = _cfg["reranker_max_chars"]
RRF_K: int = _cfg["rrf_k"]
RRF_DENSE_WEIGHT: int = _cfg["rrf_dense_weight"]
RRF_KEYWORD_WEIGHT: int = _cfg["rrf_keyword_weight"]
HYBRID_EXTRA_K_OFFSET: int = _cfg["hybrid_extra_k_offset"]
MMR_DEFAULT_K: int = _cfg["mmr_default_k"]
MMR_COMPARE_DEFAULT_K: int = _cfg["mmr_compare_default_k"]
MMR_LAMBDA: float = _cfg["mmr_lambda"]
BM25_K1: float = _cfg["bm25_k1"]
BM25_B: float = _cfg["bm25_b"]
HF_HUB_TIMEOUT: int = _cfg["hf_hub_timeout"]
QDRANT_MODE: str = _cfg["qdrant"]["mode"]
QDRANT_HOST: str = _cfg["qdrant"]["host"]
QDRANT_PORT: int = _cfg["qdrant"]["port"]
