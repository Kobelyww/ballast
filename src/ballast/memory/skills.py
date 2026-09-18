"""Procedural memory: a skill library the agent writes, audits and retires.

Cards are plain text retrieved lexically, so this works on a text-only API with no
embedding endpoint. Every card carries usage statistics, and — the part most skill
libraries skip — a `status` that starts at `candidate`. A candidate is never injected
into a live prompt; it becomes `active` only by winning the holdout gate in
`ballast.memory.promotion`. Growth is therefore bounded by evidence, not by enthusiasm.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ..support.bm25 import BM25Index, Doc

SkillStatus = Literal["candidate", "active", "retired"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills(
  id TEXT PRIMARY KEY, name TEXT, kind TEXT, when_to_use TEXT, procedure TEXT,
  tools TEXT, pitfalls TEXT, keywords TEXT, status TEXT, version INTEGER,
  created_at REAL, last_used_at REAL, use_count INTEGER, success_count INTEGER,
  source_run TEXT, family TEXT, evidence TEXT
);
"""

SIMILARITY_MERGE = 0.6


@dataclass(slots=True)
class Skill:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = ""
    kind: str = "procedure"  # procedure | caution
    when_to_use: str = ""
    procedure: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)
    keywords: str = ""
    status: SkillStatus = "candidate"
    version: int = 1
    created_at: float = field(default_factory=time.time)
    last_used_at: float = 0.0
    use_count: int = 0
    success_count: int = 0
    source_run: str = ""
    family: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.success_count / self.use_count if self.use_count else 0.0

    def retrieval_text(self) -> str:
        return " ".join([self.name, self.when_to_use, self.keywords, " ".join(self.procedure), " ".join(self.pitfalls)])

    def render(self) -> str:
        lines = [f"### {self.name}"]
        if self.kind == "caution":
            lines.append("**CAUTION — learned from a past failure**")
        lines.append(f"Use when: {self.when_to_use}")
        if self.procedure:
            lines.append("Steps:")
            lines.extend(f"  {i + 1}. {step}" for i, step in enumerate(self.procedure))
        if self.pitfalls:
            lines.append("Avoid: " + "; ".join(self.pitfalls))
        if self.tools:
            lines.append("Tools: " + ", ".join(self.tools))
        return "\n".join(lines)


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^0-9a-z一-鿿]+", text.lower()) if len(t) > 1}


def jaccard(a: str, b: str) -> float:
    sa, sb = _tokens(a), _tokens(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


class SkillLibrary:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._index: BM25Index | None = None

    # ------------------------------------------------------------------- crud
    def add(self, skill: Skill) -> Skill:
        row = asdict(skill)
        for key in ("procedure", "tools", "pitfalls", "evidence"):
            row[key] = json.dumps(row[key], ensure_ascii=False)
        cols = ", ".join(row)
        self._conn.execute(f"INSERT OR REPLACE INTO skills ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        self._conn.commit()
        self._index = None
        return skill

    def get(self, skill_id: str) -> Skill | None:
        row = self._conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        return _from_row(row) if row else None

    def all(self, *, status: str | None = "active") -> list[Skill]:
        sql = "SELECT * FROM skills" + (" WHERE status=?" if status else "") + " ORDER BY created_at"
        rows = self._conn.execute(sql, (status,) if status else ()).fetchall()
        return [_from_row(r) for r in rows]

    def candidates(self) -> list[Skill]:
        return self.all(status="candidate")

    def count(self, *, status: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM skills" + (" WHERE status=?" if status else "")
        return int(self._conn.execute(sql, (status,) if status else ()).fetchone()[0])

    def promote(self, skill_id: str, *, evidence: dict) -> Skill:
        skill = self.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        skill.status = "active"
        skill.evidence = {**(skill.evidence or {}), **evidence}
        return self.add(skill)

    def reject(self, skill_id: str, *, evidence: dict) -> Skill:
        skill = self.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        skill.status = "retired"
        skill.evidence = {**(skill.evidence or {}), **evidence}
        return self.add(skill)

    # -------------------------------------------------------------- retrieval
    @property
    def index(self) -> BM25Index:
        if self._index is None:
            skills = self.all()
            self._index = BM25Index([Doc(id=s.id, title=s.name, text=s.retrieval_text()) for s in skills])
        return self._index

    def search(self, task_text: str, top_k: int = 3, *, blend: bool = True) -> list[tuple[Skill, float]]:
        by_id = {s.id: s for s in self.all()}
        hits = self.index.search(task_text, top_k=top_k * 3)
        scored: list[tuple[Skill, float]] = []
        now = time.time()
        for doc, lex in hits:
            skill = by_id.get(doc.id)
            if skill is None:
                continue
            score = lex
            if blend:
                freshness = 1.0 / (1.0 + (now - (skill.last_used_at or skill.created_at)) / 86_400)
                score = 0.72 * lex + 0.18 * skill.win_rate + 0.10 * freshness
            scored.append((skill, score))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k]

    def find_similar(self, skill: Skill) -> Skill | None:
        text = skill.retrieval_text()
        for existing in self.all(status=None):
            if existing.id != skill.id and jaccard(text, existing.retrieval_text()) >= SIMILARITY_MERGE:
                return existing
        return None

    # ---------------------------------------------------------------- scoring
    def record_use(self, skill_ids: list[str], *, success: bool | None = None) -> None:
        now = time.time()
        for skill_id in skill_ids:
            skill = self.get(skill_id)
            if skill is None:
                continue
            skill.use_count += 1
            skill.last_used_at = now
            if success:
                skill.success_count += 1
            self.add(skill)

    def prune(self, *, min_uses: int = 5, max_win_rate: float = 0.2) -> list[str]:
        """Retire cards that keep getting injected and keep correlating with failure."""
        retired = []
        for skill in self.all():
            if skill.use_count >= min_uses and skill.win_rate <= max_win_rate:
                skill.status = "retired"
                self.add(skill)
                retired.append(skill.id)
        return retired

    def close(self) -> None:
        self._conn.close()


def _from_row(row: sqlite3.Row) -> Skill:
    data = dict(row)
    for key in ("procedure", "tools", "pitfalls"):
        data[key] = json.loads(data.get(key) or "[]")
    data["evidence"] = json.loads(data.get("evidence") or "{}")
    return Skill(**data)
