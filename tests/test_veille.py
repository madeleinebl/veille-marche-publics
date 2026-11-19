"""Tests automatiques (hors réseau) — données SYNTHÉTIQUES uniquement, jamais publiées."""
import json
import shutil
from pathlib import Path

import pytest

from veille import boamp, run, ted
from veille.http import SourceError
from veille.scoring import load_scoring, score_notice
from veille.store import Store, manual_to_record
from veille.text import find_keywords, normalize

FIX = Path(__file__).parent / "fixtures"
CFG = json.load(open(Path(__file__).parent.parent / "config" / "sources.json", encoding="utf-8"))
SCFG = load_scoring()
LEGAL, ADV = set(CFG["cpv_legal"]), set(CFG["cpv_advisory"])


def fx(name):
    return json.load(open(FIX / name, encoding="utf-8"))


def score(n):
    return score_notice(n, SCFG, LEGAL, ADV)


# ---------------- texte ----------------
def test_keywords_whole_words_and_accents():
    t = normalize("Services d'interprétariat et Prêt à usage — Sûretés réelles")
    assert "pret" in find_keywords(t, ["pret"])            # "Prêt" isolé : oui
    assert find_keywords(normalize("interprétariat"), ["pret"]) == []  # pas dans un autre mot
    assert find_keywords(t, ["suretes"]) == ["suretes"]
    assert find_keywords(normalize("partenariat public-privé"), ["partenariat public prive"])
    assert find_keywords(normalize("engagement"), ["gage"]) == []


# ---------------- scoring ----------------
def test_scoring_bdgs_target_is_high_and_explained():
    n = {"title": "Conseil juridique pour la mise en place de garanties rehaussées", "buyer": "Bpifrance Assurance Export",
         "description": "financements structurés, assurance-crédit", "cpv": ["79111000"], "value": 600012, "type": "call"}
    s = score(n)
    assert s["priority"] == "high"
    assert "Finance & Bancaire" in s["practices"]
    assert "garanties rehaussees" in s["matched"]
    assert "Mission juridique" in s["why"] and "acheteur stratégique" in s["why"]
    assert sum(b["points"] for b in s["breakdown"]) == s["score"]


def test_scoring_off_target_is_low():
    s = score({"title": "Prestations de nettoyage des locaux", "buyer": "Commune", "cpv": ["90910000"], "type": "call"})
    assert s["priority"] == "low" and s["score"] < SCFG["thresholds"]["min_to_keep"]


def test_scoring_high_requires_legal_signal():
    n = {"title": "Financement de projet, PPP, concession, nucléaire, émission obligataire, LBO, refinancement",
         "buyer": "X", "cpv": ["45000000"], "type": "call"}
    s = score(n)
    assert s["score"] >= SCFG["thresholds"]["high"] and s["priority"] == "medium"


def test_award_is_penalised():
    base = {"title": "Conseil juridique droit social", "buyer": "Département", "cpv": ["79111000"]}
    assert score({**base, "type": "award"})["score"] < score({**base, "type": "call"})["score"]


