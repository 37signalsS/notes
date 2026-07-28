import os
import sys
import json
import shutil
import tempfile
import argparse
from typing import Optional

from tqdm import tqdm
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_chroma import Chroma as ChromaStore

import rag_utils

from unified_search import bust_cache

log = rag_utils.log
MANIFEST_FILE = os.path.join(rag_utils.SCRIPT_DIR, "manifest.json")
MANIFEST_LOCK_FILE = MANIFEST_FILE + ".lock"


class _ManifestLock:
    def __init__(self, path: str):
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

    def __enter__(self):
        import fcntl
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *args):
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
) -> tuple[list, list, dict, dict, dict]:
    manifest = load_manifest()
    engine_state = manifest.get(engine_name, {})
    files_meta = engine_state.get("files", {})

    if os.path.isdir(db_dir) and not files_meta:
        return files, [], manifest, engine_state, {}

    changed = []
    deleted = []
    existing_paths = {rel for _, rel in files}

    for file_path, rel_path in files:
        mtime = os.path.getmtime(file_path)
        entry = files_meta.get(rel_path)
        if force or entry is None or entry.get("mtime") != mtime:
            changed.append((file_path, rel_path))

    for rel_path in list(files_meta.keys()):
        if rel_path not in existing_paths:
            deleted.append(rel_path)

    return changed, deleted, manifest, engine_state, files_meta


def delete_chunks(vectorstore: ChromaStore, ids_to_remove: list[str]) -> None:
    if ids_to_remove and vectorstore is not None:
        vectorstore.delete(ids_to_remove)


def _revalidate_changed(changed: list, fresh_files: dict) -> list:
    still_valid = []
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


def build_text_splitters(cfg: dict) -> tuple:
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "H1"), ("##", "H2"), ("###", "H3"),
        ],
        strip_headers=False
    )
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
        add_start_index=True,
    )
    return header_splitter, text_splitter


def process_files(
    changed_files: list[tuple[str, str]],
    header_splitter: MarkdownHeaderTextSplitter,
    text_splitter: RecursiveCharacterTextSplitter,
) -> tuple[list, list]:
    all_docs = []
    file_chunk_ids = []

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
                ids = [
                    rag_utils.make_chunk_id(rel_path, i, d.page_content)
                    for i, d in enumerate(docs)
                ]
                all_docs.extend(docs)
                file_chunk_ids.append((rel_path, ids, os.path.getmtime(file_path)))
        except Exception as e:
            log.error("Error %s: %s", rel_path, e)

    return all_docs, file_chunk_ids


def ingest(engine_name: str = "", force: bool = False) -> None:
    if not engine_name:
        engine_name = next(iter(rag_utils.ENGINES))
    cfg = rag_utils.ENGINES[engine_name]
    db_dir = cfg["dir"]
    device = rag_utils.get_device()

    log.info("--- %s (%s) on %s ---", cfg['label'], cfg['model'], device.upper())

    files = rag_utils.get_files()
    log.info("  Total .md files: %d", len(files))

    with _ManifestLock(MANIFEST_LOCK_FILE):
        changed, deleted, manifest, engine_state, files_meta = get_changed_files(
            engine_name, files, force, db_dir
        )

        for rel_path in list(files_meta.keys()):
            if rag_utils.is_excluded(rel_path):
                if rel_path not in deleted:
                    deleted.append(rel_path)
                    log.info("  Excluded from index: %s", rel_path)

        if not changed and not deleted:
            log.info("  Index is up to date. Skipping.")
            return

        log.info("  Changed/new: %d, deleted: %d", len(changed), len(deleted))

    doc_prefix = cfg.get("doc_prefix", "")
    embeddings = rag_utils.get_embeddings(cfg["model"], device, doc_prefix)
    header_splitter, text_splitter = build_text_splitters(cfg)

    vectorstore: Optional[ChromaStore] = None
    if os.path.exists(db_dir):
        if force:
            shutil.rmtree(db_dir)
        else:
            try:
                vectorstore = ChromaStore(
                    persist_directory=db_dir,
                    embedding_function=embeddings,
                    collection_name=cfg["collection"],
                )
                vectorstore.similarity_search("", k=1)
            except Exception:
                vectorstore = None

    docs, file_chunk_info = process_files(changed, header_splitter, text_splitter)

    if not docs:
        with _ManifestLock(MANIFEST_LOCK_FILE):
            fresh_manifest = load_manifest()
            fresh_files = fresh_manifest.get(engine_name, {}).get("files", {})
            valid_deleted = _revalidate_deleted(deleted, fresh_files)
            valid_changed = _revalidate_changed(changed, fresh_files)
            old_ids = []
            for rel_path in valid_deleted:
                entry = fresh_files.pop(rel_path, None)
                if entry:
                    old_ids.extend(entry.get("chunk_ids", []))
            for _, rel_path in valid_changed:
                entry = fresh_files.pop(rel_path, None)
                if entry:
                    old_ids.extend(entry.get("chunk_ids", []))
            delete_chunks(vectorstore, old_ids)
            fresh_manifest[engine_name] = {"files": fresh_files}
            save_manifest(fresh_manifest)
        log.info("  No new documents. Index updated.")
        return

    all_ids = []
    for _, ids, _ in file_chunk_info:
        all_ids.extend(ids)

    total = len(docs)
    batch_size = cfg.get("batch_size", 100)
    if vectorstore is None:
        vectorstore = ChromaStore(
            persist_directory=db_dir,
            embedding_function=embeddings,
            collection_name=cfg["collection"],
        )

    with tqdm(total=total, desc="  Embeddings", unit="chunk") as pbar:
        for i in range(0, total, batch_size):
            vectorstore.add_documents(
                docs[i:i + batch_size],
                ids=all_ids[i:i + batch_size],
            )
            pbar.update(min(batch_size, total - i))

    with _ManifestLock(MANIFEST_LOCK_FILE):
        fresh_manifest = load_manifest()
        fresh_files = fresh_manifest.get(engine_name, {}).get("files", {})
        valid_deleted = _revalidate_deleted(deleted, fresh_files)
        valid_changed = _revalidate_changed(changed, fresh_files)

        changed_rel = {rel for _, rel in valid_changed}
        processed_rel = {rel for rel, _, _ in file_chunk_info}

        deleted_ids = []
        for rel_path in valid_deleted:
            entry = fresh_files.pop(rel_path, None)
            if entry:
                deleted_ids.extend(entry.get("chunk_ids", []))
        for _, rel_path in valid_changed:
            entry = fresh_files.pop(rel_path, None)
            if entry:
                deleted_ids.extend(entry.get("chunk_ids", []))
        delete_chunks(vectorstore, deleted_ids)

        for rel_path, ids, mtime in file_chunk_info:
            if rel_path in changed_rel:
                fresh_files[rel_path] = {"mtime": mtime, "chunk_ids": ids}

        fresh_manifest[engine_name] = {"files": fresh_files}
        save_manifest(fresh_manifest)

    log.info("  --- %s ready! ---", cfg['label'])
    bust_cache()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest files into RAG vector store")
    parser.add_argument("engine", nargs="?", default="", help=f"Engine name: {', '.join(rag_utils.ENGINES)}")
    parser.add_argument("--force", "-f", action="store_true", help="Force full rebuild")
    args = parser.parse_args()

    if args.engine not in rag_utils.ENGINES:
        log.error("Unknown engine: %s. Available: %s", args.engine, ', '.join(rag_utils.ENGINES))
        sys.exit(1)

    ingest(args.engine, force=args.force)
