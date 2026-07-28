import os
import glob
import re
import math
import hashlib
import logging
import threading
import concurrent.futures
from functools import lru_cache
from typing import Optional, TypedDict

import torch
import yaml

_LOG_LEVEL = getattr(logging, os.environ.get("RAG_LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rag")

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR: str = os.environ.get("RAG_NOTES_DIR") or os.path.normpath(os.path.join(SCRIPT_DIR, "../../"))


class EngineConfig(TypedDict):
    dir: str
    collection: str
    model: str
    chunk_size: int
    chunk_overlap: int
    batch_size: int
    label: str
    query_prefix: str
    doc_prefix: str


_CFG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

_EXCLUDED_DIRS_DEFAULT = [".git", ".obsidian", "venv", "rag_system"]
_EXCLUDED_FILES_DEFAULT = ["GEMINI.md", "MEMORY.md", ".DS_Store"]
_EXCLUDED_EXTENSIONS_DEFAULT = [".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".py"]

_ENGINES_DEFAULT: dict[str, EngineConfig] = {
    "mpnet": {
        "dir": os.path.join(SCRIPT_DIR, "chroma_db"),
        "collection": "notes_rag_v2",
        "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "chunk_size": 1200,
        "chunk_overlap": 200,
        "batch_size": 100,
        "label": "MPNet",
        "query_prefix": "",
        "doc_prefix": "",
    },
    "bge": {
        "dir": os.path.join(SCRIPT_DIR, "chroma_bge"),
        "collection": "notes_bge",
        "model": "BAAI/bge-m3",
        "chunk_size": 1500,
        "chunk_overlap": 250,
        "batch_size": 100,
        "label": "BGE-M3",
        "query_prefix": "Represent this query for searching relevant passages: ",
        "doc_prefix": "Represent this document for searching relevant passages: ",
    },
}

_RERANKER_MODEL_DEFAULT = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
_RERANKER_MAX_CHARS_DEFAULT = 2048
_RRF_K_DEFAULT = 60
_RRF_DENSE_WEIGHT_DEFAULT = 2
_RRF_KEYWORD_WEIGHT_DEFAULT = 2
_HYBRID_EXTRA_K_OFFSET_DEFAULT = 50
_MMR_DEFAULT_K_DEFAULT = 15
_MMR_COMPARE_DEFAULT_K_DEFAULT = 30
_MMR_LAMBDA_DEFAULT = 0.5
_BM25_K1_DEFAULT = 2.5
_BM25_B_DEFAULT = 0.75
_HF_HUB_TIMEOUT_DEFAULT = 180


def _resolve_engine_dirs(cfg: dict) -> None:
    for name, engine_cfg in cfg.items():
        d = engine_cfg.get("dir")
        if d and not os.path.isabs(d):
            engine_cfg["dir"] = os.path.join(SCRIPT_DIR, d)


def _merge_config(file_cfg: dict) -> dict:
    return {
        "excluded_dirs": file_cfg.get("excluded", {}).get("dirs", _EXCLUDED_DIRS_DEFAULT),
        "excluded_files": file_cfg.get("excluded", {}).get("files", _EXCLUDED_FILES_DEFAULT),
        "excluded_extensions": file_cfg.get("excluded", {}).get("extensions", _EXCLUDED_EXTENSIONS_DEFAULT),
        "engines": file_cfg.get("engines", _ENGINES_DEFAULT),
        "reranker_model": file_cfg.get("reranker", {}).get("model", _RERANKER_MODEL_DEFAULT),
        "reranker_max_chars": file_cfg.get("reranker", {}).get("max_chars", _RERANKER_MAX_CHARS_DEFAULT),
        "rrf_k": file_cfg.get("rrf", {}).get("k", _RRF_K_DEFAULT),
        "rrf_dense_weight": file_cfg.get("rrf", {}).get("dense_weight", _RRF_DENSE_WEIGHT_DEFAULT),
        "rrf_keyword_weight": file_cfg.get("rrf", {}).get("keyword_weight", _RRF_KEYWORD_WEIGHT_DEFAULT),
        "hybrid_extra_k_offset": file_cfg.get("hybrid", {}).get("extra_k_offset", _HYBRID_EXTRA_K_OFFSET_DEFAULT),
        "mmr_default_k": file_cfg.get("mmr", {}).get("default_k", _MMR_DEFAULT_K_DEFAULT),
        "mmr_compare_default_k": file_cfg.get("mmr", {}).get("compare_default_k", _MMR_COMPARE_DEFAULT_K_DEFAULT),
        "mmr_lambda": file_cfg.get("mmr", {}).get("lambda", _MMR_LAMBDA_DEFAULT),
        "bm25_k1": file_cfg.get("bm25", {}).get("k1", _BM25_K1_DEFAULT),
        "bm25_b": file_cfg.get("bm25", {}).get("b", _BM25_B_DEFAULT),
        "hf_hub_timeout": file_cfg.get("hf_hub_timeout", _HF_HUB_TIMEOUT_DEFAULT),
    }


def _load_config() -> dict:
    if os.path.exists(_CFG_PATH):
        try:
            with open(_CFG_PATH) as f:
                file_cfg = yaml.safe_load(f) or {}
            merged = _merge_config(file_cfg)
            _resolve_engine_dirs(merged["engines"])
            return merged
        except (OSError, yaml.YAMLError) as e:
            log.warning("Failed to load config.yaml: %s — using defaults", e)
    fallback = _merge_config({})
    _resolve_engine_dirs(fallback["engines"])
    return fallback


_cfg = _load_config()

EXCLUDED_DIRS: list[str] = _cfg["excluded_dirs"]
EXCLUDED_FILES: list[str] = _cfg["excluded_files"]
EXCLUDED_EXTENSIONS: list[str] = _cfg["excluded_extensions"]
ENGINES: dict[str, EngineConfig] = _cfg["engines"]
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

_STEMMER: Optional[object] = None
_STEMMER_LOCK = threading.Lock()
_STEMMER_FAILED: bool = False
_EN_STEMMER: Optional[object] = None
_EN_STEMMER_LOCK = threading.Lock()
_EN_STEMMER_FAILED: bool = False

STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "it", "be", "this",
    "that", "was", "are", "were", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "not", "no", "nor", "so",
    "if", "then", "than", "just", "about", "up", "out", "also", "very",
    "в", "на", "с", "со", "и", "а", "но", "или", "к", "ко", "у",
    "о", "об", "от", "ото", "до", "по", "под", "над", "за",
    "для", "без", "через", "при", "про", "из", "изо",
    "это", "эта", "этот", "что", "как", "так", "все", "его", "ее",
    "их", "нас", "вас", "меня", "тебя", "него", "нее", "них",
    "не", "ни", "да", "нет", "же", "бы", "ли", "если", "то",
    "чтобы", "который", "которая", "которое", "которые",
    "уже", "еще", "ещё", "можно", "нужно", "надо", "будет",
    "быть", "есть", "был", "была", "было", "были",
}


def _get_stemmer():
    global _STEMMER, _STEMMER_FAILED
    if _STEMMER_FAILED:
        return None
    if _STEMMER is not None:
        return _STEMMER
    with _STEMMER_LOCK:
        if _STEMMER is not None:
            return _STEMMER
        try:
            from pymorphy3 import MorphAnalyzer
            _STEMMER = MorphAnalyzer()
        except ImportError:
            log.debug("pymorphy3 не установлен — стемминг русских слов отключён")
            _STEMMER_FAILED = True
    return _STEMMER


def _get_en_stemmer():
    global _EN_STEMMER, _EN_STEMMER_FAILED
    if _EN_STEMMER_FAILED:
        return None
    if _EN_STEMMER is not None:
        return _EN_STEMMER
    with _EN_STEMMER_LOCK:
        if _EN_STEMMER is not None:
            return _EN_STEMMER
        try:
            from nltk.stem import SnowballStemmer
            _EN_STEMMER = SnowballStemmer("english")
        except ImportError:
            log.debug("nltk не установлен — стемминг английских слов отключён")
            _EN_STEMMER_FAILED = True
    return _EN_STEMMER


@lru_cache(maxsize=100000)
def normalize_word(word: str) -> str:
    if not word:
        return word
    if re.search(r'[а-яА-Я]', word):
        stemmer = _get_stemmer()
        if stemmer:
            return stemmer.parse(word)[0].normal_form
    elif re.search(r'[a-zA-Z]', word):
        en_stemmer = _get_en_stemmer()
        if en_stemmer:
            return en_stemmer.stem(word.lower())
    return word.lower()


def get_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def is_excluded(source_path: str) -> bool:
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


class _DocPrefixEmbeddings:
    def __init__(self, inner, doc_prefix: str):
        self._inner = inner
        self._doc_prefix = doc_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self._doc_prefix + t for t in texts]
        return self._inner.embed_documents(prefixed)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)


