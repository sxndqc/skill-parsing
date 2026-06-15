#!/usr/bin/env python3
"""
UMR layered-parsing harness  --  the thing that *calls the skills*.

A sentence is parsed by recursively peeling it, one layer at a time. The harness
owns the recursion; each layer of judgement is delegated to a skill:

    clause span ---------------> umr-segment   (discourse or single event?)
      single clause -----------> umr-predicate (find verb, bracket phrases)
        each bracketed edge ---> umr-role      (what relation is this?)
        each nominal phrase ---> umr-entity    (head noun + modifiers; named entity)
          each modifier -------> umr-role + recurse ...

The harness is engine-agnostic. With `--engine mock` it calls each skill's
`scripts/<skill>.py:run()` (deterministic heuristics, zero dependencies, runs
offline). With `--engine claude` it shells out to the `claude` CLI, feeding it
the skill's SKILL.md plus the span and parsing the JSON fragment that comes back
-- i.e. the *same skills*, judged by the model instead of by heuristics. Both
engines speak the identical "fragment" contract, so the recursion code below does
not care which one is in use.

Usage:
    python harness.py "Edmund Pope tasted freedom today." --trace
    python harness.py "I will walk or play soccer." --engine mock
    python harness.py --file examples/sample_sentences.txt
    python harness.py "He denied any wrongdoing." --engine claude --model sonnet
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from tools.umr_graph import Graph, Node, Const, Ref   # noqa: E402
from tools import umr_inventory as inv                # noqa: E402
from tools import heuristics                          # noqa: E402

SKILLS_DIR = os.path.join(ROOT, "skills")

# expand_as categories the harness resolves WITHOUT calling a skill (terminals).
TERMINALS = {"name", "string", "value", "leaf"}


# ===========================================================================
# Engines: how a skill gets "called"
# ===========================================================================
class MockEngine:
    """Calls each skill's deterministic heuristic implementation."""
    name = "mock"

    def __init__(self):
        self._cache: dict[str, object] = {}

    def _module(self, skill: str):
        if skill not in self._cache:
            mod_file = skill.replace("-", "_")
            path = os.path.join(SKILLS_DIR, skill, "scripts", f"{mod_file}.py")
            spec = importlib.util.spec_from_file_location(f"_skill_{mod_file}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._cache[skill] = module
        return self._cache[skill]

    def call(self, skill: str, span: str, context: dict) -> dict:
        return self._module(skill).run(span, context)


class ClaudeEngine:
    """Calls each skill via the `claude` CLI, feeding it the SKILL.md."""
    name = "claude"

    def __init__(self, model: str | None = None, timeout: int = 120):
        self.model = model
        self.timeout = timeout
        self._fallback = MockEngine()
        self._skill_bodies: dict[str, str] = {}

    def _body(self, skill: str) -> str:
        if skill not in self._skill_bodies:
            text = open(os.path.join(SKILLS_DIR, skill, "SKILL.md")).read()
            # strip YAML frontmatter
            if text.startswith("---"):
                text = text.split("---", 2)[-1]
            self._skill_bodies[skill] = text.strip()
        return self._skill_bodies[skill]

    def _prompt(self, skill: str, span: str, context: dict) -> str:
        parts = [
            f"You are applying the `{skill}` skill below to ONE span. Follow it "
            "exactly and respond with ONLY the JSON fragment it specifies -- no "
            "prose, no code fences. Fill every field with REAL values drawn from "
            "the legal labels; never copy placeholder text from the schema "
            "(e.g. do not emit \"attribute\" or \"value\" literally). Attribute "
            "pairs must look like [\":ref-person\", \"3rd\"].",
            "\n===== SKILL =====\n" + self._body(skill),
        ]
        if skill in {"umr-role", "umr-entity", "umr-predicate"}:
            parts.append("\n===== LEGAL UMR LABELS =====\n" + inv.dump_json())
        learned = heuristics.format_for_prompt(skill)
        if learned:
            parts.append(
                "\n===== LEARNED CORRECTIONS (authoritative; a human reviewed "
                "these and they OVERRIDE your default judgement) =====\n" + learned)
        parts.append("\n===== SPAN =====\n" + span)
        if context:
            parts.append("\n===== CONTEXT =====\n" + json.dumps(context, ensure_ascii=False))
        return "\n".join(parts)

    def call(self, skill: str, span: str, context: dict) -> dict:
        cmd = ["claude", "-p", self._prompt(skill, span, context)]
        if self.model:
            cmd[2:2] = ["--model", self.model]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=self.timeout)
            frag = _extract_json(res.stdout)
            if frag is None:
                raise ValueError(f"no JSON in claude output:\n{res.stdout[:400]}")
            frag.setdefault("attributes", [])
            frag.setdefault("children", [])
            return frag
        except Exception as e:  # never hard-fail a parse; degrade to heuristic
            sys.stderr.write(f"[claude:{skill}] {e}; falling back to mock for this node\n")
            return self._fallback.call(skill, span, context)


