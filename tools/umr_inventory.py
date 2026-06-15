"""
UMR label inventory  --  the "vocabulary" every layer is allowed to use.

This is the single source of truth for the legal labels a skill may emit. It is
distilled from the UMR 0.9 guidelines (Part 3 sentence-level + Part 3-1-6
discourse relations + Part 7 alphabetical index):

    https://github.com/umr4nlp/umr-guidelines/blob/master/guidelines.md

Why this exists as a *code tool*:

    Parsing is a search problem. A human annotator does not invent edge labels;
    they pick from a closed inventory. By making that inventory machine-readable
    we (a) constrain the LLM's output to legal labels, (b) let the mock engine
    make deterministic choices, and (c) get a cheap validator that catches
    hallucinated relations before they reach the graph.

Each skill imports the slices it needs and calls `validate()` / `gloss()`.
"""

from __future__ import annotations
import json

# ---------------------------------------------------------------------------
# 1. PARTICIPANT ROLES  (Part 3-2-1)
# ---------------------------------------------------------------------------
# Two parallel systems. Languages WITH PropBank-style frame files use numbered
# roles; languages WITHOUT use the generic ("non-numbered") role set. A parser
# normally commits to one system per predicate.

NUMBERED_ROLES = [f":ARG{i}" for i in range(6)]            # :ARG0 .. :ARG5

# Generic participant roles (the "thematic" inventory) -- Part 3-2-1-1.
GENERIC_ROLES = {
    ":actor":        "volitional initiator of an action",
    ":undergoer":    "entity that undergoes / is affected by a change",
    ":theme":        "entity moved, located, or whose state is predicated",
    ":experiencer":  "sentient entity having a mental/perceptual experience",
    ":stimulus":     "what triggers an experience",
    ":causer":       "entity that brings a state of affairs about",
    ":cause":        "non-volitional cause / reason event",
    ":force":        "non-volitional natural force initiating an event",
    ":recipient":    "animate endpoint of a transfer",
    ":goal":         "endpoint of motion or a transfer",
    ":source":       "starting point of motion / transfer (= origin)",
    ":start":        "starting point (temporal/spatial) of an event",
    ":instrument":   "tool/means used to carry out the action",
    ":material":     "stuff something is made from / consumed",
    ":companion":    "entity accompanying a participant ('with X')",
    ":place":        "location participant of the event",
    ":affectee":     "entity (dis)advantaged by the event (benefactive/malefactive)",
    ":manner":       "how the event is carried out",
    ":purpose":      "intended goal event of an agent",
    ":temporal":     "event/time the event is temporally anchored to",
    ":condition":    "event the main event is contingent upon",
    ":concession":   "event despite which the main event holds",
}

# Inverse ("-of") variants are legal for every participant role (Part 3-2-1-3).
def inverse(role: str) -> str:
    """':ARG0' -> ':ARG0-of'.  Used for relative clauses / nominal modification."""
    return role + "-of"


# ---------------------------------------------------------------------------
# 2. NON-PARTICIPANT ROLE RELATIONS  (Part 3-2-2)
# ---------------------------------------------------------------------------
# Relations that hold inside noun phrases / between an entity and a modifier,
# rather than between an event and its arguments. This is the inventory the
# ENTITY layer leans on when it "splits a phrase into words".

NONPARTICIPANT_ROLES = {
    ":mod":        "typifying / attributive modifier (adjective, classifying noun)",
    ":poss":       "possession ('X's Y', 'Y of X')",
    ":part-of":    "X is a part of the parent whole",
    ":consist-of": "the parent consists of / is made up of X",
    ":age":        "age of an entity",
    ":name":       "links an entity to its (name ...) constant",
    ":wiki":       "Wikipedia/KB link string for a named entity",
    ":topic":      "what something is about",
    ":medium":     "medium an action/communication is carried out through",
    ":direction":  "direction of motion (non-endpoint)",
    ":path":       "path traversed",
    ":duration":   "length of time an event lasts",
    ":frequency":  "how often an event occurs",
    ":ord":        "ordinal position (links to ordinal-entity)",
    ":range":      "scope / extent (e.g. 'more than 8 months')",
    ":scale":      "scale a measurement is on",
    ":unit":       "measurement unit",
    ":value":      "numeric value",
    ":quant":      "quantity / cardinality of an entity",
    ":polite":     "politeness marking",
    ":example":    "an exemplifying instance",
    ":other":      "catch-all for a relation not otherwise covered",
}

# Operand relations for abstract concepts (and/or/name/...): :op1 :op2 ...
def op(i: int) -> str:
    return f":op{i}"

