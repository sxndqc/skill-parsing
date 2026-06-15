#!/usr/bin/env python3
"""
umr-segment code tool / mock-engine implementation.

Layer 0: decide discourse-vs-verb. Coordination -> connective node with :opN
coordinands; otherwise passthrough to the predicate layer.

`run(span, context) -> fragment` is the interface the harness calls. Running the
file directly prints the fragment for a span (handy for eyeballing the split).
"""
from __future__ import annotations
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from tools import nlp_tools as nlp   # noqa: E402
from tools import heuristics         # noqa: E402


def run(span: str, context: dict | None = None) -> dict:
    rule = heuristics.match("umr-segment", {"span": span})
    rset = rule.get("set", {}) if rule else {}

    # a correction may forbid splitting this span (false coordination)
    if rset.get("no_split"):
        return {
            "concept": None, "node_type": "passthrough", "attributes": [],
            "children": [{"relation": None, "relation_hint": None,
                          "text": span, "expand_as": "predicate"}],
            "trace": f"[heuristic] {rule.get('note') or 'do not split'} -> passthrough",
        }

    coord = nlp.find_top_coordination(span)
    if coord:
        concept = rset.get("connective") or rset.get("concept") or coord["concept"]
        children = [
            {"relation": f":op{i+1}", "relation_hint": None,
             "text": c, "expand_as": "clause"}
            for i, c in enumerate(coord["coordinands"])
        ]
        trace = (f"top-level '{coord['connective']}' coordination "
                 f"-> {concept} node with {len(children)} coordinands")
        if concept != coord["concept"]:
            trace = f"[heuristic] {rule.get('note') or 'connective override'} -> {concept}"
        return {
            "concept": concept,
            "node_type": "discourse",
            "attributes": [],
            "children": children,
            "trace": trace,
        }
    return {
        "concept": None,
        "node_type": "passthrough",
        "attributes": [],
        "children": [{"relation": None, "relation_hint": None,
                      "text": span, "expand_as": "predicate"}],
        "trace": "single backbone event -> hand to predicate layer",
    }


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "I will go for a walk or play some soccer."
    print(json.dumps(run(text), indent=2, ensure_ascii=False))