def _load_with_timeout(func, timeout: int):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log.warning("Timed out after %ss (download may continue in background)", timeout)
            raise TimeoutError(f"Timed out after {timeout}s")


_HF_ENV_LOCK = threading.Lock()


@lru_cache(maxsize=4)
def _load_embedding_model(model_name: str, device: str) -> "HuggingFaceEmbeddings":
    from langchain_huggingface import HuggingFaceEmbeddings

    kwargs: dict = {"model_name": model_name, "model_kwargs": {"device": device}}

    try:
        return _load_with_timeout(lambda: HuggingFaceEmbeddings(**kwargs), HF_HUB_TIMEOUT)
    except (OSError, TimeoutError, Exception) as exc:
        with _HF_ENV_LOCK:
            was = os.environ.get("HF_HUB_OFFLINE")
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                return _load_with_timeout(lambda: HuggingFaceEmbeddings(**kwargs), HF_HUB_TIMEOUT)
            except (OSError, TimeoutError, Exception) as exc2:
                raise RuntimeError(f"Failed to load model {model_name}") from exc2
            finally:
                if was is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = was


def get_embeddings(model_name: str, device: Optional[str] = None, doc_prefix: str = ""):
    if device is None:
        device = get_device()
    emb = _load_embedding_model(model_name, device)
    if doc_prefix:
        return _DocPrefixEmbeddings(emb, doc_prefix)
    return emb


