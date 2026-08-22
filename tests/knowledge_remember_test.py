"""Regression test for the knowledge_remember LLM tool path.

The voice-intent path for "remember this permanently: X" is regex-driven
(src/knowledge.py::_REMEMBER_INTENT_RE) and requires the permanence adverb
to disambiguate from episodic memory. The LLM tool path here closes that
gap: Claude can write the corpus on any natural "remember this for me"
phrasing without the adverb. This test verifies:

  - the tool schema is well-formed and exposes a `fact` field
  - an empty fact returns a voice-friendly error (no file written)
  - a real fact writes a dated .md to the configured corpus dir
  - the tool is registered + correctly NOT in _RESTRICTED_DENY (phone-
    allowed, consistent with set_reminder)

Isolation uses BOTH JARVIS_KNOWLEDGE_DIR (corpus) and JARVIS_KNOWLEDGE_DB
(derived FTS5 index) against a temp dir.

  - the index override actually isolates, and the REAL index is untouched

WHY BOTH (post-mortem, 2026-08-21): this test previously overrode only
JARVIS_KNOWLEDGE_DIR and looked isolated. It was not. `knowledge_remember`
ends by calling `reindex()`, and `_db_path()` honored no override, so every
run of this test rebuilt the USER'S PRODUCTION index from a temp corpus
holding one fixture -- silently destroying the real one. It was found only
because the live index contained exactly one entry named after this file's
test pets. Overriding the corpus without the index is a half-isolation that
looks complete. Test 5 below is the regression gate for it.

    python tests/knowledge_remember_test.py     # exit 0 = pass
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_passed = 0
_failed = 0


def check(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


class isolated_knowledge:
    """Point BOTH the corpus and the derived index at a temp dir.

    Overriding only the corpus is the bug this class exists to prevent --
    see the module docstring. Restores prior values on exit rather than
    deleting, so a caller's own settings survive."""

    def __init__(self, tmp: str) -> None:
        self._tmp = tmp
        self._prior: dict[str, str | None] = {}

    def __enter__(self) -> str:
        for k, v in (("JARVIS_KNOWLEDGE_DIR", self._tmp),
                     ("JARVIS_KNOWLEDGE_DB", str(Path(self._tmp) / "index.db"))):
            self._prior[k] = os.environ.get(k)
            os.environ[k] = v
        return self._tmp

    def __exit__(self, *exc: object) -> None:
        for k, prior in self._prior.items():
            if prior is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prior


# --- Test 1: schema is well-formed ----------------------------------------
from src.knowledge import (  # noqa: E402
    KNOWLEDGE_REMEMBER_TOOL, execute_knowledge_remember,
)
schema = KNOWLEDGE_REMEMBER_TOOL
check("KNOWLEDGE_REMEMBER_TOOL: name=knowledge_remember + has description",
      schema.get("name") == "knowledge_remember" and "description" in schema)
props = schema.get("input_schema", {}).get("properties", {})
check("schema exposes a `fact` field (string), required",
      "fact" in props
      and props["fact"].get("type") == "string"
      and "fact" in schema["input_schema"].get("required", []))


# --- Test 2: empty fact returns a voice-friendly error, writes nothing ----
with tempfile.TemporaryDirectory() as tmp, isolated_knowledge(tmp):
    out = execute_knowledge_remember({"fact": ""})
    check("empty fact -> voice-friendly error",
          "nothing to remember" in out.lower())
    # No .md files should exist.
    md_files = list(Path(tmp).glob("*.md"))
    check("empty fact -> no .md file written", len(md_files) == 0)


# --- Test 3: a real fact writes a dated .md file --------------------------
with tempfile.TemporaryDirectory() as tmp, isolated_knowledge(tmp):
    out = execute_knowledge_remember(
        {"fact": "My four pets are Aria, Basil, Cosmo, and Delta."}
    )
    check("real fact -> voice-friendly confirmation",
          ("noted" in out.lower() or "saved" in out.lower()))
    md_files = list(Path(tmp).glob("*.md"))
    check("real fact -> exactly one .md file written",
          len(md_files) == 1)
    if md_files:
        body = md_files[0].read_text(encoding="utf-8")
        check("file body contains the pet names",
              "Aria" in body and "Delta" in body)


