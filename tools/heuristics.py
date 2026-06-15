"""
Learned-correction heuristics  --  the human-in-the-loop memory of the parser.

When a person looks at a parse and says "that edge is wrong, 'to her friend' is a
:recipient not a :goal", we don't want to lose that judgement. We record it as a
*heuristic*: a small, content-keyed rule that fires whenever the same situation
recurs. Heuristics accumulate in a plain, hand-editable file per skill:

    skills/<skill>/heuristics.jsonl

Each line is one rule:

    {"match": {"head_concept": "give-01", "child_text_regex": "friend"},
     "set":   {"relation": ":recipient"},
     "note":  "animate receiver, not spatial goal",
     "added": "2026-06-05"}

`match` is a set of conditions on the runtime context; ALL must hold. A key
ending in `_regex` is treated as a regular expression over the corresponding
field; any other key is a case-insensitive equality test. `set` is what to
override in that layer's decision. The rule with the most matching conditions
wins (most specific); ties go to the most recently added rule.

Both engines consult these:
  * the mock skill scripts call `match()` and apply the override directly;
  * the claude engine injects `format_for_prompt()` into the skill prompt so the
    model treats the corrections as authoritative.

Because the file is read fresh on every call, a correction you add by hand (or
via `correct.py`) takes effect on the very next parse -- no restart, no rebuild.
"""

from __future__ import annotations
import os
import re
import json
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _base() -> str:
    # overridable so tests can point at a scratch directory
    return os.environ.get("UMR_HEURISTICS_BASE", os.path.join(ROOT, "skills"))


def path_for(skill: str) -> str:
    return os.path.join(_base(), skill, "heuristics.jsonl")


def load(skill: str) -> list[dict]:
    """Read the rules for a skill (skips blank lines and # comments)."""
    path = path_for(skill)
    rules: list[dict] = []
    if not os.path.exists(path):
        return rules
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            try:
                rules.append(json.loads(s))
            except json.JSONDecodeError:
                # a malformed hand-edit shouldn't crash a parse; skip it loudly
                import sys
                sys.stderr.write(f"[heuristics:{skill}] skipping bad line: {s[:80]}\n")
    return rules


def _field_matches(cond_key: str, cond_val, context: dict) -> bool:
    if cond_key.endswith("_regex"):
        base = cond_key[:-6]
        target = str(context.get(base, "") or "")
        try:
            return re.search(cond_val, target, re.IGNORECASE) is not None
        except re.error:
            return False
    target = str(context.get(cond_key, "") or "").strip().lower()
    return target == str(cond_val).strip().lower()


def _rule_matches(rule: dict, context: dict) -> bool:
    conds = rule.get("match", {})
    if not conds:
        return False
    return all(_field_matches(k, v, context) for k, v in conds.items())


def match(skill: str, context: dict) -> dict | None:
    """Return the best-matching rule for this context, or None.

    'Best' = the most specific (largest number of satisfied conditions); ties are
    broken in favour of the rule that appears later in the file (most recent).
    """
    best = None
    best_score = -1
    for rule in load(skill):
        if _rule_matches(rule, context):
            score = len(rule.get("match", {}))
            if score >= best_score:        # >= so later duplicates override
                best, best_score = rule, score
    return best


def add(skill: str, match_cond: dict, set_action: dict, note: str = "") -> dict:
    """Append a new heuristic rule and return it."""
    rule = {
        "match": match_cond,
        "set": set_action,
        "note": note,
        "added": datetime.date.today().isoformat(),
    }
    path = path_for(skill)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new_file:
            fh.write(f"# Learned corrections for the {skill} layer. "
                     "One JSON rule per line; '#' lines are comments.\n")
        fh.write(json.dumps(rule, ensure_ascii=False) + "\n")
    return rule


def format_for_prompt(skill: str) -> str:
    """Render the rules as authoritative instructions for the claude engine."""
    rules = load(skill)
    if not rules:
        return ""
    lines = []
    for r in rules:
        conds = ", ".join(
            f"{k}{'~' if k.endswith('_regex') else '='}{v}"
            for k, v in r.get("match", {}).items())
        sets = ", ".join(f"{k}={v}" for k, v in r.get("set", {}).items())
        note = f"  ({r['note']})" if r.get("note") else ""
        lines.append(f"- WHEN {conds}  THEN {sets}{note}")
    return "\n".join(lines)


# -- small helpers the skill scripts share ---------------------------------
def replace_attr(attributes: list, attr: str, value: str) -> list:
    """Return attributes with `attr` set to `value` (replacing any existing)."""
    out = [pair for pair in attributes if pair[0] != attr]
    out.append([attr, value])
    return out
