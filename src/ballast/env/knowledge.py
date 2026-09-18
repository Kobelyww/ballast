"""SOP knowledge base: BM25 over policy sections, with a citation-shaped id.

Chunk ids look like `refund_policy::7天无理由窗口`, so a summary that cites the chunk
id is *checkable* — the grader can demand that the policy basis named in a
close-out actually exists in the corpus. That turns "did the agent reason from
policy" from an LLM-judge opinion into a string lookup.
"""

from __future__ import annotations

from pathlib import Path

from ..support.bm25 import BM25Index, Doc, load_markdown_docs

SOP_DIR = Path(__file__).parent / "sop"


class KnowledgeBase:
    def __init__(self, docs: list[Doc]) -> None:
        self.index = BM25Index(docs)
        self.by_id = {doc.id: doc for doc in docs}

    @classmethod
    def from_dir(cls, directory: Path | str | None = None) -> "KnowledgeBase":
        return cls(load_markdown_docs(Path(directory or SOP_DIR)))

    def search(self, query: str, top_k: int = 3, *, min_score: float = 0.05) -> list[tuple[Doc, float]]:
        return self.index.search(query, top_k=top_k, min_score=min_score)

    def render(self, query: str, top_k: int = 3) -> str:
        return "\n\n".join(
            f"[{doc.id} | score={score:.2f}]\n{doc.text}" for doc, score in self.search(query, top_k=top_k)
        )

    def section_ids(self) -> set[str]:
        return set(self.by_id)

    def briefing(self, max_tokens: int = 900) -> str:
        from ..support.text import clip_to_tokens

        return clip_to_tokens(
            "\n\n".join(f"[{doc.id}]\n{doc.text}" for doc in self.index.docs),
            max_tokens,
        )