def _extract_json(text: str) -> dict | None:
    """Pull the first balanced {...} object out of arbitrary CLI output."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    return None


# ===========================================================================
# The recursion: peel a span into a graph node
# ===========================================================================
class Parser:
    def __init__(self, engine, max_depth: int = 25, trace: bool = False):
        self.engine = engine
        self.graph = Graph()
        self.max_depth = max_depth
        self.trace_on = trace
        self.trace: list[dict] = []
        # structured, correctable decision points (consumed by `correct.py review`)
        self.decisions: list[dict] = []

    def _log(self, depth: int, layer: str, span: str, decision: str):
        self.trace.append({"depth": depth, "layer": layer,
                           "span": span, "decision": decision})

    def _record(self, layer, kind, match, current, display, span):
        self.decisions.append({"layer": layer, "kind": kind, "match": match,
                               "current": current, "display": display,
                               "span": span})

    def parse(self, sentence: str) -> Node:
        root = self.expand(sentence.strip(), "clause", 0)
        self.graph.root = root
        return root

    # -- core dispatch ----------------------------------------------------
    def expand(self, span: str, expand_as: str, depth: int):
        if depth > self.max_depth:
            return self.graph.node("thing", "entity", span)

        if expand_as in TERMINALS:
            return self._terminal(span, expand_as, depth)

        if expand_as == "clause":
            return self._expand_clause(span, depth)
        if expand_as == "predicate":
            return self._expand_with("umr-predicate", span, depth)
        if expand_as == "entity":
            return self._expand_with("umr-entity", span, depth)
        # unknown -> treat as entity
        return self._expand_with("umr-entity", span, depth)

    def _expand_clause(self, span: str, depth: int):
        frag = self.engine.call("umr-segment", span, {})
        self._log(depth, "umr-segment", span, frag.get("trace", ""))
        if frag.get("node_type") == "passthrough":
            child = frag["children"][0]
            return self.expand(child["text"], child["expand_as"], depth)
        # a discourse node = a coordination split decision the user may reject
        self._record("umr-segment", "split", {"span": span}, frag["concept"],
                     f"split into {frag['concept']} coordination", span)
        return self._build_node(frag, span, depth, "umr-segment")

    def _expand_with(self, skill: str, span: str, depth: int):
        frag = self.engine.call(skill, span, {})
        self._log(depth, skill, span, frag.get("trace", ""))
        if frag.get("node_type") == "passthrough":
            child = frag["children"][0]
            return self.expand(child["text"], child["expand_as"], depth)
        return self._build_node(frag, span, depth, skill)

    def _build_node(self, frag: dict, span: str, depth: int, skill: str = "") -> Node:
        concept = frag["concept"]
        node = self.graph.node(concept, frag.get("node_type", "entity"), span)
        attrs_dict = {}
        for rel, value in frag.get("attributes", []):
            # validate inline attributes against the inventory so a malformed
            # skill reply (e.g. a model echoing schema placeholders) can never
            # leak garbage like ":foo bar" into the graph
            allowed = inv.ATTRIBUTE_VALUES.get(rel)
            if allowed is not None and value in allowed:
                node.add_attr(rel, value)
                attrs_dict[rel] = value
            else:
                sys.stderr.write(
                    f"[harness] dropped invalid attribute {rel!r}={value!r} "
                    f"on {node.concept}\n")
        # record correctable head / attribute / entity-type decisions
        if skill == "umr-predicate":
            self._record("umr-predicate", "concept", {"concept": concept},
                         concept, f"head concept of \"{span}\" = {concept}", span)
            if ":aspect" in attrs_dict:
                self._record("umr-predicate", "aspect", {"concept": concept},
                             attrs_dict[":aspect"],
                             f"aspect of {concept} = {attrs_dict[':aspect']}", span)
        elif skill == "umr-entity":
            self._record("umr-entity", "entity", {"span": span}, concept,
                         f"\"{span}\" parsed as {concept}", span)
        for child in frag.get("children", []):
            relation, target = self._resolve_child(node, span, child, depth)
            if target is not None:
                node.add_edge(relation, target)
        return node

    def _resolve_child(self, parent: Node, parent_text: str, child: dict, depth: int):
        relation = child.get("relation")
        expand_as = child.get("expand_as", "entity")
        # the relation-judgement layer fires for every unlabeled semantic edge
        if relation is None:
            ctx = {
                "head_concept": parent.concept,
                "head_text": parent_text,
                "child_text": child["text"],
                "category": expand_as,
                "relation_hint": child.get("relation_hint"),
            }
            rfrag = self.engine.call("umr-role", child["text"], ctx)
            relation = rfrag["relation"]
            self._log(depth + 1, "umr-role", child["text"],
                      f"{parent.concept} --{relation}--> ({rfrag.get('trace','')})")
            self._record(
                "umr-role", "relation",
                {"head_concept": parent.concept, "child_text": child["text"]},
                relation,
                f"{parent.concept} --{relation}--> \"{child['text']}\"",
                child["text"])
        target = self.expand(child["text"], expand_as, depth + 1)
        # carry any child-level inline attributes (rare)
        if isinstance(target, Node):
            for rel, value in child.get("attributes", []):
                target.add_attr(rel, value)
        return relation, target

    # -- terminals --------------------------------------------------------
    def _terminal(self, span: str, kind: str, depth: int):
        if kind == "string":
            return Const(span, quoted=True)
        if kind == "value":
            return Const(span)
        if kind == "name":
            n = self.graph.node("name", "entity", span)
            for i, tok in enumerate(span.split(), 1):
                n.add_edge(inv.op(i), Const(tok, quoted=True))
            self._log(depth, "name", span, f"name node with {len(span.split())} op(s)")
            return n
        if kind == "leaf":
            from tools import nlp_tools as nlp
            toks = [t for t in nlp.tokenize(span) if t.pos != "PUNCT"]
            concept = toks[-1].lemma if toks else span
            return self.graph.node(concept, "entity", span)
        return self.graph.node(span, "entity", span)

    # -- trace rendering --------------------------------------------------
    def render_trace(self) -> str:
        lines = ["PEELING TRACE (each line = one skill call):"]
        for e in self.trace:
            indent = "  " * e["depth"]
            span = e["span"] if len(e["span"]) <= 48 else e["span"][:45] + "..."
            lines.append(f"{indent}[{e['layer']}] \"{span}\"")
            lines.append(f"{indent}    -> {e['decision']}")
        return "\n".join(lines)


# ===========================================================================
# CLI
# ===========================================================================
def make_engine(args):
    if args.engine == "claude":
        return ClaudeEngine(model=args.model, timeout=args.timeout)
    return MockEngine()


def parse_one(sentence: str, engine, trace: bool, max_depth: int):
    p = Parser(engine, max_depth=max_depth, trace=trace)
    p.parse(sentence)
    out = []
    out.append("# " + sentence.strip())
    out.append(p.graph.to_penman())
    if trace:
        out.append("")
        out.append(p.render_trace())
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Peel a sentence into a UMR graph, layer by layer.")
    ap.add_argument("sentence", nargs="?", help="the sentence to parse")
    ap.add_argument("--file", help="parse each non-empty line of this file")
    ap.add_argument("--engine", choices=["mock", "claude"], default="mock")
    ap.add_argument("--model", default=None, help="claude model (claude engine only)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--trace", action="store_true", help="show the peeling trace")
    ap.add_argument("--max-depth", type=int, default=25)
    args = ap.parse_args()

    engine = make_engine(args)

    sentences = []
    if args.file:
        with open(args.file) as fh:
            sentences = [ln.strip() for ln in fh
                         if ln.strip() and not ln.lstrip().startswith("#")]
    elif args.sentence:
        sentences = [args.sentence]
    else:
        ap.error("provide a sentence or --file")

    blocks = [parse_one(s, engine, args.trace, args.max_depth) for s in sentences]
    print(("\n\n" + "=" * 70 + "\n\n").join(blocks))


if __name__ == "__main__":
    main()
