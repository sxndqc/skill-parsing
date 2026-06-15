# UMR layered parser — peeling a sentence one skill at a time

[![CI](https://github.com/sxndqc/skill-parsing/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndqc/skill-parsing/actions/workflows/ci.yml)

> Recursive-descent semantic parsing into UMR graphs — four composable skills, an
> orchestrating harness (heuristic or LLM-driven), and a human-in-the-loop
> correction loop. MIT licensed.

A small system that parses an English sentence into a
[UMR](https://github.com/umr4nlp/umr-guidelines/blob/master/guidelines.md)
(Uniform Meaning Representation) graph the way a person actually does it:
**by peeling, layer by layer.** You don't meet a sentence and immediately know
its full meaning graph. You ask a sequence of smaller questions:

1. *Is this one thing being said, or several joined together?* → discourse layer
2. *What is the main event, and what phrases hang off it?* → predicate layer
3. *How does each phrase relate to the event?* → relation layer
4. *What's inside each phrase — head noun, modifiers, a name?* → entity layer
   …and each phrase that is itself a clause goes back to step 1.

Each question is a **skill**. A **harness** owns the recursion and calls the
skills in order, gluing their answers into one graph. The guideline reads like a
flat catalogue of categories; this project treats it as what it really is — a
recursive descent from the whole sentence down to individual words.

```
                       ┌─────────────────────────────────────────────┐
   "Sarah moved back   │              harness.py                      │
    to California       │   (worklist recursion + Penman output)      │
    because she        └───────┬───────────┬──────────┬───────────┬──┘
    couldn't find a            │           │          │           │
    job."             umr-segment   umr-predicate  umr-role   umr-entity
                     discourse?→     verb + bracket  which     head noun +
                     and/or/but      aspect/modstr   relation? modifiers / NE
```

> **New here?** The step-by-step user guide (parsing, reading the output, and the
> interactive `review` correction workflow) is in **[docs/USAGE.md](docs/USAGE.md)**.

## The peel, concretely

```
$ python harness.py "Edmund Pope tasted freedom today." --trace

(t / taste-01
    :ARG0 (p / person
        :name (n / name :op1 "Edmund" :op2 "Pope")
        :wiki "-")
    :ARG1 (f / freedom)
    :temporal (t2 / today)
    :aspect Performance
    :modstr FullAff)

PEELING TRACE (each line = one skill call):
[umr-segment] "Edmund Pope tasted freedom today."
    -> single backbone event -> hand to predicate layer
[umr-predicate] "Edmund Pope tasted freedom today."
    -> head taste-01; 3 phrase(s) bracketed; aspect=Performance
  [umr-role] "Edmund Pope"  -> taste-01 --:ARG0--> ...
  [umr-entity] "Edmund Pope" -> named entity -> person with name node
  [umr-role] "freedom"       -> taste-01 --:ARG1--> ...
  [umr-entity] "freedom"     -> common noun 'freedom'
  [umr-role] "today"         -> taste-01 --:temporal--> time word
```

## Layout

```
harness.py                 the orchestrator — owns the recursion, calls skills,
                           prints Penman + the peeling trace
skills/
  umr-segment/             Layer 0: discourse-or-verb (coordination → and/or/but)
  umr-predicate/           Layer 1: find the head verb / reify non-verbal pred,
                           stamp aspect·modstr·mode·polarity, bracket phrases
  umr-role/                Layer 2: judge ONE edge label (participant vs modifier)
  umr-entity/              Layer 3: NP internals — head noun, mods, named entity
    SKILL.md               instructions used by the `claude` engine
    scripts/<skill>.py     the code tool / deterministic `mock` implementation
tools/
  umr_inventory.py         the closed set of legal UMR labels (from the guideline)
  nlp_tools.py             tokenizer + heuristic tagger + chunker (spaCy optional)
  umr_graph.py             Node model + Penman serializer + AMR-style var naming
examples/sample_sentences.txt
tests/test_smoke.py        end-to-end mock run + Penman/label validity
```

## Two engines, one set of skills

Every skill speaks the same JSON **fragment** contract (a head concept, inline
attributes, and a list of child phrases to recurse into). The harness can drive
the skills with either engine:

| engine | how a skill is "called" | needs | use for |
|--------|-------------------------|-------|---------|
| `mock` (default) | runs `skills/<skill>/scripts/<skill>.py:run()` — deterministic heuristics | nothing (offline, zero deps) | demos, tests, seeing the structure |
| `claude` | shells out to the `claude` CLI, feeding it the skill's `SKILL.md` + the span, parsing the returned fragment | `claude` CLI on PATH | real semantic judgement |

```bash
python harness.py "He denied any wrongdoing." --trace            # mock
python harness.py "He denied any wrongdoing." --engine claude     # model judges
python harness.py --file examples/sample_sentences.txt            # batch
python tests/test_smoke.py                                        # smoke tests
```

The two engines are interchangeable because the recursion logic in `harness.py`
never looks at *who* answered — only at the fragment. The `claude` engine even
falls back to the mock heuristic for any single node where the model's reply
can't be parsed, so a parse never hard-fails.

## The fragment contract

What every skill returns (and the harness consumes):

```jsonc
{
  "concept": "taste-01",          // node label, or null for a "passthrough"
  "node_type": "event",           // event | entity | discourse | passthrough
  "attributes": [[":aspect","Performance"], [":modstr","FullAff"]],
  "children": [
    { "relation": null,           // null  => umr-role decides the edge label
      "relation_hint": ":ARG0",   //          (this is the bracketing layer's guess)
      "text": "Edmund Pope",
      "expand_as": "entity" }     // entity|clause|predicate recurse;
  ],                              // name|string|value|leaf are terminals
  "trace": "human-readable note"  // shown in --trace
}
```

`expand_as` terminals the harness resolves without a skill: `name` (builds a
`name` node with `:op1 …`), `string` (a quoted constant, e.g. `:wiki`), `value`
(a bare number, e.g. `:quant`), `leaf` (a single modifier word → its own node).

## Why the code tools?

Parsing is search over a closed vocabulary. The tools keep that search honest:

- **`umr_inventory.py`** — the only labels a skill may emit, distilled from the
  guideline (participant roles, non-participant relations, discourse connectives,
  aspect/modstr/mode/polarity/ref values, the NE ontology). `is_relation()` /
  `validate_attribute()` reject anything off-list, so the model can't invent
  `:totally-made-up`.
- **`nlp_tools.py`** — cheap, mechanical signals (where are the verbs, the
  conjunctions, the capitalized spans, the prepositions). This *narrows the
  search* for each layer; it is not a parser by itself. Uses spaCy if installed,
  otherwise a self-contained heuristic so everything runs with zero deps.
- **`umr_graph.py`** — the structure the layers build up, serialized to standard
  Penman.

## Teaching the parser: learned corrections

The parser is never finished — you correct it. When you look at a parse and see
a mislabel, you record the fix, and it applies from the next parse onward, under
*both* engines. Corrections are stored as **heuristics**, one hand-editable file
per layer:

```
skills/<skill>/heuristics.jsonl
```

Each line is a content-keyed rule — `match` conditions on the runtime context,
`set` the override — so a single correction generalizes to every future sentence
with the same situation, not just the one you were looking at:

```jsonc
{"match": {"head_concept": "give-01", "child_text": "her friend"},
 "set":   {"relation": ":recipient"},
 "note":  "animate receiver, not spatial goal"}
```

The easiest way is the **interactive review** — it walks a parse decision by
decision and lets you fix each one ([full walkthrough](docs/USAGE.md)):

```bash
python correct.py review "She sent the parcel to him."
#   [Enter]=keep   c=correct   s=skip rest   q=quit
```

Or record a single correction directly with the `correct.py` CLI (or edit the
heuristics file by hand):

```bash
# "to her friend" under give-01 is a :recipient, not a :goal
python correct.py role --head give-01 --child "her friend" --relation :recipient \
       --note "animate receiver"

# generalize with a regex over any field (suffix _regex):
python correct.py role --head-regex "give-\d+" --child-regex friend --relation :recipient

# fix a head concept / aspect the heuristic tagger got wrong:
python correct.py predicate --verb-surface barbecued --concept barbecue-01 --aspect Performance

# re-type a named entity the tagger missed:
python correct.py entity --span "bone cancer" --ne-type disease --wiki "Bone_cancer"

# stop a false coordination split:
python correct.py segment --span "rock and roll is here to stay" --no-split

python correct.py list           # review everything learned so far
```

How each engine consults them:

- **mock** — each skill script calls `heuristics.match()` and applies the
  override; a fired correction shows up in `--trace` as
  `[heuristic] <note> -> <result>`.
- **claude** — the rules for that layer are injected into the skill prompt as
  *"LEARNED CORRECTIONS (authoritative … they OVERRIDE your default judgement)"*,
  so the model obeys the same human fixes.

The file is re-read on every call, so a correction takes effect immediately — no
restart, no rebuild. Rules are matched most-specific-first; ties go to the most
recently added. Match keys per layer:

| layer | match keys | typical `set` |
|-------|------------|---------------|
| `umr-segment`   | `span` | `no_split: true`, `connective` |
| `umr-predicate` | `span`, `verb`, `verb_surface`, `concept` | `concept`, `aspect`, `modstr` |
| `umr-role`      | `head_concept`, `head_text`, `child_text`, `category`, `relation_hint` | `relation` |
| `umr-entity`    | `span` | `ne_type`, `name`, `wiki`, `concept`, `head`, `ref_number`, `ref_person` |

(Append `_regex` to any match key to match by regular expression.)

## Honesty about the `mock` engine

The mock engine is a **heuristic demonstrator**, not a gold UMR annotator. With
no real parser it gets simple SVO sentences, coordination, subordination, named
entities, pronouns and PP modifiers right, and it will mislabel hard cases
(shared subjects across conjuncts, control/raising, sense disambiguation, fine
aspect). Its job is to make the *layering and data flow* runnable and inspectable
offline. For real semantic accuracy, use `--engine claude` — the same skills,
judged by the model. Installing spaCy (`pip install spacy && python -m spacy
download en_core_web_sm`) sharpens the mock tagging but is optional.

## Using these as real Claude Code skills

Each `skills/<name>/SKILL.md` is a valid Claude Code skill (name + description
frontmatter). Copy or symlink the `skills/*` directories into `.claude/skills/`
to invoke a single layer interactively, or keep them here and let `harness.py`
drive the whole recursion.
