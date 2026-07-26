import os
import sys
import json
import uuid
import shutil
import torch
from tqdm import tqdm
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_chroma import Chroma as ChromaStore

import rag_utils

log = rag_utils.log
MANIFEST_FILE = os.path.join(rag_utils.SCRIPT_DIR, "manifest.json")

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_manifest(manifest):
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

def get_changed_files(engine_name, files, force, db_dir):
    manifest = load_manifest()
    engine_state = manifest.get(engine_name, {})
    files_meta = engine_state.get("files", {})

    # If DB exists but no manifest — seed it with current file mtimes
    if os.path.isdir(db_dir) and not files_meta:
        for file_path, rel_path in files:
            files_meta[rel_path] = {
                "mtime": os.path.getmtime(file_path),
                "chunk_ids": []
            }
        engine_state["files"] = files_meta
        manifest[engine_name] = engine_state
        save_manifest(manifest)
        return [], [], manifest, engine_state, files_meta

    changed = []
    deleted = []

    existing_paths = set()
    for file_path, rel_path in files:
        existing_paths.add(rel_path)
        mtime = os.path.getmtime(file_path)
        entry = files_meta.get(rel_path)
        if force or entry is None or entry.get("mtime") != mtime:
            changed.append((file_path, rel_path))

    for rel_path in files_meta:
        if rel_path not in existing_paths:
            deleted.append(rel_path)

    return changed, deleted, manifest, engine_state, files_meta

def delete_chunks(vectorstore, ids_to_remove):
    if ids_to_remove and vectorstore is not None:
        try:
            vectorstore.delete(ids_to_remove)
        except Exception as e:
            log.error("Ошибка удаления старых чанков: %s", e)

def build_text_splitters(cfg):
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[
        ("#", "H1"), ("##", "H2"), ("###", "H3")
    ])
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
        add_start_index=True
    )
    return header_splitter, text_splitter

def process_files(changed_files, header_splitter, text_splitter):
    all_docs = []
    file_chunk_ids = []

    for file_path, rel_path in tqdm(changed_files, desc="  Разбиение"):
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
                ids = [str(uuid.uuid4()) for _ in docs]
                all_docs.extend(docs)
                file_chunk_ids.append((rel_path, ids, os.path.getmtime(file_path)))
        except Exception as e:
            log.error("Ошибка %s: %s", rel_path, e)

    return all_docs, file_chunk_ids

def ingest(engine_name="mpnet", force=False):
    cfg = rag_utils.ENGINES[engine_name]
    db_dir = cfg["dir"]
    device = rag_utils.get_device()

    log.info("--- %s (%s) на %s ---", cfg['label'], cfg['model'], device.upper())

    files = rag_utils.get_files()
    log.info("  Всего .md файлов: %d", len(files))

    changed, deleted, manifest, engine_state, files_meta = get_changed_files(engine_name, files, force, db_dir)

    # Проверяем, не попали ли уже проиндексированные файлы под новые исключения
    for rel_path in list(files_meta.keys()):
        if rag_utils.is_excluded(rel_path):
            if rel_path not in deleted:
                deleted.append(rel_path)
                log.info("  Исключён из индекса: %s", rel_path)

    if not changed and not deleted:
        log.info("  Индекс актуален. Пропускаем.")
        return

    log.info("  Изменено/новых: %d, удалено: %d", len(changed), len(deleted))

    embeddings = rag_utils.get_embeddings(cfg["model"], device)
    header_splitter, text_splitter = build_text_splitters(cfg)

    # Load or create vectorstore
    vectorstore = None
    if os.path.exists(db_dir) and not force:
        try:
            vectorstore = ChromaStore(
                persist_directory=db_dir,
                embedding_function=embeddings,
                collection_name=cfg["collection"]
            )
            _ = vectorstore.similarity_search("", k=1)
        except Exception:
            vectorstore = None

    if vectorstore is None and os.path.exists(db_dir) and force:
        shutil.rmtree(db_dir)

    # Collect chunk IDs to remove from vectorstore
    ids_to_remove = []
    for _, rel_path in changed:
        entry = files_meta.get(rel_path)
        if entry:
            ids_to_remove.extend(entry.get("chunk_ids", []))
    for rel_path in deleted:
        entry = files_meta.get(rel_path)
        if entry:
            ids_to_remove.extend(entry.get("chunk_ids", []))
        if rel_path in files_meta:
            del files_meta[rel_path]
    for _, rel_path in changed:
        if rel_path in files_meta:
            del files_meta[rel_path]

    delete_chunks(vectorstore, ids_to_remove)

    # Process changed files
    docs, file_chunk_info = process_files(changed, header_splitter, text_splitter)

    if not docs:
        # Only deletions, no new content
        engine_state["files"] = files_meta
        manifest[engine_name] = engine_state
        save_manifest(manifest)
        log.info("  Нет новых документов. Индекс обновлён.")
        return

    # Add to vectorstore with progress
    all_ids = []
    for _, ids, _ in file_chunk_info:
        all_ids.extend(ids)

    total = len(docs)
    BATCH_SIZE = 100
    if vectorstore is None:
        vectorstore = ChromaStore(
            persist_directory=db_dir,
            embedding_function=embeddings,
            collection_name=cfg["collection"]
        )

    with tqdm(total=total, desc="  Эмбеддинги", unit="чанк") as pbar:
        for i in range(0, total, BATCH_SIZE):
            vectorstore.add_documents(
                docs[i:i + BATCH_SIZE],
                ids=all_ids[i:i + BATCH_SIZE]
            )
            pbar.update(min(BATCH_SIZE, total - i))

    # Update manifest
    for rel_path, ids, mtime in file_chunk_info:
        files_meta[rel_path] = {"mtime": mtime, "chunk_ids": ids}

    engine_state["files"] = files_meta
    manifest[engine_name] = engine_state
    save_manifest(manifest)

    log.info("  --- %s готов! ---", cfg['label'])

if __name__ == "__main__":
    engine = "mpnet"
    force = False

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--force" in flags or "-f" in flags:
        force = True

    if args:
        engine = args[0]

    if engine not in rag_utils.ENGINES:
        log.error("Неизвестный движок: %s. Доступны: %s", engine, ', '.join(rag_utils.ENGINES.keys()))
        sys.exit(1)

    ingest(engine, force=force)
