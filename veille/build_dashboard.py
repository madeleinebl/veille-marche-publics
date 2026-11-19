"""Génère docs/index.html (autonome, données intégrées) et docs/data.json à partir du gabarit."""
import json
from datetime import datetime, timezone

from . import DOCS_DIR, ROOT

TEMPLATE = ROOT / "dashboard" / "template.html"
MARKER = "/*__VEILLE_DATA__*/null"

DASH_FIELDS = ["id", "origin", "src", "url", "title", "buyer", "country", "pub", "dl", "type", "type_label",
               "cpv", "value", "lots", "family", "procedure_label", "sources", "corrigenda", "last_corrigendum",
               "award_published", "first_seen", "last_seen", "last_changed", "score", "priority", "practices",
               "matched", "why", "breakdown", "has_legal_signal", "manual_note", "matched_queries"]

SOURCES_INFO = {
    "BOAMP": {"label": "BOAMP — Open Data DILA", "official": True,
              "url": "https://boamp-datadila.opendatasoft.com/explore/dataset/boamp/",
              "note": "API publique Opendatasoft (licence Etalab 2.0), sans clé. Tous les avis BOAMP, MAPA ≥ 90 k€ inclus."},
    "TED": {"label": "TED — Search API v3 (Office des publications UE)", "official": True,
            "url": "https://api.ted.europa.eu/swagger-ui/index.html",
            "note": "API publique, recherche anonyme sans clé. Avis européens (JOUE S)."},
    "MANUEL": {"label": "Saisie manuelle", "official": False, "url": None,
               "note": "Ajouté à la main dans data/manual_notices.json — non vérifié par une collecte automatique."},
}


def _payload(notices, runs, cfg, scfg):
    collect_runs = [r for r in runs if r.get("mode") == "collect"]
    last = collect_runs[-1] if collect_runs else None
    last_ok = next((r for r in reversed(collect_runs) if r.get("status") in ("ok", "partial")), None)
    has_auto = any(n.get("origin") in ("auto", "manual+auto") for n in notices)
    mode = "live" if (last_ok and has_auto) else ("live-empty" if last_ok else "no-collection-yet")
    slim = []
    for n in notices:
        d = {k: n.get(k) for k in DASH_FIELDS if n.get(k) not in (None, [], "")}
        if n.get("description"):
            d["description"] = n["description"][:700]
        if n.get("changes"):
            d["changes"] = n["changes"][-5:]
        slim.append(d)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_mode": mode,
        "last_run": last,
        "last_success": last_ok,
        "runs": [{k: r.get(k) for k in ("run_id", "status", "duration_s", "since", "totals", "sources", "mode")}
                 for r in collect_runs[-15:]],
        "sources_info": SOURCES_INFO,
        "cpv_legal": cfg["cpv_legal"],
        "cpv_advisory": cfg["cpv_advisory"],
        "scoring": {
            "thresholds": scfg["thresholds"],
            "legal": list(scfg["legal_signal"]["keywords"].keys()),
            "practices": {k: list(v["keywords"].keys()) for k, v in scfg["practices"].items()},
        },
        "notices": slim,
    }


def build(notices, runs, cfg, scfg, docs_dir=None, template=None):
    docs = docs_dir or DOCS_DIR
    docs.mkdir(parents=True, exist_ok=True)
    payload = _payload(notices, runs, cfg, scfg)
    tpl = (template or TEMPLATE).read_text(encoding="utf-8")
    if MARKER not in tpl:
        raise RuntimeError("Marqueur de données absent du gabarit dashboard/template.html")
    js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (docs / "index.html").write_text(tpl.replace(MARKER, js), encoding="utf-8")
    (docs / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    return docs / "index.html"
