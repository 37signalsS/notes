
import os
import yaml

def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)

cfg = load_config()
EXCLUDED_DIRS = cfg.get("excluded", {}).get("dirs", [])
EXCLUDED_FILES = cfg.get("excluded", {}).get("files", [])
EXCLUDED_EXTENSIONS = cfg.get("excluded", {}).get("extensions", [])

def is_excluded(source_path):
    if not source_path: return False
    _, ext = os.path.splitext(source_path)
    if ext.lower() in EXCLUDED_EXTENSIONS: return True
    filename = os.path.basename(source_path)
    if filename in EXCLUDED_FILES or filename.startswith("."): return True
    path_parts = source_path.replace("\\", "/").split("/")
    for part in path_parts:
        if part in EXCLUDED_DIRS: return True
    return False

def analyze_git_status(status_output):
    lines = status_output.strip().split("\n")
    md_modified = 0
    md_deleted = 0
    excluded = 0
    other = 0
    
    included_modified = []
    included_deleted = []

    for line in lines:
        if not line.strip() or line.startswith("##"): continue
        status = line[:2].strip()
        path = line[3:].strip().strip('"')
        
        # Handle quoted paths with escape sequences if any
        if path.startswith('"'):
             path = path[1:-1]
        
        if is_excluded(path):
            excluded += 1
            continue
            
        if not path.endswith(".md"):
            other += 1
            continue
            
        if "M" in status or "A" in status:
            md_modified += 1
            included_modified.append(path)
        elif "D" in status:
            md_deleted += 1
            included_deleted.append(path)
        else:
            other += 1
            
    print(f"Total lines in git status: {len(lines)}")
    print(f"Excluded by RAG rules: {excluded}")
    print(f"Non-.md files: {other}")
    print(f"Included Modified/Added .md: {md_modified}")
    print(f"Included Deleted .md: {md_deleted}")
    print("\nTop 10 included modified:")
    for p in included_modified[:10]: print(f"  {p}")
    print("\nTop 10 included deleted:")
    for p in included_deleted[:10]: print(f"  {p}")

if __name__ == "__main__":
    import sys
    # Read status from stdin
    analyze_git_status(sys.stdin.read())