@lru_cache(maxsize=1)
def get_reranker() -> object:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        log.warning("Reranker: sentence-transformers не установлен")
        return None

    device = get_device()
    kwargs = {"model_name": RERANKER_MODEL, "device": device}

    try:
        model = _load_with_timeout(lambda: CrossEncoder(**kwargs), HF_HUB_TIMEOUT)
    except (OSError, TimeoutError, Exception):
        with _HF_ENV_LOCK:
            was = os.environ.get("HF_HUB_OFFLINE")
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                model = _load_with_timeout(lambda: CrossEncoder(**kwargs), HF_HUB_TIMEOUT)
            except (OSError, TimeoutError, Exception):
                log.warning("Reranker: не удалось загрузить модель")
                return None
            finally:
                if was is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = was
    return model


def load_chroma(engine_name: str):
    from langchain_chroma import Chroma as ChromaStore
    cfg = ENGINES[engine_name]
    embeddings = get_embeddings(cfg["model"], doc_prefix=cfg.get("doc_prefix", ""))
    vs = ChromaStore(
        persist_directory=cfg["dir"],
        embedding_function=embeddings,
        collection_name=cfg["collection"],
    )
    return vs, cfg


@lru_cache(maxsize=1)
def _get_embedder_for_model(model_name: str, device: str, doc_prefix: str):
    return get_embeddings(model_name, device, doc_prefix)


def compute_cosine_sim_matrix(embeddings: list[list[float]]) -> list[list[float]]:
    n = len(embeddings)
    if n == 0:
        return []
    emb_t = torch.tensor(embeddings)
    norms = emb_t.norm(dim=1, keepdim=True)
    normalized = emb_t / norms.clamp(min=1e-12)
    sim = normalized @ normalized.T
    return sim.tolist()


def keyword_overlap(query: str, text: str) -> float:
    query_tokens = {normalize_word(w) for w in re.findall(r'\w+', query)} - STOP_WORDS
    if not query_tokens:
        return 0.0
    text_tokens = {normalize_word(w) for w in re.findall(r'\w+', text)}
    if not text_tokens:
        return 0.0
    matched = len(query_tokens & text_tokens)
    return matched / len(query_tokens)


def _tokenize(text: str) -> list[str]:
    return [normalize_word(w) for w in re.findall(r'\w+', text) if normalize_word(w) not in STOP_WORDS]


def bm25_scores(query: str, texts: list[str]) -> list[float]:
    if not texts or not query.strip():
        return [0.0] * len(texts)

    corpus_tokens = [_tokenize(t) for t in texts]
    query_tokens_raw = _tokenize(query)
    query_tokens_uniq = sorted(set(query_tokens_raw))

    if not query_tokens_uniq or not any(corpus_tokens):
        return [0.0] * len(texts)

    n_docs = len(corpus_tokens)
    doc_lens = [len(t) for t in corpus_tokens]
    avgdl = sum(doc_lens) / n_docs if n_docs > 0 else 1.0

    df: dict[str, int] = {}
    for qt in query_tokens_uniq:
        df[qt] = sum(1 for dt in corpus_tokens if qt in dt)

    k1 = BM25_K1
    b = BM25_B
    scores = []
    for i, dt in enumerate(corpus_tokens):
        score = 0.0
        for qt in query_tokens_uniq:
            idf = math.log(1.0 + (n_docs - df[qt] + 0.5) / (df[qt] + 0.5))
            tf = dt.count(qt)
            if tf == 0:
                continue
            norm = 1.0 - b + b * (doc_lens[i] / avgdl) if avgdl > 0 else 1.0
            score += idf * (tf * k1) / (tf + k1 * norm)
        scores.append(score)

    return scores