# ---------------- parsing ----------------
def test_boamp_parse():
    recs = [boamp.parse_record(r, "t") for r in fx("SYNTHETIC_boamp_page.json")["results"]]
    a, _, corr, d = recs
    assert a["uid"] == "BOAMP:99-000001" and a["pub"] == "2026-11-02" and a["dl"] == "2026-11-25"
    assert a["cpv"] == ["79111000"] and a["value"] == 600012
    assert a["procedure_id"] == "11111111-2222-3333-4444-555555555555"
    assert "Common Law" in a["description"] and "Lot unique" in a["lots"]
    assert corr["type"] == "corr" and corr["linked_ids"] == ["99-000001"]
    assert d["procedure_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_ted_parse_multilingual():
    recs = [ted.parse_notice(n, "t") for n in fx("SYNTHETIC_ted_page.json")["notices"]]
    fr, de, awd = recs
    assert fr["title"].startswith("TEST — Assistance juridique")   # français préféré
    assert de["title"].startswith("TEST — Legal advisory")           # anglais à défaut
    assert de["dl"] == "2026-12-15" and de["country"] == "DEU"       # échéance la plus proche
    assert fr["value"] == 450000 and fr["cpv"] == ["79111000", "66171000"]
    assert awd["type"] == "award" and fr["type"] == "call"
    assert fr["url"].endswith("999001-2026")


# ---------------- base / fusion ----------------
def _recs():
    b = [boamp.parse_record(r, "t") for r in fx("SYNTHETIC_boamp_page.json")["results"]]
    t = [ted.parse_notice(n, "t") for n in fx("SYNTHETIC_ted_page.json")["notices"]]
    return b, t


def test_store_dedup_corrigenda_updates():
    b, t = _recs()
    st = Store([])
    assert st.upsert(b[0], "R1") == "new"
    assert st.upsert(b[3], "R1") == "new"
    assert st.upsert(t[0], "R1") == "merged"          # même procédure (UUID) BOAMP ↔ TED
    merged = st.by_id["BOAMP:99-000004"]
    assert {s["source"] for s in merged["sources"]} == {"BOAMP", "TED"}
    assert merged["value"] == 450000                   # complété par TED
    assert st.upsert(b[2], "R2") == "corr"             # rectificatif rattaché via l'avis antérieur
    parent = st.by_id["BOAMP:99-000001"]
    assert parent["corrigenda"][0]["source_id"] == "99-000003"
    assert parent["dl"] == "2026-12-02" and parent["changes"][-1]["field"] == "dl"
    # même avis revu le lendemain avec titre modifié → mise à jour + historique
    b0 = dict(b[0], title=b[0]["title"] + " (modifié)")
    assert st.upsert(b0, "R3") == "updated"
    assert parent["first_seen"] == "R1" and parent["last_changed"] == "R3"
    assert st.upsert(b0, "R4") == "same"
    assert len(st.notices) == 2


def test_fuzzy_merge_without_uuid():
    b, t = _recs()
    rec_b = dict(b[3], procedure_id=None, uuids=[])
    rec_t = dict(t[0], procedure_id=None, uuids=[])
    st = Store([])
    st.upsert(rec_b, "R1")
    assert st.upsert(rec_t, "R1") == "merged"


def test_manual_entry_confirmed_by_collection():
    st = Store([])
    m = manual_to_record({"source": "BOAMP", "source_id": "99-000001", "title": "Saisie", "buyer": "X",
                          "pub": "2026-11-02", "dl": "2026-11-25", "url": "u"})
    st.upsert(m, "R0", origin="manual")
    b, _ = _recs()
    st.upsert(b[0], "R1")
    n = st.by_id["BOAMP:99-000001"]
    assert n["origin"] == "manual+auto" and len(st.notices) == 1


# ---------------- exécution complète (réseau simulé) ----------------
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "manual_notices.json").write_text(json.dumps({"notices": [
        {"source": "BOAMP", "source_id": "99-000001", "title": "Saisie manuelle test", "buyer": "TEST Bpifrance",
         "pub": "2026-11-02", "dl": "2026-11-25", "url": "https://www.boamp.fr/pages/avis/?q=idweb:99-000001"}]}))
    calls = {"boamp": 0, "ted": 0}

    def fake_boamp(session, method, url, params=None, json_body=None, timeout=60, **k):
        calls["boamp"] += 1
        if params.get("offset", 0) > 0:
            return {"total_count": 4, "results": []}
        return fx("SYNTHETIC_boamp_page.json")

    def fake_ted(session, method, url, params=None, json_body=None, timeout=60, **k):
        calls["ted"] += 1
        return fx("SYNTHETIC_ted_page.json")

    monkeypatch.setattr(boamp, "request_json", fake_boamp)
    monkeypatch.setattr(ted, "request_json", fake_ted)
    return tmp_path, calls, monkeypatch


