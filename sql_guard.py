"""
SQL guard: the first of two safety layers between the LLM and your database.

Layer 1 (this file): reject anything that is not a single, plain read query.
Layer 2 (the database): the planner_ro role can only SELECT, is read-only by
default, and kills any query that runs longer than 5 seconds.

Either layer alone would be a weak design. Together, a model that is
confused, jailbroken or simply wrong still cannot change or leak data.
"""

import re

MAX_SQL_LENGTH = 4000

# Whole-word keywords that have no place in a read-only analytical query.
FORBIDDEN_WORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "grant", "revoke",
    "truncate", "copy", "call", "do", "execute", "vacuum", "analyze", "reindex",
    "listen", "notify", "set", "reset", "lock", "comment", "refresh", "into",
}

# Functions and schemas that can read files, sleep, or expose system data.
FORBIDDEN_PATTERNS = [
    r"\bpg_\w+",
    r"\binformation_schema\b",
    r"\bdblink\w*",
    r"\blo_\w+",
    r"\bset_config\b",
    r"\bcurrent_setting\b",
]


class UnsafeSQL(ValueError):
    """Raised when a query is rejected. The message is safe to show the model."""


def _strip_literals(sql: str) -> str:
    """Replace string literals with '' so keywords inside them are ignored."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validate_sql(sql: str) -> str:
    """Return the cleaned query, or raise UnsafeSQL."""
    if not sql or not sql.strip():
        raise UnsafeSQL("Empty query.")
    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeSQL("Query is too long.")

    cleaned = sql.strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()

    probe = _strip_literals(cleaned).lower()

    if "--" in probe or "/*" in probe or "*/" in probe:
        raise UnsafeSQL("Comments are not allowed.")
    if ";" in probe:
        raise UnsafeSQL("Only one statement is allowed.")

    first_word = re.match(r"\s*([a-z_]+)", probe)
    if not first_word or first_word.group(1) not in ("select", "with"):
        raise UnsafeSQL("Only SELECT queries are allowed.")

    for word in re.findall(r"[a-z_]+", probe):
        if word in FORBIDDEN_WORDS:
            raise UnsafeSQL(f"The keyword '{word}' is not allowed.")

    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, probe):
            raise UnsafeSQL("That function or schema is not allowed.")

    return cleaned
