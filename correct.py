#!/usr/bin/env python3
"""
correct.py  --  teach the parser from human corrections.

You look at a parse, see something mislabeled, and record the fix. It is stored
as a heuristic in skills/<layer>/heuristics.jsonl and applies on the very next
parse, under BOTH engines (the mock scripts read it directly; the claude engine
gets it injected into the skill prompt as an authoritative correction).

Corrections are content-keyed, not tied to one sentence -- so a fix generalizes
to every future sentence with the same situation.

Examples
--------
# "to her friend" under give-01 is a recipient, not a spatial goal:
python correct.py role --head give-01 --child "her friend" --relation :recipient \
       --note "animate receiver"

# generalize with regex (any give.* + any child containing 'friend'):
python correct.py role --head-regex "give-\\d+" --child-regex friend --relation :recipient

# a multiword named entity that the tagger misses, with its type:
python correct.py entity --span "bone cancer" --ne-type disease --wiki "Bone_cancer"

# fix a lemma / sense and pin the aspect of a verb:
python correct.py predicate --verb barbecue --concept barbecue-01 --aspect Performance

# stop a false coordination split on a span:
python correct.py segment --span "rock and roll is here to stay" --no-split

# review what has been learned:
python correct.py list
python correct.py list umr-role
"""
from __future__ import annotations
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from tools import heuristics             # noqa: E402
from tools import umr_inventory as inv   # noqa: E402

LAYERS = {"segment": "umr-segment", "predicate": "umr-predicate",
          "role": "umr-role", "entity": "umr-entity"}

_QUIT = object()
_SKIP_REST = object()


def _put(match: dict, key: str, val):
    if val is not None and val != "":
        match[key] = val


def cmd_role(a):
    match: dict = {}
    _put(match, "head_concept", a.head)
    _put(match, "head_concept_regex", a.head_regex)
    _put(match, "child_text", a.child)
    _put(match, "child_text_regex", a.child_regex)
    _put(match, "relation_hint", a.hint)
    _put(match, "category", a.category)
    if not match:
        sys.exit("role: give at least one match condition (--head/--child/...)")
    if not inv.is_relation(a.relation):
        sys.exit(f"role: {a.relation!r} is not a legal UMR relation")
    return heuristics.add("umr-role", match, {"relation": a.relation}, a.note)


def cmd_entity(a):
    match: dict = {}
    _put(match, "span", a.span)
    _put(match, "span_regex", a.span_regex)
    if not match:
        sys.exit("entity: give --span or --span-regex")
    setd: dict = {}
    _put(setd, "ne_type", a.ne_type)
    _put(setd, "name", a.name)
    _put(setd, "wiki", a.wiki)
    _put(setd, "concept", a.concept)
    _put(setd, "head", a.head)
    _put(setd, "ref_number", a.ref_number)
    _put(setd, "ref_person", a.ref_person)
    if not setd:
        sys.exit("entity: give at least one of --ne-type/--concept/--head/...")
    if a.ne_type and a.ne_type not in inv.NE_TYPES:
        sys.stderr.write(f"[warn] '{a.ne_type}' is not in the bundled NE ontology "
                         "(allowed but unverified)\n")
    return heuristics.add("umr-entity", match, setd, a.note)


def cmd_predicate(a):
    match: dict = {}
    _put(match, "span", a.span)
    _put(match, "span_regex", a.span_regex)
    _put(match, "verb", a.verb)
    _put(match, "verb_regex", a.verb_regex)
    _put(match, "verb_surface", a.verb_surface)
    _put(match, "verb_surface_regex", a.verb_surface_regex)
    _put(match, "concept", a.concept_match)
    if not match:
        sys.exit("predicate: give --span/--verb/--verb-surface (or a *-regex)")
    setd: dict = {}
    _put(setd, "concept", a.concept)
    _put(setd, "aspect", a.aspect)
    _put(setd, "modstr", a.modstr)
    if not setd:
        sys.exit("predicate: give at least one of --concept/--aspect/--modstr")
    if a.aspect and a.aspect not in inv.ASPECT_VALUES:
        sys.exit(f"predicate: {a.aspect!r} is not a legal aspect value")
    if a.modstr and a.modstr not in inv.MODSTR_VALUES:
        sys.exit(f"predicate: {a.modstr!r} is not a legal modstr value")
    return heuristics.add("umr-predicate", match, setd, a.note)


def cmd_segment(a):
    match: dict = {}
    _put(match, "span", a.span)
    _put(match, "span_regex", a.span_regex)
    if not match:
        sys.exit("segment: give --span or --span-regex")
    setd: dict = {}
    if a.no_split:
        setd["no_split"] = True
    _put(setd, "connective", a.connective)
    if not setd:
        sys.exit("segment: give --no-split or --connective")
    return heuristics.add("umr-segment", match, setd, a.note)


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "\x00quit"          # treat end-of-input as quit
    return val or default


