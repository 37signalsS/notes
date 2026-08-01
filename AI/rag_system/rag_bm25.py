import math
import re
from functools import lru_cache
from typing import Any

from rag_config import BM25_K1, BM25_B

_GARBLED_ALPHANUM_RE = re.compile(r'[A-Za-z0-9+/=]')
_PUNCT_RE = re.compile(r'[^\w\s]')

try:
    import pymorphy3
    _morph_analyzer: Any = pymorphy3.MorphAnalyzer()
except ImportError:
    _morph_analyzer = None


@lru_cache(maxsize=8192)
def normalize_word(word: str) -> str:
    word = word.lower()
    if _morph_analyzer is not None:
        try:
            return _morph_analyzer.parse(word)[0].normal_form
        except Exception:
            pass
    return word


def keyword_overlap(query: str, text: str) -> float:
    q_words = set(normalize_word(w) for w in _PUNCT_RE.sub('', query).split() if w)
    t_words = set(normalize_word(w) for w in _PUNCT_RE.sub('', text).split() if w)
    if not q_words and not t_words:
        return 0.0
    if not q_words or not t_words:
        return 0.0
    return len(q_words.intersection(t_words)) / max(len(q_words), len(t_words))


def bm25_scores(query: str, texts: list[str], k1: float = BM25_K1, b: float = BM25_B) -> list[float]:
    tokenized_texts = [
        [normalize_word(w) for w in _PUNCT_RE.sub('', t).split() if w]
        for t in texts
    ]
    q_words = [normalize_word(w) for w in _PUNCT_RE.sub('', query).split() if w]
    if not q_words or not tokenized_texts:
        return [0.0] * len(texts)

    doc_len = [len(t) for t in tokenized_texts]
    avgdl = sum(doc_len) / len(doc_len) if doc_len else 1.0
    N = len(texts)

    df: dict[str, int] = {}
    for t in tokenized_texts:
        for w in set(t):
            df[w] = df.get(w, 0) + 1

    scores = []
    for i, t in enumerate(tokenized_texts):
        score = 0.0
        for w in q_words:
            if w in t:
                tf = t.count(w)
                idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len[i] / avgdl))
        scores.append(score)
    return scores


def is_garbled_chunk(content: str) -> bool:
    if not content:
        return False
    longest = 0
    current = 0
    for ch in content:
        if 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or '0' <= ch <= '9' or ch in '+/=':
            current += 1
            if current > longest:
                longest = current
        else:
            current = 0
    if longest > 55:
        return True
    if longest > 40 and longest / max(len(content), 1) > 0.15:
        return True
    return False
