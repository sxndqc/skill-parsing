#!/usr/bin/env python3
"""
umr-entity code tool / mock-engine implementation.

Layer 3 (leaves): noun-phrase internals. Named entity -> typed node + name;
pronoun -> person/thing + ref features; common noun -> head + modifier hints.
"""
from __future__ import annotations
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from tools import nlp_tools as nlp   # noqa: E402
from tools import heuristics         # noqa: E402

_COUNTRY_WIKI = {"Russia": "Russia", "America": "United_States",
                 "Germany": "Germany", "China": "China"}


def run(span: str, context: dict | None = None) -> dict:
    span = span.strip()

    # 1. pronoun
    pron = nlp.pronoun(span)
    if pron:
        attrs = [[":ref-person", pron["ref_person"]]]
        if pron.get("ref_number"):
            attrs.append([":ref-number", pron["ref_number"]])
        frag = {"concept": pron["concept"], "node_type": "entity",
                "attributes": attrs, "children": [],
                "trace": f"pronoun '{span}' -> {pron['concept']} "
                         f"({pron['ref_person']})"}
        return _apply_heuristics(frag, span)

    # 2. named entity
    ne = nlp.named_entity(span)
    if ne:
        name_text = " ".join(ne["name_tokens"])
        wiki = _COUNTRY_WIKI.get(name_text, "-")
        frag = {"concept": ne["ne_type"], "node_type": "entity",
                "attributes": [], "children": _ne_children(name_text, wiki),
                "trace": f"named entity '{name_text}' -> {ne['ne_type']} with name node"}
        return _apply_heuristics(frag, span)

    # 3. common noun
    parts = nlp.noun_phrase_parts(span)
    attrs = []
    if parts.get("ref_number"):
        attrs.append([":ref-number", parts["ref_number"]])
    children = []
    for m in parts["mods"]:
        children.append({"relation": None, "relation_hint": m["relation_hint"],
                         "text": m["text"], "expand_as": m["category"]})
    frag = {"concept": parts["head"], "node_type": "entity",
            "attributes": attrs, "children": children,
            "trace": f"common noun '{parts['head']}' + {len(children)} modifier(s)"}
    return _apply_heuristics(frag, span)


def _ne_children(name_text: str, wiki: str) -> list:
    return [
        {"relation": ":name", "relation_hint": None,
         "text": name_text, "expand_as": "name"},
        {"relation": ":wiki", "relation_hint": None,
         "text": wiki, "expand_as": "string"},
    ]


def _apply_heuristics(frag: dict, span: str) -> dict:
    """Override the computed fragment with any matching learned correction."""
    rule = heuristics.match("umr-entity", {"span": span})
    if not rule:
        return frag
    s = rule.get("set", {})
    note = rule.get("note") or "manual correction"
    if "ne_type" in s:                       # force a (possibly re-typed) named entity
        name_text = s.get("name", span)
        frag["concept"] = s["ne_type"]
        frag["children"] = _ne_children(name_text, s.get("wiki", "-"))
    elif "head" in s:                        # override the common-noun head
        frag["concept"] = s["head"]
    if "concept" in s:                       # raw concept override (rare)
        frag["concept"] = s["concept"]
    for attr in (":ref-number", ":ref-person"):
        key = attr[1:].replace("-", "_")
        if key in s:
            frag["attributes"] = heuristics.replace_attr(frag["attributes"], attr, s[key])
    frag["trace"] = f"[heuristic] {note} -> {frag['concept']}"
    return frag


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "Russian President Vladimir Putin"
    print(json.dumps(run(text), indent=2, ensure_ascii=False))
