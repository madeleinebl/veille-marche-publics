"""Score de pertinence — transparent : chaque point est expliqué."""
import json

from . import CONFIG_DIR
from .text import normalize, find_keywords


def load_scoring(path=None):
    with open(path or CONFIG_DIR / "scoring.json", encoding="utf-8") as f:
        return json.load(f)


def _text_of(n):
    parts = [n.get("title"), n.get("description"), n.get("lots"), n.get("buyer")]
    return normalize(" ".join(p for p in parts if p))


def score_notice(n, cfg, cpv_legal, cpv_advisory):
    """Calcule score, priorité, domaines, mots-clés et explication. Ne modifie que les champs de scoring."""
    text = _text_of(n)
    buyer = normalize(n.get("buyer"))
    breakdown = []
    matched = []

    # 1. Signal juridique / conseil
    ls = cfg["legal_signal"]
    legal_pts = 0
    cpvs = [str(c)[:8] for c in (n.get("cpv") or [])]
    cpv_hits_legal = sorted({c for c in cpvs if c in cpv_legal})
    cpv_hits_adv = sorted({c for c in cpvs if c in cpv_advisory})
    if cpv_hits_legal:
        legal_pts += ls["cpv_points"]["legal"]
        breakdown.append({"label": "CPV juridique " + ", ".join(cpv_hits_legal), "points": ls["cpv_points"]["legal"]})
    elif cpv_hits_adv:
        legal_pts += ls["cpv_points"]["advisory"]
        breakdown.append({"label": "CPV conseil " + ", ".join(cpv_hits_adv), "points": ls["cpv_points"]["advisory"]})
    lk = find_keywords(text, ls["keywords"].keys())
    # éviter le double comptage 'juridique' si une expression plus précise est déjà trouvée
    if "juridique" in lk and len([k for k in lk if "juridique" in k]) > 1:
        lk.remove("juridique")
    if lk:
        kw_pts = max(ls["keywords"][k] for k in lk)
        legal_pts += kw_pts
        matched += lk
        breakdown.append({"label": "Mission juridique : " + ", ".join(lk), "points": kw_pts})
    legal_pts = min(legal_pts, ls["cap"])
    if legal_pts and sum(b["points"] for b in breakdown) > legal_pts:
        breakdown.append({"label": "Plafond signal juridique", "points": legal_pts - sum(b["points"] for b in breakdown)})
    has_legal = legal_pts > 0

    # 2. Domaines de pratique
    practices = []
    practice_pts_total = 0
    per_practice = []
    for name, p in cfg["practices"].items():
        hits = find_keywords(text, p["keywords"].keys())
        # supprimer les mots inclus dans une expression plus longue déjà trouvée (ex. 'garantie' dans 'garanties rehaussees')
        hits = [h for h in hits if not any(h != o and normalize(h) in normalize(o) for o in hits)]
        if not hits:
            continue
        pts = min(sum(p["keywords"][h] for h in hits), 25)
        per_practice.append((pts, name, hits))
    per_practice.sort(reverse=True)
    for pts, name, hits in per_practice:
        practices.append(name)
        matched += hits
        practice_pts_total += pts
        breakdown.append({"label": f"{name} : " + ", ".join(hits), "points": pts})
    if practice_pts_total > 50:
        breakdown.append({"label": "Plafond domaines", "points": 50 - practice_pts_total})
        practice_pts_total = 50

    # 3. Acheteur stratégique
    sb = cfg["strategic_buyers"]
    bh = find_keywords(buyer, sb["names"])
    if bh:
        breakdown.append({"label": "Acheteur stratégique : " + bh[0], "points": sb["points"]})

    # 4. Valeur
    v = n.get("value")
    if isinstance(v, (int, float)) and v > 0:
        for tier in cfg["value_bonus"]:
            if v >= tier["min"]:
                breakdown.append({"label": f"Valeur ≥ {tier['min']:,} €".replace(",", " "), "points": tier["points"]})
                break

    # 5. Hors cible
    neg = find_keywords(text, cfg["negative"]["keywords"].keys())
    if neg:
        breakdown.append({"label": "Hors cible : " + ", ".join(neg), "points": min(cfg["negative"]["keywords"][k] for k in neg)})

    # 6. Type d'avis
    adj = cfg["type_adjust"].get(n.get("type") or "other", 0)
    if adj:
        breakdown.append({"label": "Type d'avis (" + (n.get("type") or "") + ")", "points": adj})

    score = max(0, round(sum(b["points"] for b in breakdown)))
    th = cfg["thresholds"]
    if score >= th["high"] and has_legal:
        prio = "high"
    elif score >= th["medium"]:
        prio = "medium"
    else:
        prio = "low"

    # dédoublonner les mots-clés en gardant l'ordre
    seen = set()
    canon = lambda k: normalize(k).replace("-", " ")
    matched = [m for m in matched if not (canon(m) in seen or seen.add(canon(m)))]
    matched = [m for m in matched if not any(m != o and len(canon(m)) < len(canon(o)) and
                                               f" {canon(m)} " in f" {canon(o)} " for o in matched)]

    why = _explain(has_legal, practices, bh, lk, cpv_hits_legal or cpv_hits_adv, neg, n)
    return {
        "score": score,
        "priority": prio,
        "practices": practices or (["Conseil juridique général"] if has_legal else []),
        "matched": matched,
        "why": why,
        "breakdown": breakdown,
        "has_legal_signal": has_legal,
    }


def _explain(has_legal, practices, buyers, legal_kw, cpvs, neg, n):
    bits = []
    if has_legal:
        src = []
        if cpvs:
            src.append("CPV " + ", ".join(cpvs))
        if legal_kw:
            src.append("« " + legal_kw[0] + " »")
        bits.append("Mission juridique/conseil (" + " + ".join(src) + ")")
    else:
        bits.append("Pas de signal juridique explicite — à vérifier")
    if practices:
        bits.append("domaine(s) : " + ", ".join(practices[:3]))
    if buyers:
        bits.append("acheteur stratégique")
    if neg:
        bits.append("pénalisé : " + ", ".join(neg))
    if n.get("type") == "award":
        bits.append("avis d'attribution (veille concurrentielle)")
    return " · ".join(bits) + "."
