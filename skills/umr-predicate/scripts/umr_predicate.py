#!/usr/bin/env python3
"""
umr-predicate code tool / mock-engine implementation.

Layer 1: find the head of a single clause, stamp aspect/modstr/mode/polarity,
and bracket the surrounding phrases (relations left for umr-role).
"""
from __future__ import annotations
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from tools import nlp_tools as nlp   # noqa: E402
from tools import heuristics         # noqa: E402

_STATIVE = {"be", "have", "know", "own", "love", "hate", "want", "need",
            "like", "remain", "stay", "seem", "belong", "contain", "consist"}


def run(span: str, context: dict | None = None) -> dict:
    extra_children = []
    work = span

    # Step 1: peel a subordinate clause off the main clause.
    sub = nlp.find_subordination(span)
    if sub:
        work = sub["main"]
        extra_children.append({
            "relation": sub["relation"], "relation_hint": None,
            "text": sub["subordinate"], "expand_as": "clause",
        })

    c = nlp.chunk_clause(work)

    # Degenerate case: no verb found -> treat the whole thing as an entity.
    if c["predicate"] is None:
        return {
            "concept": None, "node_type": "passthrough", "attributes": [],
            "children": [{"relation": None, "relation_hint": None,
                          "text": work, "expand_as": "entity"}],
            "trace": "no predicate found -> treat span as an entity",
        }

    children = []
    attrs = []
    neg = c["neg"]

    if c["is_copula"]:
        concept, subj_rel, comp_rel, aspect = _copula_head(c)
        if c["subject"]:
            children.append(_child(subj_rel, "entity", c["subject"]))
        for k, ch in enumerate(c["chunks"]):
            rel = comp_rel if k == 0 else None
            children.append(_child(rel, _cat(ch["category"]), ch["text"],
                                   hint=ch.get("relation_hint")))
        node_type = "event"
    else:
        lemma = c["predicate"]
        concept = f"{lemma}-01"
        aspect = _aspect(lemma, c)
        node_type = "event"
        if c["subject"]:
            children.append(_child(None, "entity", c["subject"], hint=":ARG0"))
        for ch in c["chunks"]:
            children.append(_child(None, _cat(ch["category"]), ch["text"],
                                   hint=ch.get("relation_hint")))

    children.extend(extra_children)

    attrs.append([":aspect", aspect])
    if neg:
        attrs.append([":modstr", "FullNeg"])
        attrs.append([":polarity", "-"])
    elif c["mode"] == "Imperative":
        attrs.append([":modstr", "PrtAff"])
    else:
        attrs.append([":modstr", "FullAff"])
    if c["mode"]:
        attrs.append([":mode", c["mode"]])

    frag = {
        "concept": concept,
        "node_type": node_type,
        "attributes": attrs,
        "children": children,
        "trace": f"head {concept}; {len(children)} phrase(s) bracketed; aspect={aspect}",
    }
    hctx = {
        "span": span,
        "verb": c["predicate"] or "",                 # the (possibly rough) lemma
        "verb_surface": c.get("predicate_surface", "") or "",  # the word as written
        "concept": concept,                           # the concept we're about to emit
    }
    return _apply_heuristics(frag, hctx)


def _apply_heuristics(frag: dict, hctx: dict) -> dict:
    """Override head concept / aspect / modstr from learned corrections."""
    rule = heuristics.match("umr-predicate", hctx)
    if not rule:
        return frag
    s = rule.get("set", {})
    if "concept" in s:
        frag["concept"] = s["concept"]
    if "aspect" in s:
        frag["attributes"] = heuristics.replace_attr(frag["attributes"], ":aspect", s["aspect"])
    if "modstr" in s:
        frag["attributes"] = heuristics.replace_attr(frag["attributes"], ":modstr", s["modstr"])
    frag["trace"] = f"[heuristic] {rule.get('note') or 'manual correction'} -> {frag['concept']}"
    return frag


def _copula_head(c: dict):
    """Pick the right reification predicate for a copular clause."""
    comp = c["chunks"][0] if c["chunks"] else None
    if comp and comp.get("relation_hint") == ":place":
        return "have-place-91", ":ARG1", ":ARG2", "State"
    if comp and _is_single_adjective(comp["text"]):
        return "have-mod-91", ":ARG1", ":ARG2", "State"
    return "identity-91", ":ARG1", ":ARG2", "State"


def _is_single_adjective(text: str) -> bool:
    toks = nlp.tokenize(text)
    content = [t for t in toks if t.pos not in {"DET", "PUNCT"}]
    return len(content) == 1 and content[0].pos == "ADJ"


def _aspect(lemma: str, c: dict) -> str:
    if lemma in _STATIVE:
        return "State"
    has_object = any(ch.get("relation_hint", "").startswith(":ARG")
                     for ch in c["chunks"])
    return "Performance" if has_object else "Activity"


def _cat(category: str) -> str:
    # nlp categories map directly onto expand_as terminals/recursions
    return category


def _child(relation, expand_as, text, hint=None):
    return {"relation": relation, "relation_hint": hint,
            "text": text, "expand_as": expand_as}


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "Edmund Pope tasted freedom today."
    print(json.dumps(run(text), indent=2, ensure_ascii=False))
