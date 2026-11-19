"""Enrichissement automatique des avis : extraction du titulaire (attributions),
montant estimé, nombre de lots et critères d'attribution depuis les données BOAMP/TED.

Fonctionne à partir des données déjà collectées (champ 'donnees' BOAMP, champs TED).
Pour les avis d'attribution, extrait le nom du titulaire pour le suivi concurrentiel.
"""
import json
import re

from .text import normalize


# ---------- extraction du titulaire (award notices) ----------

def _walk(obj, path=()):
    """Parcourt récursivement un objet JSON."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)
    else:
        yield path, obj


def extract_winners_from_donnees(donnees_raw):
    """Extrait les noms des titulaires depuis le champ 'donnees' BOAMP (eForms JSON).

    Retourne une liste de dicts : [{"name": "...", "lot": "..."}, ...]
    """
    if not donnees_raw:
        return []
    obj = donnees_raw
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (ValueError, TypeError):
            return _extract_winners_from_text(obj)
    if not isinstance(obj, dict):
        return []

    winners = []
    seen = set()

    for path, val in _walk(obj):
        if val is None:
            continue
        keys = "/".join(path).lower()
        last = path[-1].lower() if path else ""
        sval = str(val).strip()

        # Chercher les noms de titulaires dans les champs pertinents
        if (re.search(r"(titulaire|attributaire|winner|contractor|tenderer|awarded|beneficiary|organization.*name)", keys) and
                re.search(r"(nom|name|official|company|denomination|raison.?sociale)", last) and
                5 < len(sval) < 300 and
                not re.match(r"^[\d\s\-]+$", sval)):
            canon = normalize(sval)
            if canon not in seen and len(canon) > 3:
                seen.add(canon)
                # Essayer de trouver le lot associé
                lot = None
                for pp, pv in _walk(obj):
                    pk = "/".join(pp).lower()
                    if re.search(r"(lot|part)", pk) and re.search(r"(title|intitule|objet)", pp[-1].lower() if pp else ""):
                        if isinstance(pv, str) and 3 < len(pv) < 500:
                            lot = pv.strip()
                            break
                winners.append({"name": sval, "lot": lot})

    return winners


def _extract_winners_from_text(text):
    """Extraction des titulaires depuis du texte brut (fallback)."""
    winners = []
    seen = set()
    patterns = [
        r"(?:titulaire|attributaire)\s*:\s*(.+?)(?:\n|$|;)",
        r"(?:attribu[eé]e?\s+[àa]\s+)(.+?)(?:\n|$|;|\.|,\s*pour)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            name = m.group(1).strip()
            if 3 < len(name) < 300:
                canon = normalize(name)
                if canon not in seen:
                    seen.add(canon)
                    winners.append({"name": name, "lot": None})
    return winners


def extract_winners_from_ted(notice_data):
    """Extrait les noms des titulaires depuis les données brutes TED.

    Les avis d'attribution TED contiennent parfois les noms directement
    dans des champs comme 'winner-name' ou dans les détails.
    """
    winners = []
    seen = set()

    # TED Search API peut retourner winner-name ou contractor-name
    for field in ("winner-name", "contractor-name", "awarded-tenderer-name"):
        val = notice_data.get(field)
        if not val:
            continue
        names = []
        if isinstance(val, dict):
            for lang_vals in val.values():
                if isinstance(lang_vals, list):
                    names.extend(lang_vals)
                elif isinstance(lang_vals, str):
                    names.append(lang_vals)
        elif isinstance(val, list):
            names = val
        elif isinstance(val, str):
            names = [val]

        for name in names:
            name = str(name).strip()
            canon = normalize(name)
            if canon and canon not in seen and len(canon) > 3:
                seen.add(canon)
                winners.append({"name": name, "lot": None})

    return winners


# ---------- enrichissement des métadonnées ----------

def extract_criteria_from_donnees(donnees_raw):
    """Extrait les critères d'attribution depuis le champ 'donnees' BOAMP."""
    if not donnees_raw:
        return []
    obj = donnees_raw
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (ValueError, TypeError):
            return []
    if not isinstance(obj, dict):
        return []

    criteria = []
    seen = set()

    for path, val in _walk(obj):
        keys = "/".join(path).lower()
        last = path[-1].lower() if path else ""
        sval = str(val).strip() if val else ""

        if (re.search(r"(critere|criterion|award.*criter|criter.*attrib)", keys) and
                re.search(r"(name|nom|intitule|description|type)", last) and
                3 < len(sval) < 300):
            canon = normalize(sval)
            if canon not in seen:
                seen.add(canon)
                # Chercher le poids associé
                weight = None
                for pp, pv in _walk(obj):
                    pk = "/".join(pp).lower()
                    if (re.search(r"(poids|weight|ponderation|percentage)", pk) and
                            pp[:-1] == path[:-1]):  # même parent
                        try:
                            weight = float(str(pv).replace(",", ".").replace("%", "").strip())
                        except (ValueError, TypeError):
                            pass
                        break
                criteria.append({"name": sval, "weight": weight})

    return criteria


