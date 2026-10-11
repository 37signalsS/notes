import os
import threading
import logging
from typing import Any, Optional, Protocol
import concurrent.futures

import torch

from rag_config import (
    RERANKER_MODEL,
    RERANKER_MAX_CHARS,
    HF_HUB_TIMEOUT,
    ENGINES,
    MAX_MEMORY_MB,
)

log = logging.getLogger("rag")

# Reduce thread pool size to limit parallel model operations
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)

import atexit
atexit.register(lambda: _THREAD_POOL.shutdown(wait=False))


def get_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class _EmbedderProtocol(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class _DocPrefixEmbeddings:
    def __init__(self, inner: _EmbedderProtocol, doc_prefix: str, inference_lock: threading.Lock) -> None:
        self._inner = inner
        self._doc_prefix = doc_prefix
        self._inference_lock = inference_lock

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self._doc_prefix + t for t in texts]
        with self._inference_lock:
            return self._inner.embed_documents(prefixed)

    def embed_query(self, text: str) -> list[float]:
        with self._inference_lock:
            return self._inner.embed_query(text)


def _load_with_timeout(func: Any, timeout: int) -> Any:
    future = _THREAD_POOL.submit(func)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        log.warning("Timed out after %ss (download may continue in background)", timeout)
        raise TimeoutError(f"Timed out after {timeout}s")


_HF_ENV_LOCK = threading.Lock()

_OFFLINE_LOAD_TIMEOUT = 120


def _with_hf_offline_fallback(func: Any, timeout: int, error_msg: str = "") -> Any:
    with _HF_ENV_LOCK:
        was_hf = os.environ.get("HF_HUB_OFFLINE")
        was_tr = os.environ.get("TRANSFORMERS_OFFLINE")
        explicit_offline = was_hf is not None or was_tr is not None
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            try:
                return _load_with_timeout(func, _OFFLINE_LOAD_TIMEOUT)
            except Exception:
                if explicit_offline:
                    raise RuntimeError("Offline mode requested but models are not cached locally. Run refresh with internet first to cache models.") from None
                pass
        finally:
            if was_hf is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = was_hf
            if was_tr is None:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
            else:
                os.environ["TRANSFORMERS_OFFLINE"] = was_tr
        try:
            return _load_with_timeout(func, timeout)
        except Exception as exc:
            raise RuntimeError(error_msg) from exc


_EMBEDDING_MODEL_LOCK = threading.Lock()
_EMBEDDING_INFERENCE_LOCKS: dict[str, threading.Lock] = {}
_EMBEDDING_INFERENCE_LOCKS_LOCK = threading.Lock()


def _get_embedding_inference_lock(model_name: str) -> threading.Lock:
    with _EMBEDDING_INFERENCE_LOCKS_LOCK:
        if model_name not in _EMBEDDING_INFERENCE_LOCKS:
            _EMBEDDING_INFERENCE_LOCKS[model_name] = threading.Lock()
        return _EMBEDDING_INFERENCE_LOCKS[model_name]


class _LockedEmbedder:
    def __init__(self, inner: _EmbedderProtocol, inference_lock: threading.Lock) -> None:
        self._inner = inner
        self._inference_lock = inference_lock

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self._inference_lock:
            return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        with self._inference_lock:
            return self._inner.embed_query(text)


def _load_embedding_model(model_name: str, device: str) -> "HuggingFaceEmbeddings":
    with _EMBEDDING_MODEL_LOCK:
        cache_key = (model_name, device)
        if not hasattr(_load_embedding_model, "_cache"):
            _load_embedding_model._cache = {}
            _load_embedding_model._cache_maxsize = 2
        cached = _load_embedding_model._cache.get(cache_key)
        if cached is not None:
            return cached
        from langchain_huggingface import HuggingFaceEmbeddings

        kwargs: dict = {"model_name": model_name, "model_kwargs": {"device": device}}
        result = _with_hf_offline_fallback(
            lambda: HuggingFaceEmbeddings(**kwargs),
            HF_HUB_TIMEOUT,
            f"Failed to load model {model_name}",
        )
        if len(_load_embedding_model._cache) >= _load_embedding_model._cache_maxsize:
            _load_embedding_model._cache.pop(next(iter(_load_embedding_model._cache)))
        _load_embedding_model._cache[cache_key] = result
        return result


def _clear_model_caches() -> None:
    if hasattr(_load_embedding_model, "_cache"):
        _load_embedding_model._cache.clear()
    global _reranker_cache
    _reranker_cache = None
    global _sparse_embedding_cache
    _sparse_embedding_cache = None


def _check_and_clear_models_if_needed() -> None:
    """Clear model caches if memory usage is too high."""
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / (1024 * 1024)
        if memory_mb > MAX_MEMORY_MB * 0.8:  # Clear at 80% of limit
            log.warning("Memory usage %.1f MB, clearing model caches", memory_mb)
            _clear_model_caches()
            # Force garbage collection
            import gc
            gc.collect()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
    except ImportError:
        pass


def get_embeddings(model_name: str, device: Optional[str] = None, doc_prefix: str = "") -> Any:
    _check_and_clear_models_if_needed()
    if device is None:
        device = get_device()
    emb = _load_embedding_model(model_name, device)
    inference_lock = _get_embedding_inference_lock(model_name)
    if doc_prefix:
        return _DocPrefixEmbeddings(emb, doc_prefix, inference_lock)
    return _LockedEmbedder(emb, inference_lock)


_RERANKER_LOCK = threading.Lock()
_RERANKER_INFERENCE_LOCK = threading.Lock()
_reranker_cache: Optional[Any] = None


def get_reranker() -> Optional[Any]:
    _check_and_clear_models_if_needed()
    global _reranker_cache
    if _reranker_cache is not None:
        return _reranker_cache
    with _RERANKER_LOCK:
        if _reranker_cache is not None:
            return _reranker_cache
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            log.warning("Reranker: sentence-transformers not installed")
            return None

        device = get_device()
        kwargs = {"model_name": RERANKER_MODEL, "device": device}
        try:
            _reranker_cache = _with_hf_offline_fallback(
                lambda: CrossEncoder(**kwargs),
                HF_HUB_TIMEOUT,
                "Failed to load reranker model",
            )
            return _reranker_cache
        except RuntimeError:
            log.warning("Reranker: failed to load model, skipping reranking")
            return None


_SPARSE_EMBEDDING_LOCK = threading.Lock()
_SPARSE_INFERENCE_LOCK = threading.Lock()
_sparse_embedding_cache: Optional[Any] = None


def get_sparse_embedding_model() -> "SparseTextEmbedding":
    _check_and_clear_models_if_needed()
    global _sparse_embedding_cache
    if _sparse_embedding_cache is not None:
        return _sparse_embedding_cache
    with _SPARSE_EMBEDDING_LOCK:
        if _sparse_embedding_cache is not None:
            return _sparse_embedding_cache
        from fastembed import SparseTextEmbedding
        try:
            _sparse_embedding_cache = _load_with_timeout(
                lambda: SparseTextEmbedding(model_name="Qdrant/bm25"), HF_HUB_TIMEOUT
            )
            return _sparse_embedding_cache
        except Exception as exc:
            raise RuntimeError("Failed to load SparseTextEmbedding") from exc


def get_reranker_inference_lock() -> threading.Lock:
    return _RERANKER_INFERENCE_LOCK


def get_sparse_inference_lock() -> threading.Lock:
    return _SPARSE_INFERENCE_LOCK
