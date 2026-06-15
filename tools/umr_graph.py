"""
UMR graph model + Penman serializer.

A UMR sentence graph is a rooted, (mostly) tree-shaped structure of concept
nodes connected by labeled relations, with constant-valued attributes hanging
inline. This module is the thing the harness *builds up* as the layers peel the
sentence apart, and then prints in the standard Penman notation, e.g.

    (t / taste-01
        :ARG0 (p / person
            :name (n / name :op1 "Edmund" :op2 "Pope"))
        :ARG1 (f / free-04
            :ARG1 p)
        :aspect Performance
        :modstr FullAff)

Variable naming follows the AMR/UMR convention: first alphabetic character of
the concept, lowercased, with a numeric suffix to disambiguate.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Union


@dataclass
class Const:
    """An inline constant value: a number, '-', or a quoted string."""
    value: str
    quoted: bool = False

    def render(self) -> str:
        return f'"{self.value}"' if self.quoted else self.value


@dataclass
class Ref:
    """A reentrancy: a relation pointing back at an already-introduced variable."""
    var: str


@dataclass
class Node:
    concept: str
    node_type: str = "entity"        # event | entity | discourse | value
    var: str = ""
    # ordered edges: (relation, target) where target is Node | Const | Ref
    edges: list = field(default_factory=list)
    # inline attributes: (relation, Const)
    attrs: list = field(default_factory=list)
    # bookkeeping for the peeling trace
    source_text: str = ""

    def add_edge(self, relation: str, target: Union["Node", Const, Ref]):
        self.edges.append((relation, target))

    def add_attr(self, relation: str, value: str, quoted: bool = False):
        self.attrs.append((relation, Const(value, quoted)))


class Graph:
    def __init__(self):
        self._counts: dict[str, int] = {}
        self.root: Node | None = None

    def new_var(self, concept: str) -> str:
        # first alpha char, lowercased; fall back to 'x'
        base = next((c.lower() for c in concept if c.isalpha()), "x")
        n = self._counts.get(base, 0) + 1
        self._counts[base] = n
        return base if n == 1 else f"{base}{n}"

    def node(self, concept: str, node_type: str = "entity", source_text: str = "") -> Node:
        nd = Node(concept=concept, node_type=node_type, source_text=source_text)
        nd.var = self.new_var(concept)
        return nd

    # -- serialization -----------------------------------------------------
    def to_penman(self, root: Node | None = None, indent: int = 0) -> str:
        root = root or self.root
        if root is None:
            return "()"
        return self._render(root, indent)

    def _render(self, node: Node, indent: int) -> str:
        pad = " " * indent
        child_pad = " " * (indent + 4)
        head = f"({node.var} / {node.concept}"
        lines = [head]
        # inline attributes first or interleaved? UMR interleaves, but grouping
        # edges then attributes is valid and more readable.
        for rel, target in node.edges:
            if isinstance(target, Node):
                rendered = self._render(target, indent + 4)
                lines.append(f"{child_pad}{rel} {rendered}")
            elif isinstance(target, Ref):
                lines.append(f"{child_pad}{rel} {target.var}")
            elif isinstance(target, Const):
                lines.append(f"{child_pad}{rel} {target.render()}")
        for rel, const in node.attrs:
            lines.append(f"{child_pad}{rel} {const.render()}")
        return "\n".join(lines) + ")"


# Convenience for callers that already have a finished node tree.
def render(root: Node) -> str:
    g = Graph()
    return g._render(root, 0)