# Calendar / clock sub-relations of a time expression (Part 3-2-2-1).
TEMPORAL_SUBRELATIONS = {
    ":calendar", ":era", ":century", ":decade", ":year", ":year2", ":season",
    ":quarter", ":month", ":week", ":day", ":weekday", ":dayperiod", ":timezone",
}


# ---------------------------------------------------------------------------
# 3. DISCOURSE CONNECTIVES  (Part 3-1-6)
# ---------------------------------------------------------------------------
# When a sentence packs more than one event, the SEGMENT layer either:
#   (a) builds a coordinating connective NODE (these concepts), with the
#       coordinands hung off :op1 :op2 ...   OR
#   (b) lets a subordinate clause attach to the main event via a discourse
#       RELATION (these are participant/non-participant roles, listed below).

DISCOURSE_CONNECTIVE_CONCEPTS = {
    # higher-level, polysemous coordinators
    "and":            "conjunctive / additive coordination",
    "or":             "disjunctive coordination (alternatives)",
    "but":            "adversative coordination",
    "contrast-91":    "explicit contrast between two events",
    # finer-grained additive family
    "additive":       "two events form a complex figure (general addition)",
    "consecutive":    "events sequenced temporally/logically",
    "inclusive-disj": "non-exhaustive disjunction (any or all alternatives)",
    "exclusive-disj": "exhaustive disjunction (mutually exclusive alternatives)",
}

# Discourse RELATIONS used when one clause subordinates to another. Most reuse
# participant-role labels; UMR adds a few dedicated ones.
DISCOURSE_RELATIONS = {
    ":purpose":      "intention to bring about the subordinate event",
    ":cause":        "subordinate event causes the main event",
    ":condition":    "main event contingent on the subordinate event",
    ":concession":   "main event holds despite the subordinate event",
    ":manner":       "means/manner (positive circumstantial)",
    ":temporal":     "anterior/posterior/simultaneous sequencing",
    ":substitute":   "subordinate event is rejected alternative (:ARG2) of replacement",
    ":apprehensive": "act done to prevent the (feared) subordinate event",
    ":pure-addition":"events must co-occur, no temporal ordering implied",
}


# ---------------------------------------------------------------------------
# 4. ATTRIBUTES  (Part 3-3)  -- constant-valued, sit inline on a node
# ---------------------------------------------------------------------------

ASPECT_VALUES_COARSE = ["Activity", "Habitual", "State", "Endeavor", "Performance"]
ASPECT_VALUES_FINE = [
    "Process", "Atelic Process", "Imperfective", "Perfective",
    "Inherent state", "Point state", "Reversible state", "Irreversible state",
    "Directed activity", "Undirected activity",
    "Directed achievement", "Reversible directed achievement",
    "Irreversible directed achievement",
    "Directed endeavor", "Undirected endeavor",
    "Semelfactive", "Incremental accomplishment", "Non-incremental accomplishment",
]
ASPECT_VALUES = ASPECT_VALUES_COARSE + ASPECT_VALUES_FINE

# :modstr -- epistemic strength of the (author-)conceiver toward the event.
MODSTR_VALUES = ["FullAff", "PrtAff", "NeutAff", "FullNeg", "PrtNeg", "NeutNeg", "Unsp"]

# :mode -- sentence type (declarative is the unmarked default, so not listed).
MODE_VALUES = ["Imperative", "Interrogative", "Expressive"]

# :polarity
POLARITY_VALUES = ["-", "+"]

# :degree (Part 3-3-6)
DEGREE_VALUES = ["Intensifier", "Downtoner", "Equal"]

# :ref-person / :ref-number (Part 3-3-5)
PERSON_VALUES = ["1st", "2nd", "3rd", "non-1st", "non-3rd", "inclusive", "exclusive"]
NUMBER_VALUES = ["Singular", "Dual", "Trial", "Paucal", "Plural",
                 "Greater plural", "Non-singular", "Non-plural"]


# ---------------------------------------------------------------------------
# 5. NAMED-ENTITY / ABSTRACT CONCEPT ONTOLOGY  (Part 3-1-2, inherited from AMR)
# ---------------------------------------------------------------------------
# Not exhaustive (the AMR NE ontology has ~150 types); these are the common
# ones plus the special abstract concepts the layers actually produce.

NE_TYPES = {
    "person", "animal", "plant", "thing", "organization", "company",
    "government-organization", "political-party", "school", "university",
    "country", "country-region", "state", "province", "city", "county",
    "continent", "world-region", "location", "facility",
    "nationality", "ethnic-group", "language", "religious-group",
    "publication", "newspaper", "book", "event", "natural-object", "disease",
}

