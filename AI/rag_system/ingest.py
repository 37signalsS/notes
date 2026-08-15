import _venv_check; _venv_check.ensure_venv()

import os
import sys
import json
import re
import hashlib
import shutil
import tempfile
import threading
import argparse
from typing import Optional, Any

import torch

from tqdm import tqdm
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from qdrant_client import models
from qdrant_client import QdrantClient
import uuid

import rag_utils

from unified_search import bust_cache

_COLLECTION_LOCK = threading.Lock()

log = rag_utils.log
MANIFEST_FILE = os.path.join(rag_utils.SCRIPT_DIR, "manifest.json")
MANIFEST_LOCK_FILE = MANIFEST_FILE + ".lock"


def _delete_chunk_ids(client: QdrantClient, collection_name: str, ids_to_remove: list[str]) -> None:
    if ids_to_remove:
        valid_uuids = [str(uuid.uuid5(uuid.NAMESPACE_URL, i)) for i in ids_to_remove]
        client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=valid_uuids))


def _get_source_counts(client: QdrantClient, collection_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    next_offset = None
    while True:
        pts, next_offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            with_payload=["source", "original_id"],
            with_vectors=False,
            offset=next_offset,
        )
        for p in pts:
            src = (p.payload or {}).get("source")
            if src is None:
                src = "<none>"
            counts[src] = counts.get(src, 0) + 1
        if next_offset is None:
            break
    return counts


def _delete_stray_points(client: QdrantClient, collection_name: str, rel_path: str, manifest_ids: set[str]) -> None:
    ids_to_remove = []
    next_offset = None
    while True:
        pts, next_offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            with_payload=["original_id"],
            with_vectors=False,
            offset=next_offset,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value=rel_path))]
            ),
        )
        for p in pts:
            oid = (p.payload or {}).get("original_id")
            if oid is None or oid not in manifest_ids:
                ids_to_remove.append(str(p.id))
        if next_offset is None:
            break
    if ids_to_remove:
        client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=ids_to_remove))


def _delete_source_points(client: QdrantClient, collection_name: str, rel_path: str, null_source: bool = False) -> int:
    ids_to_remove = []
    next_offset = None
    while True:
        pts, next_offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            with_payload=False,
            with_vectors=False,
            offset=next_offset,
            scroll_filter=models.Filter(
                must=[
                    (models.IsEmptyCondition(is_empty=models.PayloadField(key="source"))
                     if null_source else
                     models.FieldCondition(key="source", match=models.MatchValue(value=rel_path)))
                ]
            ),
        )
        for p in pts:
            ids_to_remove.append(str(p.id))
        if next_offset is None:
            break
    if ids_to_remove:
        client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=ids_to_remove))
    return len(ids_to_remove)


class _ManifestLock:
    def __init__(self, path: str) -> None:
        self.path = path
        self.fd: Optional[int] = None
        self._cleanup_stale()

    def _cleanup_stale(self) -> None:
        import time
        lock_path = self.path
        try:
            if os.path.exists(lock_path):
                stale = time.time() - os.path.getmtime(lock_path) > 21600
                if stale:
                    os.unlink(lock_path)
        except OSError:
            pass

    def __enter__(self) -> "_ManifestLock":
        import fcntl
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *args: Any) -> None:
        import fcntl
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def load_manifest() -> dict:
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=rag_utils.SCRIPT_DIR, suffix=".json.tmp")
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        try:
            shutil.move(tmp_path, MANIFEST_FILE)
        except OSError:
            shutil.copy2(tmp_path, MANIFEST_FILE)
            os.unlink(tmp_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_changed_files(
    engine_name: str, files: list[tuple[str, str]], force: bool, db_dir: str
) -> tuple[list[tuple[str, str]], list[str], dict, dict]:
    manifest = load_manifest()
    engine_state = manifest.get(engine_name, {})
    files_meta = engine_state.get("files", {})

    if os.path.isdir(db_dir) and not files_meta:
        return files, [], manifest, engine_state

    changed: list[tuple[str, str]] = []
    deleted: list[str] = []
    existing_paths = {rel for _, rel in files}

    for file_path, rel_path in files:
        mtime = os.path.getmtime(file_path)
        entry = files_meta.get(rel_path)
        if force or entry is None or entry.get("mtime") != mtime:
            changed.append((file_path, rel_path))

    for rel_path in list(files_meta.keys()):
        if rel_path not in existing_paths:
            deleted.append(rel_path)

    return changed, deleted, manifest, engine_state




def _revalidate_changed(changed: list[tuple[str, str]], fresh_files: dict) -> list[tuple[str, str]]:
    still_valid: list[tuple[str, str]] = []
    for file_path, rel_path in changed:
        entry = fresh_files.get(rel_path)
        if entry is None:
            still_valid.append((file_path, rel_path))
        else:
            try:
                if entry.get("mtime") != os.path.getmtime(file_path):
                    still_valid.append((file_path, rel_path))
            except OSError:
                still_valid.append((file_path, rel_path))
    return still_valid


def _revalidate_deleted(deleted: list[str], fresh_files: dict) -> list[str]:
    return [r for r in deleted if r in fresh_files]


def _ensure_collection(client: QdrantClient, collection_name: str, dense_embeddings: Any) -> None:
    with _COLLECTION_LOCK:
        if not client.collection_exists(collection_name=collection_name):
            test_emb = dense_embeddings.embed_query("test")
            client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": models.VectorParams(size=len(test_emb), distance=models.Distance.COSINE, hnsw_config=models.HnswConfigDiff(m=16, ef_construct=200))
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
                }
            )


