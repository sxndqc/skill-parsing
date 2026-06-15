"""
Lightweight English NLP scaffolding -- the "code tool" the layers lean on.

The philosophy of this whole project is that humans parse a sentence by
*peeling*: first chop the sentence into clauses, then a clause into a
predicate + phrases, then a phrase into words. None of that peeling needs deep
semantics -- it needs cheap, mechanical signals: where are the verbs, where are
the conjunctions, which token is capitalized, is this word a preposition. That
is exactly what this module provides.

It uses spaCy IF it happens to be installed (better POS / lemmas), but degrades
to a self-contained heuristic tagger so the whole system runs with zero external
dependencies. The heuristic is deliberately shallow: it is meant to *narrow the
search space* for the layer above it, not to be a parser by itself. Real
semantic judgement is the job of the LLM engine; deterministic structure is the
job of this file.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------
# optional spaCy
# --------------------------------------------------------------------------
_NLP = None
def _spacy():
    global _NLP
    if _NLP is None:
        try:
            import spacy
            try:
                _NLP = spacy.load("en_core_web_sm")
            except Exception:
                _NLP = False   # spaCy present but no model
        except Exception:
            _NLP = False
    return _NLP or None


# --------------------------------------------------------------------------
# closed-class lexicons  (the mechanical backbone of the peeling heuristics)
# --------------------------------------------------------------------------
DETERMINERS = {"the", "a", "an", "this", "that", "these", "those", "some",
               "any", "no", "every", "each", "all", "both", "his", "her",
               "its", "their", "my", "your", "our"}
POSSESSIVE_DET = {"his", "her", "its", "their", "my", "your", "our"}

PREPOSITIONS = {"in", "on", "at", "by", "with", "from", "to", "of", "for",
                "about", "into", "onto", "over", "under", "through", "between",
                "among", "during", "before", "after", "until", "till", "since",
                "against", "toward", "towards", "near", "without", "within",
                "upon", "across", "behind", "beside", "beyond", "off"}

COORD = {"and", "or", "but", "nor", "yet", "so"}

# subordinator -> the UMR discourse relation it typically signals
SUBORDINATORS = {
    "because": ":cause", "since": ":cause", "as": ":cause",
    "although": ":concession", "though": ":concession", "whereas": ":concession",
    "even though": ":concession", "despite": ":concession",
    "if": ":condition", "unless": ":condition", "provided": ":condition",
    "when": ":temporal", "while": ":temporal", "after": ":temporal",
    "before": ":temporal", "until": ":temporal", "once": ":temporal",
    "so that": ":purpose", "in order to": ":purpose", "to": ":purpose",
    "lest": ":apprehensive", "instead of": ":substitute", "by": ":manner",
}

# Words/phrases unambiguous enough to trigger a clause split in the heuristic.
# Prepositional homographs (to, by, as, of, since) are deliberately excluded --
# without a real parse they over-split (e.g. "to California"); the predicate
# chunker handles those as PPs and the role layer assigns the nuance.
MULTIWORD_SUBORDINATORS = {
    "so that": ":purpose", "in order to": ":purpose",
    "instead of": ":substitute", "even though": ":concession",
}
CLAUSE_SUBORDINATORS = {
    "because": ":cause", "although": ":concession", "though": ":concession",
    "whereas": ":concession", "if": ":condition", "unless": ":condition",
    "when": ":temporal", "while": ":temporal", "after": ":temporal",
    "before": ":temporal", "until": ":temporal", "lest": ":apprehensive",
}

# Honorifics / titles dropped from the literal :name tokens of a person entity.
TITLES = {"president", "mr", "mrs", "ms", "dr", "prof", "sir", "lord", "lady",
          "king", "queen", "prince", "princess", "senator", "governor",
          "captain", "general", "judge", "saint", "st"}

PRONOUNS = {
    "i":   ("1st", "Singular", "person"), "me": ("1st", "Singular", "person"),
    "we":  ("1st", "Plural", "person"),   "us": ("1st", "Plural", "person"),
    "you": ("2nd", None, "person"),
    "he":  ("3rd", "Singular", "person"), "him": ("3rd", "Singular", "person"),
    "she": ("3rd", "Singular", "person"), "her": ("3rd", "Singular", "person"),
    "they":("3rd", "Plural", "person"),   "them": ("3rd", "Plural", "person"),
    "it":  ("3rd", "Singular", "thing"),
    "this":("3rd", "Singular", "thing"),  "that": ("3rd", "Singular", "thing"),
}

COPULA = {"be", "am", "is", "are", "was", "were", "been", "being"}
AUX = {"will", "would", "shall", "should", "can", "could", "may", "might",
       "must", "do", "does", "did", "have", "has", "had", "going"} | COPULA
NEGATORS = {"not", "n't", "never", "no", "none", "nobody", "nothing"}

# A small high-frequency verb lemma list + irregular past/participle forms so the
# heuristic can spot the predicate without a real tagger.
_VERB_LEMMAS = {
    "go", "come", "see", "take", "give", "get", "make", "find", "think", "say",
    "tell", "ask", "work", "play", "read", "write", "eat", "drink", "buy",
    "sell", "move", "run", "walk", "fly", "drive", "spend", "deny", "grab",
    "defend", "lie", "barbecue", "show", "stamp", "convict", "sentence", "spy",
    "pardon", "taste", "free", "open", "close", "break", "build", "love",
    "hate", "want", "need", "like", "live", "die", "kill", "help", "call",
    "meet", "leave", "arrive", "return", "win", "lose", "send", "bring",
    "remain", "stay", "become", "seem", "look", "feel", "hear", "watch",
    "study", "teach", "learn", "begin", "start", "finish", "stop", "keep",
}
_IRREGULAR = {  # surface form -> lemma
    "went": "go", "gone": "go", "came": "come", "saw": "see", "seen": "see",
    "took": "take", "taken": "take", "gave": "give", "given": "give",
    "got": "get", "gotten": "get", "made": "make", "found": "find",
    "thought": "think", "said": "say", "told": "tell", "wrote": "write",
    "written": "write", "ate": "eat", "eaten": "eat", "drank": "drink",
    "bought": "buy", "sold": "sell", "ran": "run", "drove": "drive",
    "driven": "drive", "spent": "spend", "flew": "fly", "flown": "fly",
    "broke": "break", "broken": "break", "built": "build", "won": "win",
    "lost": "lose", "sent": "send", "brought": "bring", "left": "leave",
    "met": "meet", "became": "become", "began": "begin", "kept": "keep",
    "convicted": "convict", "sentenced": "sentence", "pardoned": "pardon",
    "tasted": "taste", "moved": "move", "returned": "return",
}


# --------------------------------------------------------------------------
# token model
# --------------------------------------------------------------------------
@dataclass
class Tok:
    text: str
    lower: str
    pos: str          # coarse: VERB AUX NOUN PROPN ADJ ADP DET PRON CONJ NUM PUNCT X
    lemma: str
    i: int


def _heuristic_pos(word: str, i: int, words: list[str]) -> tuple[str, str]:
    w = word.lower()
    if re.fullmatch(r"[^\w]+", word):
        return "PUNCT", word
    if re.fullmatch(r"\d[\d,\.]*", word):
        return "NUM", word
    if w in COORD:
        return "CONJ", w
    if w in DETERMINERS:
        return "DET", w
    if w in PREPOSITIONS:
        return "ADP", w
    if w in PRONOUNS:
        return "PRON", w
    if w in NEGATORS:
        return "PART", w
    if w in AUX:
        return "AUX", w
    if w in _IRREGULAR:
        return "VERB", _IRREGULAR[w]
    if w in _VERB_LEMMAS:
        return "VERB", w
    # capitalized non-initial token -> proper noun
    if word[0].isupper() and i > 0:
        return "PROPN", word
    # morphology-based verb guess
    if w.endswith("ing") and len(w) > 4:
        return "VERB", w[:-3]
    if w.endswith("ed") and len(w) > 3:
        return "VERB", w[:-2] if not w.endswith("ied") else w[:-3] + "y"
    if w.endswith("ly") and len(w) > 3:
        return "ADV", w
    if w.endswith(("ous", "ful", "ive", "able", "al", "ic")):
        return "ADJ", w
    return "NOUN", w


def tokenize(text: str) -> list[Tok]:
    nlp = _spacy()
    if nlp is not None:
        doc = nlp(text)
        out = []
        for j, t in enumerate(doc):
            pos = t.pos_
            # normalize spaCy tags to our coarse set
            mapping = {"PROPN": "PROPN", "VERB": "VERB", "AUX": "AUX",
                       "NOUN": "NOUN", "ADJ": "ADJ", "ADP": "ADP", "DET": "DET",
                       "PRON": "PRON", "CCONJ": "CONJ", "SCONJ": "SCONJ",
                       "NUM": "NUM", "PUNCT": "PUNCT", "ADV": "ADV", "PART": "PART"}
            out.append(Tok(t.text, t.text.lower(), mapping.get(pos, "X"),
                           t.lemma_.lower(), j))
        return out
    # heuristic path
    words = re.findall(r"\w+(?:'\w+)?|[^\w\s]", text)
    toks = []
    for i, w in enumerate(words):
        pos, lemma = _heuristic_pos(w, i, words)
        toks.append(Tok(w, w.lower(), pos, lemma, i))
    return toks


def join(toks: list[Tok]) -> str:
    """Re-stringify a token slice with naive spacing."""
    out = ""
    for t in toks:
        if t.pos == "PUNCT" or t.text in {"'s", "n't"}:
            out += t.text
        else:
            out += (" " if out else "") + t.text
    return out.strip()


# --------------------------------------------------------------------------
# LAYER-0 helper:  top-level coordination
# --------------------------------------------------------------------------
def find_top_coordination(text: str) -> Optional[dict]:
    """
    Detect clause-level coordination ('X and Y', 'X or Y', 'X but Y') where both
    sides look like clauses (each contains a verb). Returns the connective concept
    + the coordinand spans, or None. Naive: splits on the FIRST top-level
    coordinator that yields verb-bearing conjuncts.
    """
    toks = tokenize(text)
    depth = 0
    for k, t in enumerate(toks):
        if t.text in "([":
            depth += 1
        elif t.text in ")]":
            depth -= 1
        if depth == 0 and t.pos == "CONJ" and t.lower in {"and", "or", "but"} and 0 < k < len(toks) - 1:
            left = toks[:k]
            right = toks[k + 1:]
            # drop a leading comma on the left conjunct
            if left and left[-1].pos == "PUNCT":
                left = left[:-1]
            if _has_verb(left) and _has_verb(right):
                concept = {"and": "and", "or": "or", "but": "but"}[t.lower]
                return {
                    "concept": concept,
                    "connective": t.lower,
                    "coordinands": [join(left), join(right)],
                }
    return None


def find_subordination(text: str) -> Optional[dict]:
    """
    Detect a subordinate clause introduced by a subordinator. Returns the
    discourse relation, the main-clause span and the subordinate-clause span,
    or None. Handles 'MAIN because SUB', 'Because SUB, MAIN', and a few multiword
    subordinators. Only unambiguous subordinators trigger a split, and both sides
    must contain a verb (this guards PP homographs like 'before noon').
    """
    toks = tokenize(text)
    low = [t.lower for t in toks]

    # 1. multiword subordinators ("so that", "in order to", ...)
    for k in range(1, len(toks) - 1):
        for n in (3, 2):
            phrase = " ".join(low[k:k + n])
            if phrase in MULTIWORD_SUBORDINATORS:
                left, right = toks[:k], toks[k + n:]
                if _has_verb(left) and _has_verb(right):
                    return {"relation": MULTIWORD_SUBORDINATORS[phrase],
                            "subordinator": phrase,
                            "main": join(left).rstrip(","),
                            "subordinate": join(right)}

    # 2. single-word clause subordinator in the middle:  MAIN <sub> SUB
    for k in range(1, len(toks)):
        if low[k] in CLAUSE_SUBORDINATORS:
            left, right = toks[:k], toks[k + 1:]
            if _has_verb(left) and _has_verb(right):
                return {"relation": CLAUSE_SUBORDINATORS[low[k]],
                        "subordinator": low[k],
                        "main": join(left).rstrip(","),
                        "subordinate": join(right)}

    # 3. leading subordinator:  "Because SUB, MAIN"
    if toks and low[0] in CLAUSE_SUBORDINATORS:
        for k, t in enumerate(toks):
            if t.pos == "PUNCT" and t.text == ",":
                left, right = toks[1:k], toks[k + 1:]
                if _has_verb(left) and _has_verb(right):
                    return {"relation": CLAUSE_SUBORDINATORS[low[0]],
                            "subordinator": low[0],
                            "main": join(right),
                            "subordinate": join(left)}
    return None


def _has_verb(toks: list[Tok]) -> bool:
    return any(t.pos in {"VERB", "AUX"} for t in toks)


# --------------------------------------------------------------------------
# LAYER-1 helper:  clause -> predicate + chunks
# --------------------------------------------------------------------------
def chunk_clause(text: str) -> dict:
    """
    Split a single clause into: the main predicate, the subject NP, and the
    post-verbal chunks (objects / PPs / adverbs), each tagged with a relation
    *hint* and an expansion category. The relation hints are intentionally just
    hints -- the ROLE layer makes the final call.
    """
    toks = [t for t in tokenize(text) if t.pos != "PUNCT" or t.text not in {".", "?", "!"}]
    neg = any(t.lower in NEGATORS for t in toks)
    mode = "Imperative" if _looks_imperative(toks) else (
        "Interrogative" if text.strip().endswith("?") else None)

    vi = _main_verb_index(toks)
    if vi is None:
        return {"predicate": None, "is_verbal": False, "subject": text,
                "chunks": [], "neg": neg, "mode": mode}

    verb = toks[vi]
    is_copula = verb.lower in COPULA or verb.lemma == "be"
    # subject = pre-verbal material minus auxiliaries, negators and particles
    subject_toks = [t for t in toks[:vi]
                    if t.pos not in {"AUX", "PART"} and t.lower not in NEGATORS]
    after = toks[vi + 1:]
    # skip auxiliaries / negation / participle chains right after the finite verb
    while after and after[0].pos in {"AUX", "PART"} or (after and after[0].lower in NEGATORS):
        after = after[1:]
    # if the "verb" was actually an auxiliary, the real predicate is next
    if verb.pos == "AUX" and after and after[0].pos == "VERB":
        verb = after[0]
        after = after[1:]
        is_copula = verb.lower in COPULA or verb.lemma == "be"

    chunks = _split_postverbal(after)
    subj = join(subject_toks).strip()
    return {
        "predicate": verb.lemma,
        "predicate_surface": verb.text,
        "is_verbal": not is_copula,
        "is_copula": is_copula,
        "subject": subj if subj else None,
        "chunks": chunks,
        "neg": neg,
        "mode": mode,
    }


def _looks_imperative(toks: list[Tok]) -> bool:
    if not toks:
        return False
    first = toks[0]
    return first.pos == "VERB" and first.i == 0 and first.lower not in PRONOUNS


def _main_verb_index(toks: list[Tok]) -> Optional[int]:
    # prefer the first finite VERB; fall back to first AUX/copula (non-verbal pred)
    for i, t in enumerate(toks):
        if t.pos == "VERB":
            return i
    for i, t in enumerate(toks):
        if t.pos == "AUX":
            return i
    return None


def _split_postverbal(toks: list[Tok]) -> list[dict]:
    """Greedy chunker: a bare NP becomes a candidate object; a PP becomes a
    prep-governed modifier; an adverb becomes a manner/temporal modifier."""
    chunks = []
    i = 0
    first_np = True
    while i < len(toks):
        t = toks[i]
        if t.pos == "ADP":
            prep = t.lower
            j = i + 1
            np = []
            while j < len(toks) and toks[j].pos not in {"ADP", "CONJ"}:
                np.append(toks[j])
                j += 1
            chunks.append({
                "text": join(np), "prep": prep,
                "relation_hint": _prep_relation(prep, np),
                "category": "entity",
            })
            i = j
        elif t.pos == "ADV":
            chunks.append({"text": t.text, "prep": None,
                           "relation_hint": ":manner", "category": "leaf"})
            i += 1
        elif t.lower in _TIME_WORDS:
            # a bare time word ("today", "yesterday") is its own temporal modifier,
            # never swallowed into an adjacent object NP
            chunks.append({"text": t.text, "prep": None,
                           "relation_hint": ":temporal", "category": "leaf"})
            i += 1
        elif t.pos in {"NOUN", "PROPN", "PRON", "DET", "NUM", "ADJ"}:
            np = []
            while (i < len(toks)
                   and toks[i].pos in {"NOUN", "PROPN", "PRON", "DET", "NUM", "ADJ"}
                   and toks[i].lower not in _TIME_WORDS):
                np.append(toks[i])
                i += 1
            hint = ":ARG1" if first_np else ":ARG2"
            first_np = False
            chunks.append({"text": join(np), "prep": None,
                           "relation_hint": hint, "category": "entity"})
        else:
            i += 1
    return chunks


def _prep_relation(prep: str, np: list[Tok]) -> str:
    if prep in {"in", "on", "at", "near", "behind", "beside", "across", "upon"}:
        return ":temporal" if _is_timeish(np) else ":place"
    if prep in {"with"}:
        return ":companion"
    if prep in {"by"}:
        return ":manner"
    if prep in {"from"}:
        return ":source"
    if prep in {"to", "into", "onto", "toward", "towards"}:
        return ":goal"
    if prep in {"for"}:
        return ":purpose"
    if prep in {"during", "before", "after", "until", "since"}:
        return ":temporal"
    if prep in {"of"}:
        return ":poss"
    return ":other"


_TIME_WORDS = {"today", "yesterday", "tomorrow", "now", "week", "month", "year",
               "day", "morning", "evening", "night", "hour", "minute", "monday",
               "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
def _is_timeish(np: list[Tok]) -> bool:
    return any(t.lower in _TIME_WORDS for t in np)


# --------------------------------------------------------------------------
# LAYER-3 helper:  noun phrase internals + named entities
# --------------------------------------------------------------------------
def named_entity(span: str) -> Optional[dict]:
    """If the span is (mostly) a proper name, return its NE type + name tokens.

    Capitalization is read off the surface, not the POS tag, so a span-initial
    proper noun ("Edmund Pope") is not lost to the sentence-initial-capital
    ambiguity. The heuristic fires only when every CONTENT token is either
    capitalized or a recognized title.
    """
    toks = tokenize(span)
    content = [t for t in toks if t.pos not in {"PUNCT", "DET"}]
    if not content:
        return None
    cap = [t for t in content
           if t.text[:1].isupper() and t.text[:1].isalpha()]
    titles = [t for t in content if t.lower in TITLES]
    # require the capitalized tokens to cover all the content (allowing titles)
    if len(cap) < 1 or len(cap) + len([t for t in titles if not t.text[:1].isupper()]) < len(content):
        return None
    name_tokens = [t.text for t in cap if t.lower not in TITLES]
    if not name_tokens:
        return None
    ne_type = _guess_ne_type(name_tokens)
    return {"ne_type": ne_type, "name_tokens": name_tokens}


_KNOWN_COUNTRIES = {"Russia", "America", "Germany", "China", "France", "Japan",
                    "Canada", "Mexico", "Brazil", "India", "England", "Spain"}
_KNOWN_STATES = {"California", "Washington", "Texas", "Florida", "Oregon"}
def _guess_ne_type(name_tokens: list[str]) -> str:
    joined = " ".join(name_tokens)
    if joined in _KNOWN_COUNTRIES:
        return "country"
    if joined in _KNOWN_STATES:
        return "state"
    if any(tok in _KNOWN_COUNTRIES for tok in name_tokens):
        return "country"
    # default: a multi-token capitalized string is most often a person
    return "person"


def noun_phrase_parts(span: str) -> dict:
    """Decompose a common-noun NP into head + modifiers, each with a relation
    hint for the ROLE layer to confirm."""
    toks = tokenize(span)
    pron = pronoun(span)
    if pron:
        return {"is_pronoun": True, **pron, "head": pron["concept"], "mods": []}

    # head noun = last NOUN/PROPN; else last token
    head_i = None
    for i in range(len(toks) - 1, -1, -1):
        if toks[i].pos in {"NOUN", "PROPN"}:
            head_i = i
            break
    if head_i is None:
        head_i = len(toks) - 1

    head = toks[head_i].lemma if toks else span
    number = "Plural" if _is_plural(toks[head_i].text) else None
    mods = []
    for i, t in enumerate(toks):
        if i == head_i:
            continue
        if t.pos == "ADJ":
            mods.append({"text": t.text, "relation_hint": ":mod", "category": "leaf"})
        elif t.pos == "NUM":
            mods.append({"text": t.text, "relation_hint": ":quant", "category": "value"})
        elif t.lower in POSSESSIVE_DET:
            mods.append({"text": t.text, "relation_hint": ":poss", "category": "entity"})
        elif t.pos in {"NOUN", "PROPN"} and i < head_i:
            mods.append({"text": t.text, "relation_hint": ":mod", "category": "leaf"})
        # bare determiners (the/a) carry no UMR node
    return {"is_pronoun": False, "head": head, "ref_number": number, "mods": mods}


def _is_plural(word: str) -> bool:
    w = word.lower()
    return w.endswith("s") and not w.endswith("ss") and len(w) > 3 and w not in {"its"}


def pronoun(span: str) -> Optional[dict]:
    w = span.strip().lower()
    if w in PRONOUNS:
        person, number, concept = PRONOUNS[w]
        out = {"concept": concept, "ref_person": person}
        if number:
            out["ref_number"] = number
        return out
    return None
