---
name: umr-predicate
description: >
  Layer 1 of UMR sentence parsing -- predicate identification. Given a SINGLE
  clause (already past the discourse layer), find its head: an eventive predicate
  (a verb -> a PropBank-style sense like taste-01) or a non-verbal predication
  (X is Y -> identity-91, X is ADJ -> have-mod-91, X is at Y -> have-place-91).
  Attach the event attributes (aspect, modal strength, mode, polarity) and chop
  the rest of the clause into the argument/modifier phrases that the next layers
  will label and peel. Use after umr-segment has handed down a single clause.
---

# umr-predicate — find the verb, bracket the phrases

The clause has one backbone event. Your job is to (1) name that event, (2) stamp
it with its grammatical attributes, and (3) **bracket** the surrounding material
into phrases — *without yet labeling the relations*. Labeling is the next layer's
job (`umr-role`); you only cut the clause into a head plus a list of sibling
spans. This mirrors how a person reads: "the verb is X; hanging off it I can see
this chunk, that chunk, and that chunk."

## Step 1 — peel off any subordinate clause

Before finding the head, check for a subordinator (because, although, if, when,
so that, to, lest, instead of, by). In UMR a subordinate clause is **not** part
of the predicate — it attaches as a discourse relation on the main event:

| subordinator              | relation       |
|---------------------------|----------------|
| because / since / as      | `:cause`       |
| so that / in order to / to| `:purpose`     |
| if / unless               | `:condition`   |
| although / though / whereas | `:concession`|
| when / while / after / before / until | `:temporal` |
| by (means)                | `:manner`      |
| lest                      | `:apprehensive`|
| instead of                | `:substitute`  |

Split the clause into MAIN + SUBORDINATE, keep MAIN as your working span, and add
the subordinate clause as a child with that relation and `expand_as: "clause"`.

## Step 2 — identify the head

- **Verbal clause** → concept = lemma + sense suffix, default `-01`
  (e.g. *tasted* → `taste-01`). Pick the more specific sense only if you are
  confident; `-01` is the safe default. `node_type: "event"`.
- **Non-verbal predication** (copula *be*, or none): reify it.
  - X **is** Y (equation)        → `identity-91`  (subject `:ARG1`, complement `:ARG2`)
  - X **is** ADJ (property)       → `have-mod-91`  (subject `:ARG1`, property `:ARG2`)
  - X **is at/in** LOC (location) → `have-place-91`(subject `:ARG1`, place `:ARG2`)
  - X **has** Y (possession)      → `belong-91` / `have-rel-role-91` as appropriate
  `node_type: "event"`, usually `:aspect State`.

## Step 3 — stamp attributes (Part 3-3)

- `:aspect` — coarse values: `State` (be/know/own/property), `Habitual`
  (generics, "used to"), `Activity` (atelic, no endpoint), `Endeavor` (tried,
  atelic+agentive), `Performance` (telic, has a natural endpoint / direct
  object). Default a transitive past-tense action to `Performance`, a copula to
  `State`, a bare intransitive to `Activity`.
- `:modstr` — `FullAff` (asserted, certain) by default; `FullNeg` if negated;
  `PrtAff` for imperatives/futures you are less than certain about; `Unsp` when
  unspecified.
- `:mode` — `Imperative` / `Interrogative` (omit for plain declaratives).
- `:polarity` — `-` when the clause is negated.

## Step 4 — bracket the rest into phrases

Emit one child per phrase you can see hanging off the verb: the subject NP, each
object NP, each PP, each adverbial, each complement/subordinate clause. Give each
a `relation_hint` (your best guess) but leave `relation: null` so `umr-role`
adjudicates it. Set `expand_as`:

- `entity` for a noun phrase (subject, object, PP complement) — peels in umr-entity
- `clause` for a subordinate/complement clause — re-enters umr-segment
- `leaf`  for a single modifier word (an adverb, a particle)
- `value` for a bare number

## Code tool

`scripts/umr_predicate.py` wraps `tools/nlp_tools.find_subordination` +
`chunk_clause`, which find the main verb and greedily bracket the post-verbal
phrases with relation hints (subject→`:ARG0`, first object→`:ARG1`, PP→by
preposition, etc.). Use its bracketing; refine the head sense, aspect and modstr
with your own judgement.

```bash
python skills/umr-predicate/scripts/umr_predicate.py "Edmund Pope tasted freedom today."
```

## Output contract

```json
{
  "concept": "taste-01",
  "node_type": "event",
  "attributes": [[":aspect", "Performance"], [":modstr", "FullAff"]],
  "children": [
    {"relation": null, "relation_hint": ":ARG0", "text": "Edmund Pope", "expand_as": "entity"},
    {"relation": null, "relation_hint": ":ARG1", "text": "freedom",     "expand_as": "entity"},
    {"relation": null, "relation_hint": ":temporal", "text": "today",   "expand_as": "leaf"}
  ],
  "trace": "verbal head taste-01; subject + 1 object + 1 temporal bracketed"
}
```

## Learned corrections

Human-recorded fixes live in `skills/umr-predicate/heuristics.jsonl` and OVERRIDE
the head concept / aspect / modstr chosen above. When present they arrive as a
"LEARNED CORRECTIONS" block — apply them. Record a new one:

    python correct.py predicate --verb-surface barbecued --concept barbecue-01 --aspect Performance --note "fix lemma"
