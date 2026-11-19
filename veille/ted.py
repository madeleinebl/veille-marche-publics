"""Collecteur TED — Search API v3 officielle de l'Office des publications de l'UE.

Endpoint : POST https://api.ted.europa.eu/v3/notices/search (recherche anonyme, sans clé).
Syntaxe : requête « expert » TED (classification-cpv IN (...), FT~("..."), publication-date>=AAAAMMJJ).
Pagination : paginationMode=ITERATION + iterationNextToken.
"""
from datetime import datetime, timezone

from .enrich import extract_winners_from_ted
from .http import SourceError, request_json

FIELD_SETS = [
    ["publication-number", "publication-date", "notice-title", "buyer-name", "buyer-country",
     "classification-cpv", "deadline-receipt-tender-date-lot", "notice-type", "form-type",
     "procedure-identifier", "title-lot", "description-lot", "description-proc",
     "estimated-value-proc", "links"],
    ["publication-number", "publication-date", "notice-title", "buyer-name", "buyer-country",
     "classification-cpv", "deadline-receipt-tender-date-lot", "notice-type", "links"],
    ["publication-number", "publication-date", "notice-title", "buyer-name", "buyer-country"],
]
LANG_PREF = ["fra", "FRA", "fr", "eng", "ENG", "en"]


def pick(v, join=" "):
    """Les champs TED multilingues sont {langue: [textes]} ; on préfère le français puis l'anglais."""
    if v is None:
        return ""
    if isinstance(v, dict):
        for lg in LANG_PREF:
            if lg in v:
                return pick(v[lg], join)
        for val in v.values():
            return pick(val, join)
        return ""
    if isinstance(v, list):
        vals = []
        for x in v:
            t = pick(x, join)
            if t and t not in vals:
                vals.append(t)
        return join.join(vals)
    return str(v).strip()


def as_list(v):
    if v is None:
        return []
    if isinstance(v, dict):
        out = []
        for val in v.values():
            out += as_list(val)
        return out
    if isinstance(v, list):
        out = []
        for x in v:
            out += as_list(x)
        return out
    return [str(v)]


def map_type(notice_type, form_type):
    nt = (notice_type or "").lower()
    ft = (form_type or "").lower()
    if nt.startswith("corr") or ft == "change":
        return "corr"
    if nt.startswith("can") or nt.startswith("compl") or ft == "result":
        return "award"
    if nt.startswith("pin") or ft == "planning":
        return "prior"
    if nt.startswith("cn") or nt.startswith("subco") or ft == "competition":
        return "call"
    return "other"


def _num(v):
    for x in as_list(v):
        try:
            return float(str(x).replace(" ", "").replace(",", "."))
        except ValueError:
            continue
    return None


def parse_notice(n, fetched_at):
    pn = pick(n.get("publication-number"))
    if not pn:
        return None
    nt = pick(n.get("notice-type"))
    ft = pick(n.get("form-type"))
    dls = sorted({d[:10] for d in as_list(n.get("deadline-receipt-tender-date-lot")) if d})
    cpvs = []
    for c in as_list(n.get("classification-cpv")):
        c = c[:8]
        if c.isdigit() and c not in cpvs:
            cpvs.append(c)
    countries = [c for c in as_list(n.get("buyer-country")) if c]
    lots_t = pick(n.get("title-lot"), " / ")
    lots_d = pick(n.get("description-lot"), " / ")
    proc = as_list(n.get("procedure-identifier"))
    typ = map_type(nt, ft)
    rec = {
        "uid": f"TED:{pn}",
        "source": "TED",
        "source_id": pn,
        "url": f"https://ted.europa.eu/fr/notice/-/detail/{pn}",
        "title": pick(n.get("notice-title")) or "(titre non renseigné)",
        "buyer": pick(n.get("buyer-name"), " ; "),
        "country": countries[0].upper() if countries else "UNK",
        "pub": (pick(n.get("publication-date")) or "")[:10] or None,
        "dl": dls[0] if dls else None,
        "dl_raw": dls[0] if dls else None,
        "type": typ,
        "type_label": nt or ft or None,
        "family": "TED / JOUE",
        "cpv": cpvs,
        "value": _num(n.get("estimated-value-proc")),
        "description": pick(n.get("description-proc"))[:3000],
        "lots": (lots_t + (" — " + lots_d if lots_d and lots_d != lots_t else ""))[:2000] or None,
        "procedure_id": proc[0].lower() if proc else None,
        "uuids": [p.lower() for p in proc],
        "linked_ids": [],
        "fetched_at": fetched_at,
    }
    # Extract winners for award notices
    if typ == "award":
        winners = extract_winners_from_ted(n)
        if winners:
            rec["winners"] = winners
    return rec


class TedCollector:
    name = "TED"

    def __init__(self, session, cfg, log):
        self.s = session
        self.cfg = cfg
        self.endpoint = cfg["ted"]["endpoint"]
        self.page_size = cfg["ted"].get("page_size", 100)
        self.timeout = cfg.get("request_timeout_s", 60)
        self.max_pages = cfg.get("max_pages_per_query", 20)
        self.log = log
        self.field_set = 0

    def _run(self, query):
        out = []
        token = None
        for _ in range(self.max_pages):
            body = {"query": query, "fields": FIELD_SETS[self.field_set], "limit": self.page_size,
                    "scope": "ALL", "paginationMode": "ITERATION"}
            if token:
                body["iterationNextToken"] = token
            try:
                data = request_json(self.s, "POST", self.endpoint, json_body=body, timeout=self.timeout)
            except SourceError as e:
                # champ inconnu → on réessaie avec un jeu de champs plus réduit
                if "HTTP 400" in str(e) and self.field_set < len(FIELD_SETS) - 1 and not out:
                    self.field_set += 1
                    self.log(f"TED : champs réduits (jeu {self.field_set}) après : {str(e)[:160]}")
                    return self._run(query)
                raise
            notices = data.get("notices")
            if notices is None:
                raise SourceError("format inattendu (pas de 'notices')")
            out += notices
            token = data.get("iterationNextToken")
            if not notices or not token:
                break
        return out

    def collect(self, since):
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        d = since.replace("-", "")
        tail = f" AND publication-date>={d} SORT BY publication-number DESC"
        queries = [
            ("CPV juridiques", "classification-cpv IN (" + " ".join(self.cfg["cpv_legal"]) + ")" + tail),
            ("CPV conseil financier", "classification-cpv IN (" + " ".join(self.cfg["cpv_advisory"]) + ")" + tail),
        ]
        for kw in self.cfg["ted"]["keyword_queries"]:
            queries.append((kw, 'FT~("' + kw.replace('"', "") + '")' + tail))
        by_id = {}
        stats = {"queries": 0, "query_errors": [], "raw_rows": 0}
        for label, q in queries:
            stats["queries"] += 1
            try:
                rows = self._run(q)
            except SourceError as e:
                stats["query_errors"].append(f"{label} : {e}")
                self.log(f"TED ⚠ {label} : {e}")
                continue
            stats["raw_rows"] += len(rows)
            for r in rows:
                rec = parse_notice(r, fetched_at)
                if not rec:
                    continue
                prev = by_id.get(rec["uid"])
                if prev:
                    prev["matched_queries"].append(label)
                else:
                    rec["matched_queries"] = [label]
                    by_id[rec["uid"]] = rec
        if stats["queries"] and len(stats["query_errors"]) == stats["queries"]:
            raise SourceError("toutes les requêtes TED ont échoué : " + stats["query_errors"][0])
        stats["field_set"] = self.field_set
        return list(by_id.values()), stats
