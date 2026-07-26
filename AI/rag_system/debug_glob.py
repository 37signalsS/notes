import os
import glob
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "../../"))
print(f"SCRIPT_DIR: {SCRIPT_DIR}")
print(f"NOTES_DIR: {NOTES_DIR}")
pattern = os.path.join(NOTES_DIR, "**/*.md")
print(f"Pattern: {pattern}")
all_files = glob.glob(pattern, recursive=True)
print(f"Total files found: {len(all_files)}")
exclude_dirs = [".obsidian", ".git", "AI/rag_system"]
files = [f for f in all_files if not any(x in f for x in exclude_dirs)]
print(f"Filtered files: {len(files)}")
if len(files) > 0:
    print(f"Sample file: {files[0]}")
