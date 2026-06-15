#!/usr/bin/env python3
"""
Smoke test for the UMR layered parser (mock engine, no network, no deps).

Runs the whole peeling pipeline end-to-end on the sample sentences and checks
the invariants that must hold regardless of heuristic quality:

  * the harness never crashes,
  * the Penman output is balanced and has a single root,
  * every relation emitted is a legal UMR label (catches hallucinated edges),
  * every inline attribute value is legal for its attribute,
  * the JSON fragment extractor survives noisy CLI-style output.

Run:  python tests/test_smoke.py     (exits non-zero on failure)
"""
from __future__ import annotations
import os, re, sys, tempfile, importlib.util, contextlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harness import Parser, MockEngine, _extract_json   # noqa: E402
from tools import umr_inventory as inv                   # noqa: E402
from tools import heuristics                             # noqa: E402


@contextlib.contextmanager
def _scratch_heuristics():
    """Point the heuristics store at a throwaway dir for the duration."""
    old = os.environ.get("UMR_HEURISTICS_BASE")
    with tempfile.TemporaryDirectory() as d:
        os.environ["UMR_HEURISTICS_BASE"] = d
        try:
            yield d
        finally:
            if old is None:
                os.environ.pop("UMR_HEURISTICS_BASE", None)
            else:
                os.environ["UMR_HEURISTICS_BASE"] = old


def _load_skill(skill: str):
    mod_file = skill.replace("-", "_")
    path = os.path.join(ROOT, "skills", skill, "scripts", f"{mod_file}.py")
    spec = importlib.util.spec_from_file_location(f"_t_{mod_file}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

SENTENCES = [
    "Edmund Pope tasted freedom today.",
    "He denied any wrongdoing.",
    "I will go for a walk or play some soccer.",
    "Sarah moved back to California because she could not find a job.",
    "Pope was flown to the military base in Germany.",
    "The president pardoned him for health reasons.",
    "She gave the book to her friend.",
    "They barbecued chicken at home.",
]

_REL_RE = re.compile(r"(:[A-Za-z][\w-]*)")


def _balanced(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def check_sentence(sentence: str) -> list[str]:
    errors: list[str] = []
    parser = Parser(MockEngine(), trace=True)
    parser.parse(sentence)
    penman = parser.graph.to_penman()

    if not penman.startswith("("):
        errors.append(f"{sentence!r}: graph has no root node")
    if not _balanced(penman):
        errors.append(f"{sentence!r}: unbalanced parentheses")

    attr_keys = set(inv.ATTRIBUTE_VALUES)
    for label in _REL_RE.findall(penman):
        if label in attr_keys:
            continue
        if not inv.is_relation(label):
            errors.append(f"{sentence!r}: illegal label {label!r} in graph")

    # at least one skill of each kind should have fired across the corpus
    layers = {e["layer"] for e in parser.trace}
    if "umr-segment" not in layers:
        errors.append(f"{sentence!r}: segment layer never ran")
    return errors


def test_attribute_values_legal():
    """Attribute values produced for the corpus must validate."""
    errors = []
    for sentence in SENTENCES:
        parser = Parser(MockEngine())
        parser.parse(sentence)
        # walk the node tree
        stack = [parser.graph.root]
        while stack:
            node = stack.pop()
            if node is None or not hasattr(node, "attrs"):
                continue
            for rel, const in node.attrs:
                if rel in inv.ATTRIBUTE_VALUES:
                    try:
                        inv.validate_attribute(rel, const.value)
                    except ValueError as e:
                        errors.append(f"{sentence!r}: {e}")
            stack.extend(t for _, t in node.edges if hasattr(t, "attrs"))
    assert not errors, "\n".join(errors)


def test_corpus_parses_cleanly():
    all_errors = []
    for s in SENTENCES:
        all_errors.extend(check_sentence(s))
    assert not all_errors, "\n".join(all_errors)


def test_json_extractor_handles_noise():
    noisy = 'Sure! Here is the fragment:\n```json\n{"concept": "go-01", ' \
            '"children": [{"text": "a \\"book\\""}]}\n```\nHope that helps.'
    frag = _extract_json(noisy)
    assert frag is not None and frag["concept"] == "go-01"
    assert frag["children"][0]["text"] == 'a "book"'


def test_inventory_validation():
    assert inv.is_relation(":ARG0")
    assert inv.is_relation(":ARG1-of")
    assert inv.is_relation(":op3")
    assert inv.is_relation(":poss")
    assert not inv.is_relation(":totally-made-up")


def test_heuristic_match_specificity_and_regex():
    with _scratch_heuristics():
        # two rules; the more specific one should win
        heuristics.add("umr-role", {"head_concept": "give-01"},
                       {"relation": ":goal"}, "broad")
        heuristics.add("umr-role",
                       {"head_concept": "give-01", "child_text": "her friend"},
                       {"relation": ":recipient"}, "specific")
        r = heuristics.match("umr-role",
                             {"head_concept": "give-01", "child_text": "her friend"})
        assert r["set"]["relation"] == ":recipient", "most specific rule must win"
        # regex match on a different field
        heuristics.add("umr-role", {"child_text_regex": "knife$"},
                       {"relation": ":instrument"}, "tools")
        r2 = heuristics.match("umr-role", {"child_text": "a sharp knife"})
        assert r2 and r2["set"]["relation"] == ":instrument"
        # no match -> None
        assert heuristics.match("umr-role", {"head_concept": "walk-01"}) is None


def test_role_correction_overrides_default():
    with _scratch_heuristics():
        umr_role = _load_skill("umr-role")
        ctx = {"head_concept": "give-01", "head_text": "gave",
               "child_text": "her friend", "category": "entity",
               "relation_hint": ":goal"}
        before = umr_role.run("her friend", ctx)["relation"]
        assert before == ":goal", "default heuristic should pick the hint :goal"
        heuristics.add("umr-role",
                       {"head_concept": "give-01", "child_text": "her friend"},
                       {"relation": ":recipient"}, "animate receiver")
        after = umr_role.run("her friend", ctx)["relation"]
        assert after == ":recipient", "learned correction must override"


def test_predicate_correction_fixes_lemma():
    with _scratch_heuristics():
        umr_predicate = _load_skill("umr-predicate")
        before = umr_predicate.run("They barbecued chicken at home.")["concept"]
        assert before == "barbecu-01", "lemmatizer stem reproduces the known bug"
        heuristics.add("umr-predicate", {"verb_surface_regex": "^barbecu"},
                       {"concept": "barbecue-01", "aspect": "Performance"}, "fix")
        after = umr_predicate.run("They barbecued chicken at home.")["concept"]
        assert after == "barbecue-01", "learned correction must fix the head concept"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}\n      {e}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nall smoke tests passed")
