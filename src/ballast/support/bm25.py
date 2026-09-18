"""BM25 lexical retrieval in ~90 lines of standard library.

Deliberately not an embedding index: the target providers (DeepSeek, and most
self-hosted OpenAI-compatible gateways) expose no embedding endpoint, so a
runtime that assumes one cannot claim portability. Lexical retrieval also has a
property that matters more here than recall — it is deterministic, so a
retrieval-dependent eval is reproducible run to run.

Chinese is indexed as unigrams + bigrams, which avoids shipping a segmenter
while keeping phrase-level discrimination.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

_CJK_RANGE = "一-鿿㐀-䶿"
_TOKEN_RE = re.compile(rf"[a-z0-9_]+|[{_CJK_RANGE}]")


def tokenize(text: str) -> list[str]:
    """Lowercase word/unigram tokens; CJK runs additionally contribute bigrams."""
    units = _TOKEN_RE.findall(text.lower())
    tokens: list[str] = []
    run: list[str] = []

    def flush() -> None:
        for i, ch in enumerate(run):
            tokens.append(ch)
            if i + 1 < len(run):
                tokens.append(ch + run[i + 1])
        run.clear()

    for unit in units:
        if len(unit) == 1 and is_cjk_char(unit):
            run.append(unit)
            continue
        if run:
            flush()
        tokens.append(unit)
    if run:
        flush()
    return tokens


def is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF


@dataclass(slots=True)
class Doc:
    id: str
    title: str
    text: str
    meta: dict | None = None

    @property
    def blob(self) -> str:
        return f"{self.title}\n{self.text}"


class BM25Index:
    """Okapi BM25 over an in-memory corpus. Rebuild-free: `add` invalidates caches."""

    def __init__(self, docs: list[Doc] | None = None, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[Doc] = []
        self._tokens: list[list[str]] = []
        self._df: dict[str, int] = {}
        self._avgdl = 0.0
        if docs:
            self.add_many(docs)

    def add_many(self, docs: list[Doc]) -> None:
        for doc in docs:
            self._add(doc)

    def _add(self, doc: Doc) -> None:
        tokens = tokenize(doc.blob)
        self.docs.append(doc)
        self._tokens.append(tokens)
        for term in set(tokens):
            self._df[term] = self._df.get(term, 0) + 1
        total = sum(len(t) for t in self._tokens)
        self._avgdl = total / len(self._tokens) if self._tokens else 0.0

    def __len__(self) -> int:
        return len(self.docs)

    def search(self, query: str, top_k: int = 4, *, min_score: float = 0.0) -> list[tuple[Doc, float]]:
        if not self.docs:
            return []
        n = len(self.docs)
        query_terms = set(tokenize(query))
        if not query_terms:
            return []
        scores = [0.0] * n
        for term in query_terms:
            df = self._df.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, tokens in enumerate(self._tokens):
                tf = tokens.count(term)
                if not tf:
                    continue
                dl = len(tokens)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1.0))
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(zip(self.docs, scores), key=lambda kv: kv[1], reverse=True)
        best = max(scores) if scores else 0.0
        out = [(doc, s / best if best else 0.0) for doc, s in ranked]
        return [(doc, score) for doc, score in out if score >= min_score][:top_k]


def load_markdown_docs(directory: Path | str) -> list[Doc]:
    """Split markdown into `##`-section chunks so retrieval returns policy paragraphs, not files."""
    docs: list[Doc] = []
    for path in sorted(Path(directory).glob("*.md")):
        title = path.stem
        buffer: list[str] = []
        preamble: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if buffer:
                    docs.append(Doc(id=f"{path.stem}::{title}", title=title, text="\n".join(buffer).strip()))
                    buffer = []
                title = line[3:].strip()
            elif line.startswith("# "):
                preamble.append(line[2:].strip())
            else:
                buffer.append(line)
        if buffer:
            docs.append(Doc(id=f"{path.stem}::{title}", title=title, text="\n".join(buffer).strip()))
        if preamble and not docs:
            docs.append(Doc(id=path.stem, title=path.stem, text="\n".join(preamble)))
    return docs
