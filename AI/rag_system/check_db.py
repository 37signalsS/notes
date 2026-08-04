import _venv_check; _venv_check.ensure_venv()

import os
import json
import argparse
from typing import Any
import rag_utils
from qdrant_client import models

log = rag_utils.log

MANIFEST_FILE = os.path.join(rag_utils.SCRIPT_DIR, "manifest.json")


def _load_manifest() -> dict:
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    return {}


def _count_per_source(client: Any, collection_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    next_offset = None
    while True:
        pts, next_offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            with_payload=["source"],
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


def check_db(engine_name: str, list_limit: int = 10) -> None:
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

        log.info("  --- Validation ---")
        manifest = _load_manifest()
        files_meta = manifest.get(engine_name, {}).get("files", {})
        if not files_meta:
            log.warning("  Manifest has no entries for engine %r — cannot validate", engine_name)
            return

        counts = _count_per_source(client, collection_name)

        coll_sources = set(counts)
        manifest_sources = set(files_meta)

        stale = sorted(coll_sources - manifest_sources)
        missing = []
        mismatched = []
        for rel_path in sorted(manifest_sources):
            expected = len(files_meta[rel_path].get("chunk_ids", []))
            actual = counts.get(rel_path, 0)
            if actual == 0:
                missing.append(rel_path)
            elif actual != expected:
                mismatched.append((rel_path, expected, actual))

        log.info("  Manifest files: %d, distinct sources in collection: %d",
                 len(manifest_sources), len(coll_sources))
        log.info("  Stale sources (in collection, not in manifest): %d", len(stale))
        for src in stale[:list_limit]:
            log.error("    STALE %s (%d chunks)", src, counts[src])
        if len(stale) > list_limit:
            log.error("    ... and %d more", len(stale) - list_limit)

        log.info("  Manifest files with NO vectors in collection: %d", len(missing))
        for rel in missing[:list_limit]:
            log.error("    LOST %s", rel)
        if len(missing) > list_limit:
            log.error("    ... and %d more", len(missing) - list_limit)

        log.info("  Manifest files with mismatched chunk count: %d", len(mismatched))
        for rel, expected, actual in mismatched[:list_limit]:
            log.error("    MISMATCH %s (manifest=%d, collection=%d)", rel, expected, actual)
        if len(mismatched) > list_limit:
            log.error("    ... and %d more", len(mismatched) - list_limit)

        if not stale and not missing and not mismatched:
            log.info("  Validation: OK")
        else:
            log.error("  Validation: %d stale, %d lost, %d mismatched",
                      len(stale), len(missing), len(mismatched))
    except Exception as e:
        log.error("Error: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check and validate vector DB against manifest")
    parser.add_argument("--engine", "-e", default=None, help=f"Engine name: {', '.join(rag_utils.ENGINES)}")
    parser.add_argument("--list", "-l", type=int, default=10, help="Max problem files to list (0 = none)")
    args = parser.parse_args()

    engines = [args.engine] if args.engine else ["e5", "bge"]
    for engine in engines:
        check_db(engine, list_limit=args.list)
