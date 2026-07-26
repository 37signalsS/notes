import os
import glob
import re
import logging
import torch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rag")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "../../"))

ENGINES = {
    "mpnet": {
        "dir": os.path.join(SCRIPT_DIR, "chroma_db"),
        "collection": "notes_rag_v2",
        "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "chunk_size": 1200,
        "chunk_overlap": 200,
        "label": "MPNet"
    },
    "bge": {
        "dir": os.path.join(SCRIPT_DIR, "chroma_bge"),
        "collection": "notes_bge",
        "model": "BAAI/bge-m3",
        "chunk_size": 1500,
        "chunk_overlap": 250,
        "label": "BGE-M3"
    }
}

EXCLUDED_DIRS = ["Vagrant", ".git", ".obsidian", "venv", "rag_system"]
EXCLUDED_FILES = ["GEMINI.md", "MEMORY.md", ".DS_Store"]
EXCLUDED_EXTENSIONS = [".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".py"]

RERANKER_MODEL = "cross-encoder/multilingual-MiniLM-L-12-v2"

BGE_QUERY_PREFIX = "Represent this query for searching relevant passages: "

_STEMMER = None

def _get_stemmer():
    global _STEMMER
    if _STEMMER is None:
        try:
            from pymorphy3 import MorphAnalyzer
            _STEMMER = MorphAnalyzer()
        except ImportError:
            _STEMMER = False
    return _STEMMER

def normalize_word(word):
    stemmer = _get_stemmer()
    if stemmer:
        return stemmer.parse(word)[0].normal_form
    return word.lower()

def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

def is_excluded(source_path):
    if not source_path:
        return False
    _, ext = os.path.splitext(source_path)
    if ext.lower() in EXCLUDED_EXTENSIONS:
        return True
    filename = os.path.basename(source_path)
    if filename in EXCLUDED_FILES:
        return True
    if filename.startswith("."):
        return True
    path_parts = source_path.split(os.sep)
    if any(d in path_parts for d in EXCLUDED_DIRS):
        return True
    return False

def get_files():
    all_files = glob.glob(os.path.join(NOTES_DIR, "**/*.md"), recursive=True)
    result = []
    for f in all_files:
        rel = os.path.relpath(f, NOTES_DIR)
        if not is_excluded(rel) and not is_excluded(f):
            result.append((f, rel))
    return result

def get_embeddings(model_name, device=None):
    from langchain_huggingface import HuggingFaceEmbeddings
    if device is None:
        device = get_device()
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        return HuggingFaceEmbeddings(model_name=model_name, model_kwargs={"device": device})
    except Exception:
        os.environ.pop("HF_HUB_OFFLINE", None)
        return HuggingFaceEmbeddings(model_name=model_name, model_kwargs={"device": device})

def keyword_overlap(query: str, text: str) -> float:
    query_tokens = {normalize_word(w) for w in re.findall(r'\w+', query)}
    text_tokens = {normalize_word(w) for w in re.findall(r'\w+', text)}
    if not query_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)
