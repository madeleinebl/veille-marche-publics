"""Client HTTP avec réessais et délai d'attente. Aucune clé API nécessaire."""
import time

import requests

USER_AGENT = "veille-marches-publics/1.0 (veille marches publics; contact via depot GitHub)"


class SourceError(Exception):
    """Erreur de source (réseau, HTTP, format) — enregistrée dans le journal, n'arrête pas les autres sources."""


def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def request_json(session, method, url, *, params=None, json_body=None, timeout=60, retries=3, backoff=4):
    """Renvoie (json, None) ou lève SourceError. Réessaie sur erreurs réseau, 429 et 5xx."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = session.request(method, url, params=params, json=json_body, timeout=timeout)
        except requests.RequestException as e:
            last = f"réseau : {e.__class__.__name__}: {e}"
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    raise SourceError(f"réponse non JSON de {url} (HTTP 200)")
            body = r.text[:500].replace("\n", " ")
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code} : {body}"
                wait = int(r.headers.get("Retry-After", 0) or 0) or backoff * attempt
                time.sleep(min(wait, 60))
                continue
            raise SourceError(f"HTTP {r.status_code} : {body}", ) from None
        time.sleep(backoff * attempt)
    raise SourceError(f"échec après {retries} tentatives — {last}")