def _config_fingerprint(cfg: dict) -> str:
    parts = [
        cfg.get("model", ""),
        str(cfg.get("chunk_size", "")),
        str(cfg.get("chunk_overlap", "")),
        str(cfg.get("doc_prefix", "")),
        str(cfg.get("query_prefix", "")),
        "strip_headers=true",
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def _update_manifest(
    engine_name: str,
    client: QdrantClient,
    collection_name: str,
    changed: list[tuple[str, str]],
    deleted: list[str],
    file_chunk_info: list[tuple[str, list[str], float]],
    cfg_hash: Optional[str] = None,
) -> None:
    with _ManifestLock(MANIFEST_LOCK_FILE):
        fresh_manifest = load_manifest()
        fresh_files = fresh_manifest.get(engine_name, {}).get("files", {})
        valid_deleted = _revalidate_deleted(deleted, fresh_files)

        new_ids: set[str] = set()
        for _, ids, _ in file_chunk_info:
            new_ids.update(ids)

        old_ids = []
        for rel_path in valid_deleted:
            entry = fresh_files.pop(rel_path, None)
            if entry:
                old_ids.extend(entry.get("chunk_ids", []))

        for rel_path, ids, mtime in file_chunk_info:
            prev = fresh_files.pop(rel_path, None)
            if prev:
                for cid in prev.get("chunk_ids", []):
                    if cid not in new_ids:
                        old_ids.append(cid)
            fresh_files[rel_path] = {"mtime": mtime, "chunk_ids": ids}

        _delete_chunk_ids(client, collection_name, old_ids)

        engine_meta: dict[str, Any] = {"files": fresh_files}
        if cfg_hash:
            engine_meta["config_hash"] = cfg_hash
        fresh_manifest[engine_name] = engine_meta
        save_manifest(fresh_manifest)


def build_text_splitters(cfg: dict) -> tuple[MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter]:
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "H1"), ("##", "H2"), ("###", "H3"),
        ],
        strip_headers=True
    )
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
        add_start_index=True,
    )
    return header_splitter, text_splitter


def _build_header_chain(header_pairs: list[tuple[str, str]]) -> str:
    chain: list[str] = []
    for _, value in header_pairs:
        if chain and (value in chain[-1] or chain[-1] in value):
            if len(value) > len(chain[-1]):
                chain[-1] = value
            continue
        chain.append(value)
    return " > ".join(chain)