def extract_lot_count(notice):
    """Déduit le nombre de lots depuis les données disponibles."""
    lots_text = notice.get("lots") or ""

    # Chercher un chiffre explicite
    m = re.search(r"(\d+)\s*lots?", lots_text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Compter les lots séparés par "/"
    if "/" in lots_text:
        return len([p for p in lots_text.split("/") if p.strip()])

    # Champ dédié dans les données
    for key in ("lot_count", "nb_lots"):
        if notice.get(key):
            try:
                return int(notice[key])
            except (ValueError, TypeError):
                pass

    return None


def enrich_notice(notice, raw_data=None):
    """Enrichit un avis avec les métadonnées supplémentaires.

    Args:
        notice: l'avis à enrichir (dict)
        raw_data: données brutes de la source (dict BOAMP ou TED), optionnel

    Returns:
        dict avec les champs enrichis ajoutés/mis à jour
    """
    enriched = {}

    # Nombre de lots
    lot_count = extract_lot_count(notice)
    if lot_count and lot_count > 0:
        enriched["lot_count"] = lot_count

    # Pour les attributions : extraction des titulaires
    if notice.get("type") == "award":
        winners = []
        if raw_data:
            source = notice.get("source") or notice.get("src", "")
            if source == "BOAMP":
                winners = extract_winners_from_donnees(raw_data.get("donnees"))
            elif source == "TED":
                winners = extract_winners_from_ted(raw_data)

        if winners:
            enriched["winners"] = winners

    # Critères d'attribution
    if raw_data and (notice.get("source") or notice.get("src", "")) == "BOAMP":
        criteria = extract_criteria_from_donnees(raw_data.get("donnees"))
        if criteria:
            enriched["criteria"] = criteria

    return enriched


def build_competition_data(notices):
    """Construit les données de suivi concurrentiel à partir des attributions.

    Retourne un dict :
    {
        "winners": {
            "Cabinet X": {"count": 5, "total_value": 1200000, "notices": ["TED:xxx", ...]},
            ...
        },
        "recent_awards": [
            {"id": "...", "title": "...", "buyer": "...", "winners": [...], "pub": "...", "value": ...},
            ...
        ]
    }
    """
    winners_agg = {}
    recent_awards = []

    for n in notices:
        if n.get("type") != "award":
            continue

        award_winners = n.get("winners") or []

        award_entry = {
            "id": n["id"],
            "title": n.get("title", ""),
            "buyer": n.get("buyer", ""),
            "pub": n.get("pub"),
            "value": n.get("value"),
            "winners": [w["name"] for w in award_winners],
            "practices": n.get("practices", []),
        }
        recent_awards.append(award_entry)

        for w in award_winners:
            name = w["name"]
            canon = normalize(name)
            # Regrouper par nom canonique
            if canon not in winners_agg:
                winners_agg[canon] = {
                    "name": name,
                    "count": 0,
                    "total_value": 0,
                    "notices": [],
                    "practices": set(),
                }
            entry = winners_agg[canon]
            entry["count"] += 1
            if n.get("value"):
                entry["total_value"] += n["value"]
            entry["notices"].append(n["id"])
            for p in n.get("practices", []):
                entry["practices"].add(p)

    # Convertir les sets en listes pour JSON
    for entry in winners_agg.values():
        entry["practices"] = sorted(entry["practices"])

    # Trier par nombre de marchés remportés
    sorted_winners = dict(sorted(winners_agg.items(), key=lambda x: -x[1]["count"]))
    recent_awards.sort(key=lambda x: x.get("pub") or "", reverse=True)

    return {
        "winners": sorted_winners,
        "recent_awards": recent_awards[:50],
    }
