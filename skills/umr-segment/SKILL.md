---
name: umr-segment
description: >
  Layer 0 of UMR sentence parsing -- the discourse-vs-verb decision. Given a
  sentence or clause span, decide whether its backbone is a SINGLE event (hand
  straight down to the predicate layer) or SEVERAL co-ranked events that must be
  joined by a discourse connective (and / or / but / contrast-91), and if so,
  split the span into its coordinands. Use this first, before any predicate or
  argument analysis.
---

# umr-segment — the outermost peel (discourse or verb?)

You are the first knife. A reader meeting a sentence does not start by hunting
for the verb; they first ask *"is this one thing being said, or several things
joined together?"* That is your only job.

## The decision

Look at the **backbone** of the span — the top-level, co-ranked clauses, ignoring
anything already inside brackets or inside a subordinate clause.

1. **Coordination → build a discourse node.** If the backbone is two or more
   *co-ranked, verb-bearing* clauses joined by a coordinator, emit a connective
   concept and hang each clause off `:op1`, `:op2`, … Each clause is then peeled
   again from the top (it goes back through this same layer).

   | surface coordinator | UMR concept   | gloss                                  |
   |---------------------|---------------|----------------------------------------|
   | and                 | `and`         | conjunctive / additive                 |
   | or                  | `or`          | disjunctive (alternatives)             |
   | but                 | `but`         | adversative                            |
   | (explicit contrast) | `contrast-91` | when "but" is clearly contrastive      |
   | (sequencing)        | `consecutive` | events ordered in time/logic           |
   | (necessity to co-occur) | `additive`| events form one complex figure         |

   When in doubt between fine-grained values, **choose the coarse coordinator**
   (`and`/`or`/`but`). UMR explicitly allows backing off to the higher-level,
   polysemous category.

2. **Single backbone → passthrough.** If there is exactly one main event (the
   common case, *including* sentences with a subordinate clause like
   "…*because* she left"), do **not** build a node here. Return a `passthrough`
   so the same span drops to the predicate layer. Subordinate clauses are *not*
   coordination — in UMR they attach as a relation (`:cause`, `:purpose`,
   `:condition`, `:temporal`, `:concession` …) on the main event, which the
   predicate layer handles.

The litmus test for coordination vs subordination: can you swap the two clauses
without changing meaning and is neither grammatically dependent on the other? If
yes → coordination (build a node). If one clause is introduced by a subordinator
(because, although, if, when, so that, to, lest, instead of) → passthrough.

## Code tool

Call `scripts/umr_segment.py` (or, in the harness, it is called for you). It uses
`tools/nlp_tools.find_top_coordination`, which scans for a *top-level*
coordinator whose left and right sides both contain a verb. Trust its split as a
candidate, but you (the model) make the final call on the connective concept —
the tool only ever proposes the coarse `and`/`or`/`but`.

```bash
python skills/umr-segment/scripts/umr_segment.py "I will go for a walk or play some soccer."
```

## Output contract (a "fragment")

Return ONE JSON object:

```json
{
  "concept": "or",                // connective concept, or null for passthrough
  "node_type": "discourse",       // "discourse" or "passthrough"
  "attributes": [],
  "children": [
    {"relation": ":op1", "text": "I will go for a walk", "expand_as": "clause"},
    {"relation": ":op2", "text": "play some soccer",     "expand_as": "clause"}
  ],
  "trace": "top-level 'or' coordination -> or node"
}
```

Passthrough form:

```json
{
  "concept": null,
  "node_type": "passthrough",
  "children": [{"relation": null, "text": "<the whole span>", "expand_as": "predicate"}],
  "trace": "single backbone event -> predicate layer"
}
```

Rules: every `:opN` child is `expand_as: "clause"` (it re-enters this layer).
Never assign participant roles here — that is two layers down.

## Learned corrections

Human-recorded fixes live in `skills/umr-segment/heuristics.jsonl` and can force
a span NOT to split (false coordination) or override the connective concept. When
present they arrive as a "LEARNED CORRECTIONS" block — apply them. Record one:

    python correct.py segment --span "rock and roll is here to stay" --no-split --note "fixed expression"
