"""Base de données JSON : fusion des sources, dédoublonnage, rectificatifs, historique des modifications.

data/notices.json  — liste des opportunités (une par procédure, toutes sources confondues)
data/runs.json     — journal des exécutions (durée, erreurs, dernière exécution réussie)
Les statuts/notes saisis dans le tableau de bord sont stockés dans le navigateur et indexés par 'id',
qui ne change jamais : ils sont donc conservés à chaque actualisation.
"""
import json
from datetime import date
from pathlib import Path

from .text import jaccard, normalize, title_tokens

TRACKED_FIELDS = ["title", "buyer", "dl", "value", "type", "lots"]
SOURCE_KEYS = ["source", "source_id", "url", "pub", "type", "type_label", "family", "fetched_at"]


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")
    tmp.replace(p)


def _days_between(a, b):
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return 9999


class Store:
    def __init__(self, notices):
        self.notices = notices
        self.by_id = {}
        self.uid_index = {}
        self.uuid_index = {}
        for n in notices:
            self._index(n)

    def _index(self, n):
        self.by_id[n["id"]] = n
        for s in n.get("sources", []) + n.get("corrigenda", []):
            self.uid_index[f"{s['source']}:{s['source_id']}"] = n["id"]
        for u in n.get("uuids", []):
            self.uuid_index.setdefault(u, n["id"])

    # ---------- recherche de correspondances ----------
    def _match_uuid(self, rec):
        cands = ([rec["procedure_id"]] if rec.get("procedure_id") else []) + rec.get("uuids", [])
        for u in cands:
            if u in self.uuid_index:
                return self.by_id[self.uuid_index[u]]
        return None

    def _match_fuzzy(self, rec, min_title=0.75, max_days=30, other_source_only=True):
        tt = title_tokens(rec.get("title"))
        bt = title_tokens(rec.get("buyer"))
        best, best_s = None, 0
        for n in self.notices:
            if other_source_only and any(s["source"] == rec["source"] for s in n.get("sources", [])):
                continue
            if _days_between(n.get("pub"), rec.get("pub")) > max_days:
                continue
            ts = jaccard(tt, title_tokens(n.get("title")))
            bs = jaccard(bt, title_tokens(n.get("buyer"))) if bt else 0
            if ts >= min_title and (bs >= 0.5 or not bt):
                if ts + bs > best_s:
                    best, best_s = n, ts + bs
        return best

    def _find_parent_for_corr(self, rec):
        for lid in rec.get("linked_ids", []):
            oid = self.uid_index.get(f"{rec['source']}:{lid}")
            if oid:
                return self.by_id[oid]
        n = self._match_uuid(rec)
        if n:
            return n
        tt = title_tokens(rec.get("title"))
        bt = title_tokens(rec.get("buyer"))
        for n in self.notices:
            if n.get("type") == "corr":
                continue
            if jaccard(tt, title_tokens(n.get("title"))) >= 0.6 and jaccard(bt, title_tokens(n.get("buyer"))) >= 0.5 \
                    and _days_between(n.get("pub"), rec.get("pub")) <= 180:
                return n
        return None

    # ---------- mise à jour ----------
    @staticmethod
    def _src(rec):
        return {k: rec.get(k) for k in SOURCE_KEYS}

    def _log_change(self, n, field, old, new, run_id, via):
        if old == new or new in (None, "", []):
            return False
        n.setdefault("changes", []).append({"at": run_id, "field": field, "old": old, "new": new, "via": via})
        n["changes"] = n["changes"][-30:]
        n[field] = new
        n["last_changed"] = run_id
        return True

    def _new_notice(self, rec, run_id, origin):
        n = {
            "id": rec["uid"],
            "origin": origin,
            "src": rec["source"],
            "url": rec["url"],
            "title": rec["title"], "buyer": rec["buyer"], "country": rec["country"],
            "pub": rec["pub"], "dl": rec["dl"], "type": rec["type"], "type_label": rec.get("type_label"),
            "cpv": rec.get("cpv") or [], "value": rec.get("value"),
            "description": rec.get("description") or "", "lots": rec.get("lots"),
            "procedure_id": rec.get("procedure_id"), "uuids": sorted(set(rec.get("uuids") or [])),
            "family": rec.get("family"), "procedure_label": rec.get("procedure_label"),
            "sources": [self._src(rec)], "corrigenda": [],
            "first_seen": run_id, "last_seen": run_id, "last_changed": run_id, "changes": [],
            "matched_queries": rec.get("matched_queries", []),
        }
        if rec.get("note"):
            n["manual_note"] = rec["note"]
        return n

    def _enrich(self, n, rec):
        for c in rec.get("cpv") or []:
            if c not in n["cpv"]:
                n["cpv"].append(c)
        for f in ("value", "lots", "description", "procedure_id", "family", "procedure_label"):
            if not n.get(f) and rec.get(f):
                n[f] = rec[f]
        n["uuids"] = sorted(set(n.get("uuids", [])) | set(rec.get("uuids") or []))
        for q in rec.get("matched_queries", []):
            if q not in n.setdefault("matched_queries", []):
                n["matched_queries"].append(q)

    def upsert(self, rec, run_id, origin="auto"):
        """Ajoute ou met à jour un enregistrement de source. Renvoie 'new' | 'updated' | 'same' | 'merged' | 'corr' | 'corr_new'."""
        uid = rec["uid"]
        # 1. déjà connu (même source, même identifiant)
        if uid in self.uid_index:
            n = self.by_id[self.uid_index[uid]]
            n["last_seen"] = run_id
            if origin == "auto" and n.get("origin") == "manual":
                n["origin"] = "manual+auto"  # saisie manuelle confirmée par la collecte officielle
            is_primary = n["sources"] and f"{n['sources'][0]['source']}:{n['sources'][0]['source_id']}" == uid
            for s in n["sources"] + n["corrigenda"]:
                if f"{s['source']}:{s['source_id']}" == uid:
                    s.update(self._src(rec))
            changed = False
            if is_primary:
                for f in TRACKED_FIELDS:
                    changed |= self._log_change(n, f, n.get(f), rec.get(f), run_id, "mise à jour " + rec["source"])
            self._enrich(n, rec)
            self._index(n)
            return "updated" if changed else "same"

        # 2. rectificatif → rattachement à l'avis initial
        if rec["type"] == "corr":
            parent = self._find_parent_for_corr(rec)
            if parent:
                parent["corrigenda"].append({**self._src(rec), "title": rec["title"], "dl": rec.get("dl")})
                parent["last_corrigendum"] = rec.get("pub")
                parent["last_seen"] = run_id
                if rec.get("dl"):
                    self._log_change(parent, "dl", parent.get("dl"), rec["dl"], run_id, "rectificatif " + uid)
                parent["last_changed"] = run_id
                self._enrich(parent, rec)
                self._index(parent)
                return "corr"

        # 3. même procédure publiée sur une autre source (BOAMP ↔ TED)
        dup = self._match_uuid(rec) or self._match_fuzzy(rec)
        if dup and rec["type"] != "corr":
            dup["sources"].append(self._src(rec))
            dup["last_seen"] = run_id
            if rec["type"] == "award" and dup.get("type") != "award":
                dup["award_published"] = rec.get("pub")
                dup["last_changed"] = run_id
            self._enrich(dup, rec)
            self._index(dup)
            return "merged"

        # 4. nouvel avis
        n = self._new_notice(rec, run_id, origin)
        self.notices.append(n)
        self._index(n)
        return "corr_new" if rec["type"] == "corr" else "new"

    def link_awards_to_calls(self):
        """Relie chaque award à l'appel d'offres le plus probable (même acheteur + titre similaire)."""
        awards = [n for n in self.notices if n["type"] == "award"]
        calls = [n for n in self.notices if n["type"] in ("call", "prior")]
        for aw in awards:
            if aw.get("related_call"):
                continue  # déjà relié
            # 1. par procedure_id / UUID
            best, best_s = None, 0
            if aw.get("procedure_id"):
                for c in calls:
                    if c.get("procedure_id") and c["procedure_id"] == aw["procedure_id"]:
                        best = c
                        break
            if not best:
                common_uuids = set(aw.get("uuids", []))
                if common_uuids:
                    for c in calls:
                        if common_uuids & set(c.get("uuids", [])):
                            best = c
                            break
            # 2. par fuzzy match titre + acheteur (intra-source aussi)
            if not best:
                att = title_tokens(aw.get("title"))
                abt = title_tokens(aw.get("buyer"))
                for c in calls:
                    if _days_between(c.get("pub"), aw.get("pub")) > 365:
                        continue
                    ts = jaccard(att, title_tokens(c.get("title")))
                    bs = jaccard(abt, title_tokens(c.get("buyer"))) if abt else 0
                    score = ts * 0.6 + bs * 0.4
                    if ts >= 0.4 and bs >= 0.5 and score > best_s:
                        best, best_s = c, score
            if best:
                aw["related_call"] = best["id"]
                best.setdefault("related_award", aw["id"])
                # Propager les winners et la date d'attribution
                if aw.get("winners") and not best.get("winners"):
                    best["winners"] = aw["winners"]
                if not best.get("award_published"):
                    best["award_published"] = aw.get("pub")

    def remove(self, nid):
        n = self.by_id.pop(nid, None)
        if n:
            self.notices.remove(n)
            for k in [k for k, v in self.uid_index.items() if v == nid]:
                del self.uid_index[k]
            for k in [k for k, v in self.uuid_index.items() if v == nid]:
                del self.uuid_index[k]


def manual_to_record(m):
    """Convertit une saisie de data/manual_notices.json en enregistrement de source."""
    src = m.get("source") or "MANUEL"
    sid = m.get("source_id") or m.get("id")
    return {
        "uid": f"{src}:{sid}", "source": src, "source_id": sid,
        "url": m.get("url") or "", "title": m.get("title") or "", "buyer": m.get("buyer") or "",
        "country": m.get("country") or "FRA", "pub": m.get("pub"), "dl": m.get("dl"),
        "type": m.get("type") or "call", "type_label": "Saisie manuelle", "family": None,
        "cpv": m.get("cpv") or [], "value": m.get("value"), "description": m.get("description") or "",
        "lots": m.get("lots"), "procedure_id": None, "uuids": [], "linked_ids": [],
        "fetched_at": None, "matched_queries": ["saisie manuelle"], "note": m.get("note"),
    }


def normalize_buyer_for_display(s):
    return normalize(s)
