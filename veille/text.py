"""Normalisation de texte et recherche de mots-clés (sans accents, mots entiers)."""
import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(s) -> str:
    """Minuscules, sans accents, apostrophes et tirets unifiés, espaces compactés."""
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    return _WS.sub(" ", s).strip()


_pattern_cache = {}


def kw_pattern(kw: str):
    """Mot-clé -> regex 'mot entier' (évite que 'pret' matche 'interpretariat')."""
    p = _pattern_cache.get(kw)
    if p is None:
        nk = normalize(kw)
        out = []
        for ch in nk:
            if ch == " ":
                out.append(r"[\s\-]+")
            elif ch == "-":
                out.append(r"[\s\-]?")
            elif ch == "'":
                out.append(r"['\s]?")
            else:
                out.append(re.escape(ch))
        body = "".join(out)
        p = re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")
        _pattern_cache[kw] = p
    return p


def find_keywords(text_norm: str, keywords):
    """Retourne les mots-clés présents (texte déjà normalisé)."""
    return [k for k in keywords if kw_pattern(k).search(text_norm)]


def title_tokens(s: str):
    stop = {"de", "des", "du", "la", "le", "les", "et", "pour", "a", "au", "aux", "en", "d", "l",
            "un", "une", "sur", "par", "the", "of", "and", "for", "to", "in", "lot", "marche", "accord", "cadre"}
    return {t for t in re.split(r"[^a-z0-9]+", normalize(s)) if len(t) > 2 and t not in stop}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
