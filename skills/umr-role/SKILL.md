---
name: umr-role
description: >
  The relation-judgement layer of UMR parsing. Given a head concept and ONE of
  its bracketed children (an argument or a modifier phrase), decide the exact UMR
  edge label that connects them: a participant role (:ARG0..:ARG5, or the generic
  :actor/:undergoer/:theme/:experiencer/:recipient/:instrument/:goal/:source...)
  for core arguments, or a non-participant relation (:mod/:poss/:part-of/:quant/
  :place/:temporal/:manner/:purpose/:cause...) for modifiers. Invoked once per
  edge, after a bracketing layer (umr-predicate or umr-entity) proposes a hint.
---

# umr-role — judge the relation on a single edge

The bracketing layers cut the sentence into a head and its phrases. They do not
know *how* each phrase relates to the head — they only guess. You decide. This is
the step the human annotator agonizes over: "is that 'with a knife' an
`:instrument` or a `:companion`? is 'of the king' a `:poss` or a `:part-of`?"

You judge **one edge at a time**. You are given the head concept, the head's
surface text, the child's surface text, the child's category (entity / clause /
leaf / value), and the bracketing layer's `relation_hint`. Return the single best
label.

## Decision procedure

1. **Is the child a core participant or a peripheral modifier?**
   A participant is required by the head's frame (who did it, to what, to/for
   whom). A modifier sets the scene (when, where, how, why, whose).

2. **Core participant → pick a role.**
   - If the head is a verb with a PropBank frame, use **numbered** roles:
     `:ARG0` = proto-agent (doer/causer), `:ARG1` = proto-patient (thing
     affected/created/moved), `:ARG2` = instrument/beneficiary/attribute/end
     state, `:ARG3`/`:ARG4` = start/end points, etc.
   - If there is no frame (or you are annotating a language without frame files),
     use **generic** roles: `:actor`, `:undergoer`, `:theme`, `:experiencer`,
     `:stimulus`, `:recipient`, `:goal`, `:source`, `:instrument`, `:companion`,
     `:force`, `:causer`, `:material`, `:affectee`.
   - Pick numbered *or* generic consistently for a given predicate; do not mix.

3. **Peripheral modifier → pick a non-participant relation.**
   - location → `:place`; time/when → `:temporal`; duration → `:duration`;
     frequency → `:frequency`
   - how → `:manner`; with-whom → `:companion`; with-what → `:instrument`
   - why/goal-of-agent → `:purpose`; because → `:cause`; if → `:condition`;
     although → `:concession`
   - whose → `:poss`; part/whole → `:part-of` / `:consist-of`; how-many →
     `:quant`; what-kind → `:mod`; named → `:name`; KB id → `:wiki`
   - genuinely none of the above → `:other`

4. **Disambiguation cheatsheet** (the cases that actually bite):
   - `:instrument` vs `:companion`: a tool you *use* vs an entity that *acts
     alongside* you. "cut with a knife" = `:instrument`; "came with Sherry" =
     `:companion`.
   - `:poss` vs `:part-of`: alienable ownership vs an integral part. "the king's
     crown" = `:poss`; "the leg of the table" = `:part-of`.
   - `:place` vs `:temporal`: a location vs a time. "in Russia" = `:place`; "in
     2001" = `:temporal`.
   - `:goal` vs `:recipient`: spatial endpoint vs animate receiver. "flew to the
     base" = `:goal`; "gave it to her" = `:recipient`.
   - `:mod` vs `:ARG1-of`: a simple adjective (`:mod`) vs a reduced/relative
     clause that should reify to a predicate (`:ARG1-of (... )`).

The `relation_hint` from the bracketing layer is a starting point, not an order.
Override it whenever your judgement differs.

## Code tool

`scripts/umr_role.py` exposes `run(span, context)` where `context` carries
`head_concept`, `head_text`, `child_text`, `category`, `relation_hint`. It
validates a candidate against `tools/umr_inventory` and applies the
disambiguation rules above mechanically (time-vs-place by lexical cues,
of-phrase → poss, adjective → mod, numeral → quant). It guarantees the returned
label is in the legal inventory.

```bash
python skills/umr-role/scripts/umr_role.py --head taste-01 --child "today" --hint :temporal
```

## Output contract

```json
{ "relation": ":temporal", "trace": "peripheral time phrase 'today' -> :temporal" }
```

Return exactly one `relation`. It MUST be a label present in the UMR inventory.

## Learned corrections

Human-recorded fixes for this layer live in `skills/umr-role/heuristics.jsonl`
and OVERRIDE the procedure above. When present they are passed to you as a
"LEARNED CORRECTIONS" block — apply them verbatim, they reflect a human's review.
Record a new one (applies to mock and claude alike, from the next parse):

    python correct.py role --head give-01 --child "her friend" --relation :recipient --note "animate receiver"