def process_files(
    changed_files: list[tuple[str, str]],
    header_splitter: MarkdownHeaderTextSplitter,
    text_splitter: RecursiveCharacterTextSplitter,
) -> tuple[list, list[tuple[str, list[str], float]]]:
    all_docs = []
    file_chunk_ids: list[tuple[str, list[str], float]] = []

    for file_path, rel_path in tqdm(changed_files, desc="  Splitting"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                continue
            splits = header_splitter.split_text(content)
            docs = []
            for s in splits:
                s.metadata["source"] = rel_path
                docs.extend(text_splitter.split_documents([s]))
            if docs:
                for d in docs:
                    h_levels = [(k, v) for k, v in d.metadata.items() if re.match(r"^H(\d+)$", k)]
                    h_levels.sort(key=lambda kv: int(kv[0][1:]))
                    header_chain = _build_header_chain(h_levels)
                    if header_chain:
                        d.page_content = f"{header_chain} > {d.page_content}"
                clean_docs = [d for d in docs if not rag_utils.is_garbled_chunk(d.page_content)]
                if clean_docs:
                    ids = [
                        rag_utils.make_chunk_id(rel_path, i, d.page_content)
                        for i, d in enumerate(clean_docs)
                    ]
                    all_docs.extend(clean_docs)
                    file_chunk_ids.append((rel_path, ids, os.path.getmtime(file_path)))
        except Exception as e:
            log.error("Error %s: %s", rel_path, e)

    return all_docs, file_chunk_ids


def ingest(engine_name: str = "", force: bool = False, repair: bool = False) -> None:
    if not engine_name:
        engine_name = next(iter(rag_utils.ENGINES))
    cfg = rag_utils.ENGINES[engine_name]
    db_dir = cfg["dir"]
    device = rag_utils.get_device()

    log.info("--- %s (%s) on %s ---", cfg['label'], cfg['model'], device.upper())

    files = rag_utils.get_files()
    log.info("  Total .md files: %d", len(files))

    client, cfg = rag_utils.load_qdrant(engine_name)
    collection_name = cfg["collection"]
    doc_prefix = cfg.get("doc_prefix", "")

    with _ManifestLock(MANIFEST_LOCK_FILE):
        cfg_hash = _config_fingerprint(cfg)
        manifest_pre = load_manifest()
        engine_state_pre = manifest_pre.get(engine_name, {})
        config_changed = bool(engine_state_pre.get("files")) and engine_state_pre.get("config_hash") != cfg_hash
        if config_changed and not force:
            log.info(
                "  Config fingerprint changed (%s -> %s) — full reindex",
                engine_state_pre.get("config_hash"), cfg_hash,
            )
            force = True

        changed, deleted, manifest, engine_state = get_changed_files(
            engine_name, files, force, db_dir
        )
        files_meta = engine_state.get("files", {})

        for rel_path in list(files_meta.keys()):
            if rag_utils.is_excluded(rel_path):
                if rel_path not in deleted:
                    deleted.append(rel_path)
                    log.info("  Excluded from index: %s", rel_path)

        if repair:
            counts = _get_source_counts(client, collection_name)
            stale_sources = [src for src in counts if src != "<none>" and src not in files_meta]
            removed_stale = 0
            for src in stale_sources:
                removed_stale += _delete_source_points(client, collection_name, src)
            none_count = counts.get("<none>", 0)
            if none_count:
                removed_stale += _delete_source_points(client, collection_name, "<none>", null_source=True)
            if removed_stale:
                log.info("  Repair: removed %d stale point(s) from %d unknown source(s)", removed_stale, len(stale_sources) + (1 if none_count else 0))
            changed_rel = {rel for _, rel in changed}
            repaired: list[tuple[str, str]] = []
            for rel_path, entry in files_meta.items():
                expected = len(entry.get("chunk_ids", []))
                actual = counts.get(rel_path, 0)
                if expected and actual != expected and rel_path not in changed_rel:
                    file_path = os.path.join(rag_utils.NOTES_DIR, rel_path)
                    if os.path.isfile(file_path):
                        manifest_ids = set(entry.get("chunk_ids", []))
                        _delete_stray_points(client, collection_name, rel_path, manifest_ids)
                        repaired.append((file_path, rel_path))
            if repaired:
                log.info("  Repair: %d files with mismatched vectors, re-indexing", len(repaired))
                changed.extend(repaired)

        if not changed and not deleted:
            log.info("  Index is up to date. Skipping.")
            return

        log.info("  Changed/new: %d, deleted: %d", len(changed), len(deleted))

        dense_embeddings = rag_utils.get_embeddings(cfg["model"], device, doc_prefix)
        sparse_model = rag_utils.get_sparse_embedding_model()

        if force and client.collection_exists(collection_name=collection_name):
            client.delete_collection(collection_name=collection_name)

        _ensure_collection(client, collection_name, dense_embeddings)

    header_splitter, text_splitter = build_text_splitters(cfg)
    docs, file_chunk_info = process_files(changed, header_splitter, text_splitter)

    if not docs:
        _update_manifest(engine_name, client, collection_name, changed, deleted, [], cfg_hash=cfg_hash)
        log.info("  No new documents. Index updated.")
        return

    all_ids = []
    for _, ids, _ in file_chunk_info:
        all_ids.extend(ids)

    total = len(docs)
    batch_size = cfg.get("batch_size", 100)

    with tqdm(total=total, desc="  Embeddings & Upload", unit="chunk") as pbar:
        for i in range(0, total, batch_size):
            batch_docs = docs[i:i + batch_size]
            batch_ids = all_ids[i:i + batch_size]
            
            texts = [d.page_content for d in batch_docs]
            with torch.no_grad():
                dense_vecs = dense_embeddings.embed_documents(texts)
                sparse_iter = list(sparse_model.embed(texts))
            
            points = []
            for j, doc in enumerate(batch_docs):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, batch_ids[j]))
                sv = sparse_iter[j]
                
                points.append(
                    models.PointStruct(
                        id=point_id,
                        vector={
                            "dense": dense_vecs[j],
                            "sparse": models.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist())
                        },
                        payload={
                            "source": doc.metadata.get("source", ""),
                            "page_content": doc.page_content,
                            "original_id": batch_ids[j]
                        }
                    )
                )
            
            client.upsert(collection_name=collection_name, points=points)
            pbar.update(min(batch_size, total - i))

    _update_manifest(engine_name, client, collection_name, changed, deleted, file_chunk_info, cfg_hash=cfg_hash)

    log.info("  --- %s ready! ---", cfg['label'])
    bust_cache()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest files into RAG vector store")
    parser.add_argument("engine", nargs="?", default="", help=f"Engine name: {', '.join(rag_utils.ENGINES)}")
    parser.add_argument("--force", "-f", action="store_true", help="Force full rebuild")
    parser.add_argument("--repair", "-r", action="store_true",
                        help="Reconcile manifest vs collection: clean stray points and re-index mismatched files")
    args = parser.parse_args()

    if args.engine not in rag_utils.ENGINES:
        log.error("Unknown engine: %s. Available: %s", args.engine, ', '.join(rag_utils.ENGINES))
        sys.exit(1)

    ingest(args.engine, force=args.force, repair=args.repair)