def test_end_to_end_run_and_rerun(sandbox):
    tmp, calls, _ = sandbox
    assert run.main(["--data-dir", str(tmp / "data")]) == 0
    notices = json.load(open(tmp / "data" / "notices.json"))
    runs = json.load(open(tmp / "data" / "runs.json"))
    ids = {n["id"] for n in notices}
    assert "BOAMP:99-000002" not in ids                    # nettoyage écarté (score faible)
    assert "BOAMP:99-000001" in ids and "TED:999002-2026" in ids
    first = {n["id"]: n["first_seen"] for n in notices}
    assert runs[-1]["status"] == "ok" and runs[-1]["sources"]["BOAMP"]["filtered_low_score"] >= 1
    assert next(n for n in notices if n["id"] == "BOAMP:99-000001")["origin"] == "manual+auto"
    html = (tmp / "docs" / "index.html").read_text(encoding="utf-8")
    assert "/*__VEILLE_DATA__*/" not in html and "BOAMP:99-000001" in html
    # 2e exécution : rien de nouveau, identifiants et dates de première détection inchangés
    assert run.main(["--data-dir", str(tmp / "data")]) == 0
    notices2 = json.load(open(tmp / "data" / "notices.json"))
    runs2 = json.load(open(tmp / "data" / "runs.json"))
    assert {n["id"]: n["first_seen"] for n in notices2} == first
    assert runs2[-1]["totals"]["new"] == 0 and runs2[-1]["lookback_days"] == CFG["lookback_days_daily"]


def test_source_failure_is_isolated(sandbox):
    tmp, _, mp = sandbox

    def down(*a, **k):
        raise SourceError("HTTP 503 : service indisponible")
    mp.setattr(ted, "request_json", down)
    assert run.main(["--data-dir", str(tmp / "data")]) == 0
    r = json.load(open(tmp / "data" / "runs.json"))[-1]
    assert r["status"] == "partial" and r["sources"]["TED"]["status"] == "failed"
    assert r["sources"]["BOAMP"]["status"] == "ok" and r["sources"]["BOAMP"]["new"] >= 1


def test_all_sources_down_keeps_previous_data(sandbox):
    tmp, _, mp = sandbox
    run.main(["--data-dir", str(tmp / "data")])
    before = json.load(open(tmp / "data" / "notices.json"))

    def down(*a, **k):
        raise SourceError("réseau : ConnectionError")
    mp.setattr(ted, "request_json", down)
    mp.setattr(boamp, "request_json", down)
    run.main(["--data-dir", str(tmp / "data")])
    after = json.load(open(tmp / "data" / "notices.json"))
    r = json.load(open(tmp / "data" / "runs.json"))[-1]
    assert r["status"] == "failed"
    assert {n["id"] for n in after} == {n["id"] for n in before}


def test_boamp_syntax_fallback(monkeypatch):
    seen = []

    def fake(session, method, url, params=None, **k):
        seen.append(params["where"])
        if "search(" in params["where"]:
            raise SourceError("HTTP 400 : ODSQL query is malformed")
        return {"total_count": 0, "results": []}
    monkeypatch.setattr(boamp, "request_json", fake)
    col = boamp.BoampCollector(None, CFG, lambda m: None)
    recs, stats = col.collect("2026-11-01")
    assert stats["query_errors"] == [] and recs == []
    assert any("like" in w for w in seen)


def test_ted_field_fallback(monkeypatch):
    sent = []

    def fake(session, method, url, json_body=None, **k):
        sent.append(len(json_body["fields"]))
        if len(json_body["fields"]) == len(ted.FIELD_SETS[0]):
            raise SourceError("HTTP 400 : unknown field 'description-proc'")
        return {"notices": [], "totalNoticeCount": 0}
    monkeypatch.setattr(ted, "request_json", fake)
    col = ted.TedCollector(None, CFG, lambda m: None)
    _, stats = col.collect("2026-11-01")
    assert stats["field_set"] == 1 and not stats["query_errors"]
