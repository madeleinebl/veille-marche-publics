"""Point d'entrée : collecte → fusion → scoring → journal → tableau de bord.

Exemples :
  python -m veille.run                      # exécution quotidienne normale
  python -m veille.run --lookback 30        # remonter 30 jours
  python -m veille.run --idweb 26-106060    # forcer l'ajout d'un avis BOAMP précis
  python -m veille.run --offline            # sans réseau : recalcule scores + tableau de bord
"""
import argparse
import json
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone

from . import CONFIG_DIR, DATA_DIR
from .boamp import BoampCollector
from .build_dashboard import build
from .http import SourceError, make_session
from .scoring import load_scoring, score_notice
from .store import Store, load_json, manual_to_record, save_json
from .ted import TedCollector

NOTICES = DATA_DIR / "notices.json"
RUNS = DATA_DIR / "runs.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def apply_score(n, scfg, cfg):
    n.update(score_notice(n, scfg, set(cfg["cpv_legal"]), set(cfg["cpv_advisory"])))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Veille marchés publics BDGS")
    ap.add_argument("--lookback", type=int, help="nombre de jours à couvrir")
    ap.add_argument("--sources", default="", help="ex. boamp,ted (par défaut : toutes celles activées)")
    ap.add_argument("--idweb", default="", help="identifiant(s) BOAMP à ajouter, séparés par des virgules")
    ap.add_argument("--offline", action="store_true", help="pas de collecte réseau")
    ap.add_argument("--data-dir", default=None, help="dossier de données (tests)")
    args = ap.parse_args(argv)

    data_dir = DATA_DIR if args.data_dir is None else __import__("pathlib").Path(args.data_dir)
    notices_path, runs_path = data_dir / "notices.json", data_dir / "runs.json"

    cfg = json.load(open(CONFIG_DIR / "sources.json", encoding="utf-8"))
    scfg = load_scoring()
    runs = load_json(runs_path, [])
    store = Store(load_json(notices_path, []))

    started = time.time()
    run_id = now_iso()
    had_success = any(r.get("status") in ("ok", "partial") and r.get("mode") == "collect" for r in runs)
    lookback = args.lookback or (cfg["lookback_days_daily"] if had_success else cfg["lookback_days_first_run"])
    since = (date.today() - timedelta(days=lookback)).isoformat()
    wanted = {s.strip().upper() for s in args.sources.split(",") if s.strip()}

    run = {"run_id": run_id, "started_at": run_id, "mode": "offline" if args.offline else "collect",
           "since": since, "lookback_days": lookback, "sources": {}, "totals": {}}
    log(f"Exécution {run_id} — avis publiés depuis le {since} ({lookback} j)")

    counts = {"new": 0, "updated": 0, "merged": 0, "corr": 0, "filtered": 0}
    session = make_session()
    collectors = []
    if not args.offline:
        if cfg["boamp"]["enabled"] and (not wanted or "BOAMP" in wanted):
            collectors.append(BoampCollector(session, cfg, log))
        if cfg["ted"]["enabled"] and (not wanted or "TED" in wanted):
            collectors.append(TedCollector(session, cfg, log))

    for col in collectors:
        t0 = time.time()
        info = {"status": "ok", "records": 0, "kept": 0, "new": 0, "updated": 0, "merged": 0,
                "corrigenda": 0, "filtered_low_score": 0, "errors": []}
        try:
            recs, stats = col.collect(since)
            info.update({"queries": stats["queries"], "raw_rows": stats["raw_rows"], "records": len(recs)})
            if stats["query_errors"]:
                info["status"] = "partial"
                info["errors"] = stats["query_errors"][:10]
            for rec in recs:
                if rec["uid"] not in store.uid_index:
                    pre = score_notice(rec, scfg, set(cfg["cpv_legal"]), set(cfg["cpv_advisory"]))
                    if pre["score"] < scfg["thresholds"]["min_to_keep"]:
                        info["filtered_low_score"] += 1
                        continue
                res = store.upsert(rec, run_id)
                info["kept"] += 1
                key = {"new": "new", "corr_new": "new", "updated": "updated", "merged": "merged", "corr": "corrigenda"}.get(res)
                if key:
                    info[key] += 1
        except SourceError as e:
            info["status"] = "failed"
            info["errors"].append(str(e))
            log(f"✗ {col.name} indisponible : {e}")
        except Exception as e:  # erreur de code : on la journalise sans bloquer les autres sources
            info["status"] = "failed"
            info["errors"].append(f"{e.__class__.__name__}: {e}")
            traceback.print_exc()
        info["duration_s"] = round(time.time() - t0, 1)
        run["sources"][col.name] = info
        log(f"{col.name} : {info['status']} — {info['records']} avis reçus, {info['new']} nouveaux, "
            f"{info['updated']} mis à jour, {info['corrigenda']} rectificatifs, {info['merged']} fusionnés, "
            f"{info['filtered_low_score']} écartés (score faible) en {info['duration_s']} s")

    # Avis BOAMP ajoutés à la demande (identifiant connu, ex. MAPA repéré manuellement)
    if args.idweb and not args.offline:
        col = BoampCollector(session, cfg, log)
        info = {"status": "ok", "requested": [], "found": [], "errors": []}
        for idw in [x.strip() for x in args.idweb.split(",") if x.strip()]:
            info["requested"].append(idw)
            try:
                for rec in col.fetch_one(idw):
                    store.upsert(rec, run_id)
                    info["found"].append(idw)
            except SourceError as e:
                info["status"] = "failed"
                info["errors"].append(f"{idw} : {e}")
        run["sources"]["BOAMP (idweb)"] = info
        log(f"BOAMP idweb : trouvés {info['found']} / demandés {info['requested']}")

    # Saisies manuelles (data/manual_notices.json)
    if cfg["manual"]["enabled"]:
        manual = load_json(data_dir / "manual_notices.json", {"notices": []}).get("notices", [])
        keep = set()
        for m in manual:
            rec = manual_to_record(m)
            keep.add(rec["uid"])
            if rec["uid"] in store.uid_index:
                ex = store.by_id[store.uid_index[rec["uid"]]]
                ex["last_seen"] = run_id
                if ex.get("origin") == "auto":
                    ex["origin"] = "manual+auto"  # saisie manuelle confirmée par la collecte officielle
                if m.get("note") and not ex.get("manual_note"):
                    ex["manual_note"] = m["note"]
                continue
            store.upsert(rec, run_id, origin="manual")
        for n in list(store.notices):
            if n.get("origin") == "manual" and not ({f"{x['source']}:{x['source_id']}" for x in n["sources"]} & keep):
                store.remove(n["id"])
        run["sources"]["Saisie manuelle"] = {"status": "ok", "records": len(manual)}

    for n in store.notices:
        apply_score(n, scfg, cfg)
    store.notices.sort(key=lambda n: (n.get("pub") or "", n["id"]), reverse=True)

    statuses = [v["status"] for k, v in run["sources"].items() if k in ("BOAMP", "TED")]
    if args.offline or not statuses:
        run["status"] = "ok"
    elif all(s == "failed" for s in statuses):
        run["status"] = "failed"
    elif any(s != "ok" for s in statuses):
        run["status"] = "partial"
    else:
        run["status"] = "ok"
    run["finished_at"] = now_iso()
    run["duration_s"] = round(time.time() - started, 1)
    run["totals"] = {
        "notices": len(store.notices),
        "new": sum(1 for n in store.notices if n["first_seen"] == run_id and n.get("origin") != "manual"),
        "high": sum(1 for n in store.notices if n.get("priority") == "high"),
    }
    runs.append(run)
    runs = runs[-400:]

    save_json(notices_path, store.notices)
    save_json(runs_path, runs)
    out = build(store.notices, runs, cfg, scfg, docs_dir=None if args.data_dir is None else data_dir.parent / "docs")
    log(f"Terminé : statut {run['status']} en {run['duration_s']} s — {run['totals']} — tableau de bord : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