# --- Test 4: registered in _CLIENT_TOOLS + NOT in _RESTRICTED_DENY --------
from src.llm import _CLIENT_TOOLS, _RESTRICTED_DENY  # noqa: E402
check("knowledge_remember registered in _CLIENT_TOOLS",
      "knowledge_remember" in _CLIENT_TOOLS)
check("knowledge_remember NOT in _RESTRICTED_DENY (phone may write)",
      "knowledge_remember" not in _RESTRICTED_DENY)


# --- Test 5: the index override isolates; the REAL index is untouched -----
# Regression gate for the 2026-08-21 leak. A bug a test would have caught
# earns a test; this is that test.
from src.knowledge import _db_path            # noqa: E402
from src.memory import default_base_dir       # noqa: E402


def _fingerprint(p: Path):
    """(mtime_ns, size) or None. Cheap, and enough to prove 'untouched'."""
    return (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None


_real_db = default_base_dir() / "knowledge.db"
_before = _fingerprint(_real_db)

with tempfile.TemporaryDirectory() as tmp, isolated_knowledge(tmp):
    check("JARVIS_KNOWLEDGE_DB overrides the index path",
          _db_path() == Path(tmp) / "index.db")
    execute_knowledge_remember({"fact": "Isolation probe fact for the index."})
    check("reindex wrote to the OVERRIDE index, not the default",
          (Path(tmp) / "index.db").exists())

check("the REAL knowledge.db was NOT touched by this test",
      _fingerprint(_real_db) == _before)


# --- Test 6: restatements merge; DISTINCT facts must not (2026-08-21) -----
# The duplicate bug: one fact (the four cats) had been stored TEN times,
# because the filename was a slug of the fact TEXT. Reword it, get a new file.
#
# Test BOTH directions deliberately. A missed merge costs a redundant file; a
# WRONG merge silently destroys a distinct fact, which is far worse — so the
# false-positive case below matters more than the true-positive one.
with tempfile.TemporaryDirectory() as tmp, isolated_knowledge(tmp):
    execute_knowledge_remember(
        {"fact": "My four cats are Constantine, Lucifer, Ares, and Osiris."}
    )
    check("dedup: first fact -> one file",
          len(list(Path(tmp).glob("*.md"))) == 1)

    # Reworded AND enriched — the exact shape that produced the duplicates.
    execute_knowledge_remember({"fact": (
        "The user's four cats are: Constantine, a smaller orange cat; "
        "Lucifer, a bigger gray cat; Ares, a bigger orange cat; and "
        "Osiris, a female tuxedo cat."
    )})
    files = list(Path(tmp).glob("*.md"))
    check("dedup: reworded restatement -> still ONE file, not two",
          len(files) == 1)
    if files:
        body = files[0].read_text(encoding="utf-8")
        check("dedup: merge KEPT both wordings (nothing discarded)",
              "smaller orange" in body and "My four cats" in body)

    # Same subject, genuinely different fact -> must NOT be swallowed.
    execute_knowledge_remember({"fact": "Osiris likes tuna."})
    check("dedup: distinct fact about the same subject -> a NEW file",
          len(list(Path(tmp).glob("*.md"))) == 2)


# --- Test 7: a fully-covered restatement writes nothing at all ------------
with tempfile.TemporaryDirectory() as tmp, isolated_knowledge(tmp):
    execute_knowledge_remember(
        {"fact": "The user's four cats are Constantine, Lucifer, Ares, and Osiris."}
    )
    out = execute_knowledge_remember(
        {"fact": "My four cats are Constantine, Lucifer, Ares, and Osiris."}
    )
    check("dedup: fully-covered restatement -> honest 'already had it' reply",
          "already had" in out.lower())
    check("dedup: fully-covered restatement -> no second file",
          len(list(Path(tmp).glob("*.md"))) == 1)


# --- summary --------------------------------------------------------------
print(f"\n{_passed} passed, {_failed} failed")
sys.exit(0 if _failed == 0 else 1)
