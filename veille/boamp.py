"""Collecteur BOAMP — Open Data officiel de la DILA (Opendatasoft Explore API v2.1).

Source : https://boamp-datadila.opendatasoft.com/explore/dataset/boamp/
Accès : public, sans clé, licence Etalab 2.0. 100 enregistrements max par requête.
Couvre tous les avis publiés au BOAMP (MAPA ≥ 90 k€, procédures formalisées, rectificatifs, attributions).
"""
import json
import re
from datetime import datetime, timezone

from .http import SourceError, request_json

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
IDWEB_RE = re.compile(r"\b\d{2}-\d{3,7}\b")
CPV_RE = re.compile(r"^\d{8}(-\d)?$")

# variantes de syntaxe ODSQL, essayées dans l'ordre ; la première acceptée par l'API est retenue
TEXT_VARIANTS = [
    'search(objet, "{kw}")',
    'objet like "{kw}"',
    '"{kw}"',
]
CPV_VARIANTS = [
    'search(donnees, "{kw}")',
    '"{kw}"',
]


def _type_from_nature(nature, libelle):
    s = f"{nature or ''} {libelle or ''}".upper()
    if "RECTIF" in s or "MODIF" in s:
        return "corr"
    if "ANNUL" in s:
        return "cancel"
    if "ATTRIB" in s or "RESULTAT" in s:
        return "award"
    if "PRE" in s and "INFO" in s or "PREALABLE" in s or "PERIODIQUE" in s:
        return "prior"
    if "APPEL" in s or "MARCHE" in s or "CONCURRENCE" in s:
        return "call"
    return "other"


