"""
retriever.py
============
Loads the local support corpus from data/{hackerrank,claude,visa}/
and builds a per-company TF-IDF index for grounded retrieval.

Public API
----------
    r = Retriever()
    chunks = r.retrieve(query="how do I reset password", company="hackerrank")
    # → list of {"source": str, "text": str, "score": float}
"""

import math
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR      = REPO_ROOT / "data"
COMPANIES     = ["hackerrank", "claude", "visa"]
CHUNK_WORDS   = 350    # words per chunk
CHUNK_OVERLAP = 60     # word overlap between consecutive chunks
DEFAULT_TOP_K = 6      # chunks returned per query


# ── text utilities ────────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", " ", raw)        # strip HTML tags
    raw = re.sub(r"https?://\S+", " ", raw)    # remove bare URLs (keep surrounding text)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _sliding_chunks(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    step   = max(1, CHUNK_WORDS - CHUNK_OVERLAP)
    result = []
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + CHUNK_WORDS])
        if len(chunk) > 80:
            result.append(chunk)
    return result


# ── corpus loader ─────────────────────────────────────────────────────────────

def _load_corpus() -> dict[str, list[tuple[str, str]]]:
    """
    Returns corpus[company] = [(relative_path, chunk_text), ...]
    """
    corpus: dict[str, list[tuple[str, str]]] = {c: [] for c in COMPANIES}

    for company in COMPANIES:
        d = DATA_DIR / company
        if not d.exists():
            print(f"  [WARN] data/{company}/ missing — no corpus for {company}")
            continue

        file_count = 0
        for fpath in sorted(d.rglob("*")):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in {".txt", ".md", ".html", ".htm", ".json"}:
                continue
            try:
                raw  = fpath.read_text(encoding="utf-8", errors="ignore")
                text = _clean(raw)
                rel  = str(fpath.relative_to(REPO_ROOT))
                for chunk in _sliding_chunks(text):
                    corpus[company].append((rel, chunk))
                file_count += 1
            except Exception as e:
                print(f"  [WARN] {fpath.name}: {e}")

        total_chunks = len(corpus[company])
        print(f"  {company:12s} {file_count:4d} files  →  {total_chunks:5d} chunks")

    return corpus


# ── TF-IDF index builder ──────────────────────────────────────────────────────

def _build_index(chunks: list[tuple[str, str]]) -> tuple[list[dict], dict]:
    """
    Returns (vectors, idf) where:
        vectors[i] = {term: tfidf}  for chunk i
        idf        = {term: idf_value}
    """
    docs = [_tokenize(text) for _, text in chunks]
    N    = len(docs)
    if N == 0:
        return [], {}

    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for term in set(doc):
            df[term] += 1

    # smooth IDF  +1 to numerator avoids log(1)=0 for common terms
    idf = {t: math.log((N + 1) / (cnt + 1)) + 1.0 for t, cnt in df.items()}

    vectors = []
    for doc in docs:
        if not doc:
            vectors.append({})
            continue
        tf: dict[str, float] = defaultdict(float)
        for term in doc:
            tf[term] += 1.0
        vec = {t: (cnt / len(doc)) * idf.get(t, 1.0) for t, cnt in tf.items()}
        vectors.append(vec)

    return vectors, idf


def _cosine(v1: dict, v2: dict) -> float:
    dot = sum(v1.get(t, 0.0) * s for t, s in v2.items())
    n1  = math.sqrt(sum(x * x for x in v1.values()))
    n2  = math.sqrt(sum(x * x for x in v2.values()))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


# ── public Retriever class ────────────────────────────────────────────────────

class Retriever:
    """
    Load once at startup; call retrieve() for every ticket.

    Design choice: per-company TF-IDF indices (not one shared index).
    This prevents Visa billing content from polluting HackerRank answers
    and vice-versa.  When company is unknown we search all three and merge.
    """

    def __init__(self):
        print("Loading corpus...")
        self._corpus  = _load_corpus()
        print("Building TF-IDF indices...")
        self._indices: dict[str, tuple[list, dict]] = {}
        for company in COMPANIES:
            vecs, idf = _build_index(self._corpus[company])
            self._indices[company] = (vecs, idf)
            if vecs:
                print(f"  {company:12s} index ready  ({len(vecs)} vectors)")
            else:
                print(f"  {company:12s} index EMPTY — corpus missing")

    # ── public ───────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query:   str,
        company: str,
        top_k:   int = DEFAULT_TOP_K,
    ) -> list[dict]:
        """
        Return top_k relevant corpus chunks for the given query.

        If company is unknown/missing, searches all three corpora and
        returns the globally best chunks.
        """
        company = company.lower().strip()

        if company in COMPANIES and self._corpus[company]:
            return self._search_one(query, company, top_k)

        # Unknown company: search all, merge, dedup by score
        all_results: list[dict] = []
        for c in COMPANIES:
            all_results.extend(self._search_one(query, c, top_k=3))
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

    def has_corpus(self, company: str) -> bool:
        return bool(self._corpus.get(company.lower(), []))

    # ── internal ─────────────────────────────────────────────────────────────

    def _search_one(self, query: str, company: str, top_k: int) -> list[dict]:
        vecs, idf = self._indices.get(company, ([], {}))
        chunks    = self._corpus.get(company, [])
        if not vecs:
            return []

        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        q_vec: dict[str, float] = defaultdict(float)
        for term in q_tokens:
            q_vec[term] += idf.get(term, math.log(2)) / len(q_tokens)

        scored = sorted(
            enumerate(vecs),
            key=lambda iv: _cosine(iv[1], q_vec),
            reverse=True,
        )

        results = []
        for idx, vec in scored[:top_k]:
            score = _cosine(vec, q_vec)
            if score <= 0:
                break
            src, text = chunks[idx]
            results.append({"source": src, "text": text, "score": round(score, 5)})
        return results
