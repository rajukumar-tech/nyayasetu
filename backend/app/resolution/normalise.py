"""Name normalisation for Indian names across scripts.

transliterate (Kannada/Devanagari → Latin) → NFC/ASCII fold → strip honorifics →
split aliases (@, urf, alias) → tokens + initials → phonetic key robust to common
spelling variation (Manjunath/Manjunatha, Lakshmi/Laxmi, Gowda/Gouda, Rafiq/Rafeeq).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from indic_transliteration import sanscript

HONORIFICS = {"sri", "shri", "shree", "sree", "smt", "srimati", "shrimati", "mr", "mrs", "ms", "kum", "kumari", "dr",
              "late", "master", "baby", "janab", "sh"}
EXPANSIONS = {"md": "mohammed", "mohd": "mohammed", "mohd.": "mohammed", "mohammad": "mohammed", "muhammad": "mohammed",
              "mahammad": "mohammed", "saiyad": "syed", "sayed": "syed", "sayyed": "syed", "saiyed": "syed"}
SPELLED_INITIALS = {"es": "s", "ar": "r", "ke": "k", "em": "m", "en": "n", "bi": "b", "di": "d", "ji": "j", "pi": "p",
                    "ti": "t", "vi": "v", "si": "c", "el": "l", "eh": "h", "ech": "h"}
ALIAS_SPLIT = re.compile(r"\s*(?:@|\burf\b|\balias\b|\ba/k/a\b|\baka\b|\bur\b)\s*", re.I)
RELATION_SPLIT = re.compile(r"\s+(?:s/o|d/o|w/o|c/o|son of|daughter of|wife of)\s+", re.I)


def script_of(text: str) -> str:
    for ch in text:
        o = ord(ch)
        if 0x0C80 <= o <= 0x0CFF:
            return "kannada"
        if 0x0900 <= o <= 0x097F:
            return "devanagari"
    return "latin"


@lru_cache(maxsize=4096)
def to_latin(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    sc = script_of(text)
    if sc != "latin":
        src = sanscript.KANNADA if sc == "kannada" else sanscript.DEVANAGARI
        text = sanscript.transliterate(text, src, sanscript.ITRANS)
        text = text.replace("M", "n").replace(".n", "n").replace("~N", "n")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


@dataclass
class NormName:
    raw: str
    primary: list[str]                      # tokens of the main name
    aliases: list[list[str]] = field(default_factory=list)
    initials: list[str] = field(default_factory=list)
    relative: list[str] = field(default_factory=list)

    @property
    def full(self) -> str:
        return " ".join(self.primary)

    @property
    def key(self) -> str:
        return phonetic_key(self.full)

    def all_keys(self) -> set[str]:
        keys = {self.key} | {phonetic_key(" ".join(a)) for a in self.aliases}
        keys |= {phonetic_token(t) for t in self.primary + [x for a in self.aliases for x in a] if len(t) > 2}
        return {k for k in keys if k}


def _tokens(s: str) -> list[str]:
    toks = [t for t in re.split(r"[^a-z]+", to_latin(s)) if t]
    out = []
    for i, t in enumerate(toks):
        if t in HONORIFICS:
            continue
        t = EXPANSIONS.get(t, t)
        if i == len(toks) - 1 and t in SPELLED_INITIALS and len(toks) > 1:
            t = SPELLED_INITIALS[t]
        out.append(t)
    return out


def normalise_name(raw: str) -> NormName:
    rel: list[str] = []
    parts = RELATION_SPLIT.split(raw, maxsplit=1)
    if len(parts) == 2:
        raw_name, rel = parts[0], _tokens(parts[1])
    else:
        raw_name = raw
    names = [p for p in ALIAS_SPLIT.split(raw_name) if p.strip()]
    toks = [_tokens(n) for n in names] or [[]]
    primary = toks[0]
    initials = [t for t in primary if len(t) == 1]
    return NormName(raw, primary, toks[1:], initials, rel)


_PHON = [("ksh", "ks"), ("x", "ks"), ("ph", "f"), ("w", "v"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"),
         ("gh", "g"), ("jh", "j"), ("ch", "c"), ("sh", "s"), ("z", "j"), ("q", "k"), ("ck", "k"), ("ee", "i"), ("ii", "i"),
         ("oo", "u"), ("uu", "u"), ("aa", "a"), ("ou", "o"), ("ov", "o"), ("au", "o"), ("ai", "e"), ("ei", "e"),
         ("ay", "e"), ("y", "i"), ("ea", "e"), ("gauda", "goda"), ("govda", "goda")]


@lru_cache(maxsize=8192)
def phonetic_token(t: str) -> str:
    t = to_latin(t)
    t = re.sub(r"[^a-z]", "", t)
    for a, b in _PHON:
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)           # collapse doubles: Rafiq/Raffiq, Shivanna/Shivana
    if len(t) > 3:
        t = re.sub(r"[aue]+$", "", t)          # Manjunatha/Manjunath, Basavaraju/Basavaraj
    return t


def phonetic_key(name: str) -> str:
    toks = [phonetic_token(t) for t in _tokens(name)]
    return " ".join(sorted(t for t in toks if len(t) > 1))  # order-insensitive: "Gowda Suresh" = "Suresh Gowda"