def _as_obj(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _walk(obj, path=()):
    """Parcourt un JSON imbriqué : (chemin de clés, valeur feuille)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)
    else:
        yield path, obj


def extract_from_donnees(donnees):
    """Extrait CPV, description, lots, valeur, identifiant de procédure (UUID) du champ 'donnees' (eForms/JSON)."""
    obj = _as_obj(donnees)
    out = {"cpv": [], "description": [], "lots": [], "value": None, "procedure_id": None, "uuids": []}
    if obj in (None, ""):
        return out
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    out["uuids"] = sorted({u.lower() for u in UUID_RE.findall(raw)})
    if isinstance(obj, str):
        return out
    for path, val in _walk(obj):
        keys = "/".join(path).lower()
        last = path[-1].lower() if path else ""
        if val is None:
            continue
        sval = str(val).strip()
        if out["procedure_id"] is None and ("contractfolderid" in keys or "procedure" in keys) and UUID_RE.fullmatch(sval):
            out["procedure_id"] = sval.lower()
        if re.search(r"(cpv|classification)", keys) and CPV_RE.match(sval):
            c = sval[:8]
            if c not in out["cpv"]:
                out["cpv"].append(c)
        elif 8 < len(sval) < 3000 and (
                any(t in last for t in ("description", "objet", "intitule", "title", "#text", "desc"))
                or ("lot" in keys and "name" in last)):
            if len(sval) <= 15 and "lot" not in keys:
                continue
            target = out["lots"] if "lot" in keys else out["description"]
            if sval not in target and len(target) < 25:
                target.append(sval)
        if out["value"] is None and re.search(r"(valeur|montant|estimated|amount)", keys) and \
                not re.search(r"(devise|currency|cur|min|unite)", last):
            try:
                num = float(sval.replace(" ", "").replace(",", "."))
                if 1000 <= num <= 5e10:
                    out["value"] = num
            except ValueError:
                pass
    return out


def linked_idwebs(gestion, own):
    """Identifiants d'avis liés (avis initial d'un rectificatif) trouvés dans 'gestion'."""
    obj = _as_obj(gestion)
    found = []
    if obj in (None, ""):
        return found
    if isinstance(obj, str):
        cands = IDWEB_RE.findall(obj)
    else:
        cands = []
        for path, val in _walk(obj):
            keys = "/".join(path).lower()
            if re.search(r"(anterieur|initial|lie|parent|reference|rectif|modif)", keys):
                cands += IDWEB_RE.findall(str(val))
    for c in cands:
        if c != own and c not in found:
            found.append(c)
    return found


def _date(s):
    return str(s)[:10] if s else None


def parse_record(r, fetched_at):
    idweb = r.get("idweb") or r.get("id")
    if not idweb:
        return None
    d = extract_from_donnees(r.get("donnees"))
    nature = r.get("nature")
    libelle = r.get("nature_libelle")
    typ = _type_from_nature(nature, libelle)
    lots = d["lots"]
    return {
        "uid": f"BOAMP:{idweb}",
        "source": "BOAMP",
        "source_id": idweb,
        "url": r.get("url_avis") or f"https://www.boamp.fr/pages/avis/?q=idweb:{idweb}",
        "title": (r.get("objet") or "").strip() or "(objet non renseigné)",
        "buyer": (r.get("nomacheteur") or "").strip(),
        "country": "FRA",
        "pub": _date(r.get("dateparution")),
        "dl": _date(r.get("datelimitereponse")),
        "dl_raw": r.get("datelimitereponse"),
        "type": typ,
        "type_label": libelle or nature,
        "family": r.get("famille_libelle") or r.get("famille"),
        "procedure_label": r.get("procedure_libelle"),
        "departments": r.get("code_departement") if isinstance(r.get("code_departement"), list) else
                       ([r.get("code_departement")] if r.get("code_departement") else []),
        "descripteurs": r.get("descripteur_libelle") if isinstance(r.get("descripteur_libelle"), list) else
                        ([r.get("descripteur_libelle")] if r.get("descripteur_libelle") else []),
        "cpv": d["cpv"],
        "value": d["value"],
        "description": " ".join(d["description"])[:3000],
        "lots": " / ".join(lots)[:2000] if lots else None,
        "procedure_id": d["procedure_id"],
        "uuids": d["uuids"],
        "linked_ids": linked_idwebs(r.get("gestion"), idweb),
        "fetched_at": fetched_at,
    }


class BoampCollector:
    name = "BOAMP"

    def __init__(self, session, cfg, log):
        self.s = session
        self.cfg = cfg
        self.endpoint = cfg["boamp"]["endpoint"]
        self.timeout = cfg.get("request_timeout_s", 60)
        self.max_pages = cfg.get("max_pages_per_query", 20)
        self.log = log
        self._variant = {}  # 'text'/'cpv' -> index de la syntaxe acceptée

    def _query(self, where, kind_label):
        out = []
        offset = 0
        for _ in range(self.max_pages):
            params = {"where": where, "order_by": "dateparution desc", "limit": 100, "offset": offset}
            data = request_json(self.s, "GET", self.endpoint, params=params, timeout=self.timeout)
            res = data.get("results")
            if res is None:
                raise SourceError(f"format inattendu (pas de 'results') pour {kind_label}")
            out += res
            total = data.get("total_count", 0)
            offset += len(res)
            if not res or offset >= total or offset >= 9900:
                break
        return out

    def _search(self, kind, term, since):
        variants = TEXT_VARIANTS if kind == "text" else CPV_VARIANTS
        start = self._variant.get(kind, 0)
        last_err = None
        for i in range(start, len(variants)):
            cond = variants[i].format(kw=term.replace('"', ""))
            where = f"dateparution >= date'{since}' AND ({cond})"
            try:
                rows = self._query(where, f"{kind}:{term}")
                if kind not in self._variant:
                    self._variant[kind] = i
                    self.log(f"BOAMP : syntaxe retenue pour {kind} → {variants[i]}")
                return rows
            except SourceError as e:
                last_err = e
                if "HTTP 400" not in str(e):
                    raise
        raise SourceError(f"aucune syntaxe acceptée pour '{term}' : {last_err}")

    def collect(self, since):
        """since : 'YYYY-MM-DD'. Renvoie (records, stats)."""
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        by_id = {}
        stats = {"queries": 0, "query_errors": [], "raw_rows": 0}
        jobs = [("text", k) for k in self.cfg["boamp"]["keyword_queries"]]
        jobs += [("cpv", c) for c in self.cfg["cpv_legal"] + self.cfg["cpv_advisory"]]
        for kind, term in jobs:
            stats["queries"] += 1
            try:
                rows = self._search(kind, term, since)
            except SourceError as e:
                stats["query_errors"].append(f"{term} : {e}")
                self.log(f"BOAMP ⚠ {term} : {e}")
                continue
            stats["raw_rows"] += len(rows)
            for r in rows:
                rec = parse_record(r, fetched_at)
                if rec:
                    rec.setdefault("matched_queries", [])
                    prev = by_id.get(rec["uid"])
                    if prev:
                        prev["matched_queries"].append(term)
                    else:
                        rec["matched_queries"] = [term]
                        by_id[rec["uid"]] = rec
        if stats["queries"] and len(stats["query_errors"]) == stats["queries"]:
            raise SourceError("toutes les requêtes BOAMP ont échoué : " + stats["query_errors"][0])
        return list(by_id.values()), stats

    def fetch_one(self, idweb):
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data = request_json(self.s, "GET", self.endpoint,
                            params={"where": f'idweb="{idweb}"', "limit": 5}, timeout=self.timeout)
        rows = data.get("results") or []
        recs = [parse_record(r, fetched_at) for r in rows]
        return [r for r in recs if r]
