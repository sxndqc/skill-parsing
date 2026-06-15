---
name: umr-entity
description: >
  The innermost peel of UMR parsing -- noun-phrase internals. Given an argument
  span that is nominal, decide what it is: a named entity (-> a typed node like
  person / country / city carrying a (name ...) constant and a :wiki link), a
  pronoun (-> person/thing with :ref-person / :ref-number), or a common noun with
  internal modifiers (head noun + :mod adjectives, :poss possessors, :quant
  numerals, :part-of / relative clauses). Emits the head concept and the
  sub-phrases, which recurse. Use when a phrase has been bracketed as an entity.
---

# umr-entity — split the phrase into words

A noun phrase is itself a little tree. "the rare form of bone cancer", "Russian
President Vladimir Putin", "his wife Sherry" — each has a head and modifiers that
relate to it. Your job is the same peeling, one level smaller: name the head,
detect a named entity, set the reference features, and hand the modifiers down
(their edge labels are decided by `umr-role`, exactly like verb arguments).

## The three cases

1. **Named entity** (proper name dominates the phrase). Emit a *typed* node, not
   the literal words:
   - choose the type from the AMR/UMR ontology: `person`, `country`, `state`,
     `city`, `organization`, `company`, `nationality`, `language`, `disease`, …
   - attach the literal tokens under `:name` as a `name` node:
     `:name (n / name :op1 "Vladimir" :op2 "Putin")`
   - attach `:wiki "Title"` when you know the KB entry, else `:wiki "-"`.
   - titles/roles ("President", "Russian") become *modifiers* on the entity
     (often via `have-org-role-92` / `:mod` of a `nationality`), not part of the
     name.

2. **Pronoun**. Emit `person` (he/she/they/I/we/you) or `thing` (it/this) with:
   - `:ref-person` ∈ {1st, 2nd, 3rd, …}
   - `:ref-number` ∈ {Singular, Dual, Plural, …}
   No children. (Coreference to the actual referent is a *document-level* job;
   leave it.)

3. **Common noun**. Head concept = the noun's lemma (singular). Then bracket the
   modifiers, each `relation: null` + a `relation_hint`:
   - adjective / classifier noun → `:mod` (leaf)
   - possessive determiner / 's / "of X" → `:poss` (entity, recurses)
   - numeral → `:quant` (value)
   - "of"-phrase that is an integral part → `:part-of`
   - relative clause / reduced participle → `expand_as: "clause"` (reifies to a
     predicate via `:ARG0-of` / `:ARG1-of`)
   Set `:ref-number Plural` from plural morphology; `:ref-number Singular` is
   usually left implicit unless contrastive.

## Code tool

`scripts/umr_entity.py` wraps `tools/nlp_tools.named_entity`, `pronoun`, and
`noun_phrase_parts`. It detects capitalized name spans (with a small gazetteer
for country/state typing), reads pronoun features off a closed list, and splits a
common NP into head + modifier hints. Use its decomposition; upgrade the NE type
and add `:wiki` from your own world knowledge.

```bash
python skills/umr-entity/scripts/umr_entity.py "Russian President Vladimir Putin"
python skills/umr-entity/scripts/umr_entity.py "the rare form of bone cancer"
python skills/umr-entity/scripts/umr_entity.py "they"
```

## Output contract

Named entity:
```json
{
  "concept": "person",
  "node_type": "entity",
  "attributes": [],
  "children": [
    {"relation": ":name", "text": "Vladimir Putin", "expand_as": "name"},
    {"relation": ":wiki", "text": "Vladimir_Putin", "expand_as": "string"}
  ],
  "trace": "named entity -> person with name node"
}
```

Common noun:
```json
{
  "concept": "form",
  "node_type": "entity",
  "attributes": [],
  "children": [
    {"relation": null, "relation_hint": ":mod",  "text": "rare", "expand_as": "leaf"},
    {"relation": null, "relation_hint": ":poss", "text": "bone cancer", "expand_as": "entity"}
  ],
  "trace": "common noun 'form' + 1 adj mod + 1 of-phrase"
}
```

`expand_as` terminals the harness understands: `name` (builds a name node with
`:op1..`), `string` (quoted constant, e.g. for `:wiki`), `value` (bare number),
`leaf` (a single modifier word as a node). `entity` and `clause` recurse.

## Learned corrections

Human-recorded fixes live in `skills/umr-entity/heuristics.jsonl` and OVERRIDE
the NE type / head / ref features chosen above. When present they arrive as a
"LEARNED CORRECTIONS" block — apply them. Record a new one:

    python correct.py entity --span "bone cancer" --ne-type disease --wiki "Bone_cancer"