# Special / "non-91" abstract concepts the parser may instantiate as heads.
SPECIAL_CONCEPTS = {
    "name": "wrapper carrying the literal name tokens (:op1 :op2 ...)",
    "ordinal-entity": "carries :value for ordinals (first, 2nd, ...)",
    "temporal-quantity": "amount of time (:quant :unit)",
    "monetary-quantity": "amount of money (:quant :unit)",
    "date-entity": "structured date (:year :month :day ...)",
    "more-than": "comparison wrapper over :op1",
    "less-than": "comparison wrapper over :op1",
}

# "-91" / "-92" reification predicates for non-verbal predication (Part 3-1-1-3).
REIFICATION_PREDICATES = {
    "identity-91":      "equational 'X is Y'",
    "have-mod-91":      "property predication 'X is ADJ'",
    "have-place-91":    "predicative location 'X is at Y'",
    "have-rel-role-91": "relational role 'X is Y's N' (kinship/social)",
    "have-org-role-91": "X holds organizational role (president of ...)",
    "have-quant-91":    "quantity predication",
    "have-condition-91":"conditional predication (if ... then ...)",
    "belong-91":        "predicative possession 'X has Y'",
}


# ---------------------------------------------------------------------------
# Validation / lookup helpers
# ---------------------------------------------------------------------------

# Everything that can legally appear as an EDGE label (relation).
ALL_RELATIONS = set()
ALL_RELATIONS.update(NUMBERED_ROLES, [inverse(r) for r in NUMBERED_ROLES])
ALL_RELATIONS.update(GENERIC_ROLES, [inverse(r) for r in GENERIC_ROLES])
ALL_RELATIONS.update(NONPARTICIPANT_ROLES, [inverse(r) for r in NONPARTICIPANT_ROLES])
ALL_RELATIONS.update(DISCOURSE_RELATIONS)
ALL_RELATIONS.update(TEMPORAL_SUBRELATIONS)
ALL_RELATIONS.update({op(i) for i in range(1, 11)})

# Everything that can legally appear as an inline ATTRIBUTE.
ATTRIBUTE_VALUES = {
    ":aspect": ASPECT_VALUES,
    ":modstr": MODSTR_VALUES,
    ":mode": MODE_VALUES,
    ":polarity": POLARITY_VALUES,
    ":degree": DEGREE_VALUES,
    ":ref-person": PERSON_VALUES,
    ":ref-number": NUMBER_VALUES,
}

_GLOSSES = {}
_GLOSSES.update(GENERIC_ROLES)
_GLOSSES.update(NONPARTICIPANT_ROLES)
_GLOSSES.update(DISCOURSE_RELATIONS)
_GLOSSES.update({r: f"numbered PropBank argument {r}" for r in NUMBERED_ROLES})


def is_relation(label: str) -> bool:
    """True if `label` is a legal UMR edge label (handles -of inverses & :opN)."""
    if label in ALL_RELATIONS:
        return True
    if label.endswith("-of") and label[:-3] in ALL_RELATIONS:
        return True
    if label.startswith(":op") and label[3:].isdigit():
        return True
    return False


def validate_relation(label: str) -> str:
    if not is_relation(label):
        raise ValueError(f"{label!r} is not a UMR relation in the inventory")
    return label


def validate_attribute(attr: str, value: str) -> str:
    allowed = ATTRIBUTE_VALUES.get(attr)
    if allowed is None:
        raise ValueError(f"{attr!r} is not a known UMR attribute")
    if value not in allowed:
        raise ValueError(f"{value!r} not valid for {attr} (allowed: {allowed})")
    return value


def gloss(label: str) -> str:
    return _GLOSSES.get(label, "")


def dump_json() -> str:
    """Serialize the whole inventory (for prompting the LLM engine)."""
    return json.dumps({
        "numbered_roles": NUMBERED_ROLES,
        "generic_roles": GENERIC_ROLES,
        "nonparticipant_roles": NONPARTICIPANT_ROLES,
        "discourse_connectives": DISCOURSE_CONNECTIVE_CONCEPTS,
        "discourse_relations": DISCOURSE_RELATIONS,
        "aspect_values": ASPECT_VALUES,
        "modstr_values": MODSTR_VALUES,
        "mode_values": MODE_VALUES,
        "person_values": PERSON_VALUES,
        "number_values": NUMBER_VALUES,
        "ne_types": sorted(NE_TYPES),
        "reification_predicates": REIFICATION_PREDICATES,
    }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    print(dump_json())
