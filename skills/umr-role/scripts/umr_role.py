#!/usr/bin/env python3
"""
umr-role code tool / mock-engine implementation.

Layer 2: decide the single edge label between a head and one child. Validates
against the UMR inventory and applies a handful of mechanical disambiguation
rules; everything else defers to the bracketing layer's hint.
"""
from __future__ import annotations
import os, sys, json, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from tools import nlp_tools as nlp          # noqa: E402
from tools import umr_inventory as inv      # noqa: E402
from tools import heuristics                # noqa: E402

_TIME_WORDS = nlp._TIME_WORDS


def run(span: str, context: dict | None = None) -> dict:
    ctx = context or {}
    head = ctx.get("head_concept", "")
    child = (ctx.get("child_text") or span or "").strip()
    category = ctx.get("category", "entity")
    hint = ctx.get("relation_hint")

    rel, why = _decide(head, child, category, hint)

    # Learned corrections override the default judgement.
    rule = heuristics.match("umr-role", {
        "head_concept": head, "head_text": ctx.get("head_text", ""),
        "child_text": child, "category": category, "relation_hint": hint or "",
    })
    if rule and "relation" in rule.get("set", {}):
        rel = rule["set"]["relation"]
        why = f"[heuristic] {rule.get('note') or 'manual correction'} -> {rel}"

    # Final guard: never emit a label outside the inventory.
    if not inv.is_relation(rel):
        rel, why = (":mod", f"{rel!r} not in inventory -> fallback :mod") \
            if category in {"leaf", "entity"} else (":other", f"{rel!r} invalid -> :other")
    return {"relation": rel, "trace": why}


def _decide(head: str, child: str, category: str, hint: str | None):
    low = child.lower()
    toks = nlp.tokenize(child)

    # 1. numerals -> quantity
    if category == "value" or (toks and all(t.pos in {"NUM", "PUNCT"} for t in toks)):
        return ":quant", f"numeral '{child}' -> :quant"

    # 2. single adjective / classifier modifier -> :mod
    if category == "leaf":
        if hint == ":manner" and low.endswith("ly"):
            return ":manner", f"adverb '{child}' -> :manner"
        if hint in {":temporal"} or low in _TIME_WORDS:
            return ":temporal", f"time word '{child}' -> :temporal"
        return ":mod", f"modifier word '{child}' -> :mod"

    # 3. place vs temporal for prepositional / bare NPs
    if hint == ":place" and any(t.lower in _TIME_WORDS for t in toks):
        return ":temporal", f"'{child}' is time-like -> :temporal (not :place)"
    if hint == ":temporal" and not any(t.lower in _TIME_WORDS for t in toks):
        # keep temporal only if the hint was confident; otherwise leave as place
        return ":temporal", f"kept :temporal hint for '{child}'"

    # 4. of-phrase possession vs part
    if hint == ":poss":
        if _looks_partitive(head, child):
            return ":part-of", f"'{child}' reads as an integral part -> :part-of"
        return ":poss", f"of/possessive '{child}' -> :poss"

    # 5. trust a valid hint
    if hint and inv.is_relation(hint):
        return hint, f"accepted bracketing hint {hint} for '{child}'"

    # 6. last resort by category
    if category == "clause":
        return ":ARG1", f"clausal complement '{child}' -> :ARG1"
    return ":mod", f"no hint for '{child}' -> :mod"


_PART_NOUNS = {"leg", "arm", "roof", "wall", "edge", "side", "top", "bottom",
               "part", "piece", "slice", "half", "corner", "surface"}
def _looks_partitive(head: str, child: str) -> bool:
    h = head.split("-")[0]
    return h in _PART_NOUNS


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", default="")
    ap.add_argument("--child", default="")
    ap.add_argument("--category", default="entity")
    ap.add_argument("--hint", default=None)
    a = ap.parse_args()
    ctx = {"head_concept": a.head, "child_text": a.child,
           "category": a.category, "relation_hint": a.hint}
    print(json.dumps(run(a.child, ctx), indent=2, ensure_ascii=False))
