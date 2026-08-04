
import os
import rag_utils
import ingest

def diag():
    engine_name = "bge"
    cfg = rag_utils.ENGINES[engine_name]
    db_dir = cfg["dir"]
    
    files = rag_utils.get_files()
    print(f"Total .md files found by rag_utils.get_files(): {len(files)}")
    
    changed, deleted, manifest, engine_state = ingest.get_changed_files(
        engine_name, files, False, db_dir
    )
    
    print(f"Changed/new files (count: {len(changed)}):")
    for _, rel in changed[:10]:
        print(f"  {rel}")
    if len(changed) > 10:
        print("  ...")
        
    print(f"Deleted files (count: {len(deleted)}):")
    for rel in deleted[:10]:
        print(f"  {rel}")
    if len(deleted) > 10:
        print("  ...")

if __name__ == "__main__":
    diag()
