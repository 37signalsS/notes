import sys
import json
import os
import torch
import rag_utils
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(SCRIPT_DIR, "chroma_db")
COLLECTION_NAME = "notes_rag_v2"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def query(question, k=15):
    device = get_device()
    embeddings = HuggingFaceEmbeddings(model_name=MODEL_NAME, model_kwargs={"device": device})
    
    vectorstore = Chroma(
        persist_directory=DB_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME
    )
    
    # Используем MMR (Maximal Marginal Relevance) для разнообразия результатов
    # Это помогает не получать 15 одинаковых кусков из одного файла
    results = vectorstore.max_marginal_relevance_search(question, k=k, fetch_k=50)
    
    output = []
    for res in results:
        source = res.metadata.get("source", "")
        if rag_utils.is_excluded(source):
            continue
        output.append({
            "content": res.page_content,
            "metadata": res.metadata
        })
    
    return output

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python query.py 'your question'")
        sys.exit(1)
    
    question = sys.argv[1]
    k = 15
    if len(sys.argv) > 2:
        k = int(sys.argv[2])
        
    results = query(question, k)
    print(json.dumps(results, indent=2, ensure_ascii=False))
