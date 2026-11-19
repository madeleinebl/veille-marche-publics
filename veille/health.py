"""Contrôle après exécution : échoue (code 1) si une source officielle est tombée,
pour que GitHub envoie un e-mail d'alerte. Les données déjà collectées restent publiées."""
import json
import sys

from . import DATA_DIR


def main():
    try:
        runs = json.load(open(DATA_DIR / "runs.json", encoding="utf-8"))
    except FileNotFoundError:
        print("Aucun journal d'exécution.")
        return 1
    last = runs[-1]
    print(f"Dernière exécution : {last['run_id']} — statut {last['status']} — {last.get('duration_s')} s")
    bad = []
    for name, info in last.get("sources", {}).items():
        print(f"  {name:16} {info.get('status'):8} {info.get('records', '')} avis "
              f"{('— ' + ' | '.join(info.get('errors', [])[:2])) if info.get('errors') else ''}")
        if name in ("BOAMP", "TED") and info.get("status") == "failed":
            bad.append(name)
    if bad:
        print("::error::Source(s) indisponible(s) : " + ", ".join(bad) + " — voir le journal ci-dessus.")
        return 1
    if last.get("status") == "partial":
        print("::warning::Certaines requêtes ont échoué (statut partiel) — les autres données sont à jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