def _correct_decision(d: dict) -> bool:
    """Interactively turn one decision into a heuristic. Returns True if added."""
    layer, kind = d["layer"], d["kind"]
    if kind == "relation":
        new = _ask(f"    new relation (current {d['current']}, e.g. :recipient): ")
        if new in ("", "\x00quit") or not inv.is_relation(new):
            if new and new != "\x00quit":
                print(f"    '{new}' is not a legal relation; skipped.")
            return False
        note = _ask("    note (optional): ")
        heuristics.add(layer, d["match"], {"relation": new}, note)
    elif kind == "concept":
        new = _ask(f"    new head concept (current {d['current']}, e.g. barbecue-01): ")
        if new in ("", "\x00quit"):
            return False
        note = _ask("    note (optional): ")
        heuristics.add(layer, d["match"], {"concept": new}, note)
    elif kind == "aspect":
        new = _ask(f"    new aspect (current {d['current']}; one of "
                   f"{', '.join(inv.ASPECT_VALUES_COARSE)}): ")
        if new in ("", "\x00quit") or new not in inv.ASPECT_VALUES:
            if new and new != "\x00quit":
                print(f"    '{new}' is not a legal aspect; skipped.")
            return False
        note = _ask("    note (optional): ")
        heuristics.add(layer, d["match"], {"aspect": new}, note)
    elif kind == "entity":
        print("    fix as:  ne:<type> (named entity) | head:<noun> | <raw concept>")
        new = _ask(f"    new value (current {d['current']}): ")
        if new in ("", "\x00quit"):
            return False
        note = _ask("    note (optional): ")
        if new.startswith("ne:"):
            setd = {"ne_type": new[3:]}
        elif new.startswith("head:"):
            setd = {"head": new[5:]}
        else:
            setd = {"concept": new}
        heuristics.add(layer, d["match"], setd, note)
    elif kind == "split":
        new = _ask("    type 'nosplit' to undo the split, or a connective "
                   "(and/or/but/contrast-91): ")
        if new in ("", "\x00quit"):
            return False
        note = _ask("    note (optional): ")
        setd = {"no_split": True} if new == "nosplit" else {"connective": new}
        heuristics.add(layer, d["match"], setd, note)
    else:
        return False
    print("    ✓ correction recorded.")
    return True


def cmd_review(a):
    from harness import Parser, MockEngine, ClaudeEngine
    engine = ClaudeEngine(model=a.model) if a.engine == "claude" else MockEngine()

    parser = Parser(engine)
    parser.parse(a.sentence)
    print("\nsentence:", a.sentence)
    print("\ncurrent parse:")
    print(parser.graph.to_penman())
    decisions = parser.decisions
    print(f"\n{len(decisions)} decisions to review. For each: "
          "[Enter]=keep  c=correct  s=skip rest  q=quit\n")

    added = 0
    stop = False
    for i, d in enumerate(decisions, 1):
        if stop:
            break
        print(f"[{i}/{len(decisions)}] {d['layer']}:  {d['display']}")
        choice = _ask("    > ").lower()
        if choice in ("q", "\x00quit"):
            break
        if choice == "s":
            stop = True
            continue
        if choice == "c":
            if _correct_decision(d):
                added += 1
        # anything else (incl. empty) = keep

    print(f"\n{added} correction(s) recorded.")
    if added:
        reparse = _ask("re-parse to see the effect? [Y/n]: ").lower()
        if reparse in ("", "y", "yes"):
            p2 = Parser(engine if a.engine != "claude" else MockEngine())
            p2.parse(a.sentence)
            print("\nupdated parse:")
            print(p2.graph.to_penman())
    return None


def cmd_list(a):
    skills = [LAYERS[a.layer]] if a.layer in LAYERS else list(LAYERS.values())
    for skill in skills:
        rules = heuristics.load(skill)
        print(f"\n# {skill}  ({len(rules)} rule{'s' if len(rules) != 1 else ''})")
        block = heuristics.format_for_prompt(skill)
        print(block if block else "  (none)")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("role", help="correct an edge label")
    r.add_argument("--head"); r.add_argument("--head-regex", dest="head_regex")
    r.add_argument("--child"); r.add_argument("--child-regex", dest="child_regex")
    r.add_argument("--hint"); r.add_argument("--category")
    r.add_argument("--relation", required=True)
    r.add_argument("--note", default="")
    r.set_defaults(fn=cmd_role)

    e = sub.add_parser("entity", help="correct a noun-phrase / named entity")
    e.add_argument("--span"); e.add_argument("--span-regex", dest="span_regex")
    e.add_argument("--ne-type", dest="ne_type")
    e.add_argument("--name"); e.add_argument("--wiki")
    e.add_argument("--concept"); e.add_argument("--head")
    e.add_argument("--ref-number", dest="ref_number")
    e.add_argument("--ref-person", dest="ref_person")
    e.add_argument("--note", default="")
    e.set_defaults(fn=cmd_entity)

    p = sub.add_parser("predicate", help="correct a head concept / aspect / modstr")
    p.add_argument("--span"); p.add_argument("--span-regex", dest="span_regex")
    p.add_argument("--verb"); p.add_argument("--verb-regex", dest="verb_regex")
    p.add_argument("--verb-surface", dest="verb_surface",
                   help="match the verb as written, e.g. 'barbecued'")
    p.add_argument("--verb-surface-regex", dest="verb_surface_regex")
    p.add_argument("--match-concept", dest="concept_match",
                   help="match the (wrong) concept currently produced, e.g. barbecu-01")
    p.add_argument("--concept"); p.add_argument("--aspect"); p.add_argument("--modstr")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_predicate)

    s = sub.add_parser("segment", help="correct a discourse split")
    s.add_argument("--span"); s.add_argument("--span-regex", dest="span_regex")
    s.add_argument("--no-split", action="store_true", dest="no_split")
    s.add_argument("--connective")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_segment)

    v = sub.add_parser("review", help="walk a parse decision-by-decision and fix it")
    v.add_argument("sentence", help="the sentence to review")
    v.add_argument("--engine", choices=["mock", "claude"], default="mock")
    v.add_argument("--model", default=None)
    v.set_defaults(fn=cmd_review)

    l = sub.add_parser("list", help="show learned corrections")
    l.add_argument("layer", nargs="?", default="all")
    l.set_defaults(fn=cmd_list)

    args = ap.parse_args()
    rule = args.fn(args)
    if rule is not None:
        import json
        print("added heuristic:")
        print("  " + json.dumps(rule, ensure_ascii=False))
        print("it will apply on the next parse (mock and claude engines).")


if __name__ == "__main__":
    main()
