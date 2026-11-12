"""Turn free text into safe full-text queries: words only, never raw FTS5 operators.

English collections (``porter unicode61``): all words, then any word; words of five or
more letters also match as a prefix, because the stemmer gives "allergy" and "allergic"
different stems, while short words stay exact ("cart" must not match "cartridge").

CJK collections (``trigram``): the tokenizer indexes every three characters, so a run of
three or more characters matches as a substring. Shorter terms (most two-character Chinese
words) cannot use the index and are matched with LIKE. When the exact phrase is absent,
the fallback matches any trigram of the query, so "餐费报销标准" still finds
"餐费的报销标准" (BM25 ranks chunks that share more trigrams first); a last pass matches
any of the short terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_WORDS = 12
MAX_TRIGRAMS = 32
PREFIX_MIN = 5
_WORD = re.compile(r"\w+", re.UNICODE)
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힯]")


@dataclass(frozen=True)
class Pass:
    """One attempt: an FTS5 MATCH expression (or None) plus LIKE terms."""

    match: str | None = None
    like_all: tuple[str, ...] = ()
    like_any: tuple[str, ...] = ()


def words(text: str) -> list[str]:
    found = [w for w in _WORD.findall(text.lower()) if len(w) > 1 or _CJK.match(w)]
    return found[:MAX_WORDS]


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def english_plan(text: str) -> list[Pass]:
    terms = [_quote(w) + ("*" if len(w) >= PREFIX_MIN else "") for w in words(text)]
    if not terms:
        return []
    return [Pass(match=" ".join(terms)), Pass(match=" OR ".join(terms))]


def cjk_plan(text: str) -> list[Pass]:
    found = words(text)
    long = [w for w in found if len(w) >= 3]
    short = tuple(w for w in found if len(w) < 3)
    if not found:
        return []
    if not long:
        return [Pass(like_all=short), Pass(like_any=short)]
    first = Pass(match=" ".join(_quote(w) for w in long), like_all=short)
    grams: list[str] = []
    for w in long:
        pieces = [w[i : i + 3] for i in range(len(w) - 2)] if has_cjk(w) else [w]
        grams.extend(g for g in pieces if g not in grams)
    passes = [first, Pass(match=" OR ".join(_quote(g) for g in grams[:MAX_TRIGRAMS]))]
    return [*passes, Pass(like_any=short)] if short else passes


def plan(text: str, language: str) -> list[Pass]:
    return cjk_plan(text) if language == "cjk" else english_plan(text)
