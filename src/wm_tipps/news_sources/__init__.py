"""News-Adapter-Plugins fuer wm_tipps.news.refresh_news.

Jede Quelle stellt bereit:

- ``NAME``: kurzer Quellenname (str).
- ``collect(teams, *, per_team_limit=6) -> list[dict]``: liefert rohe
  News-Items im annotate_news-kompatiblen Format (title, url, summary,
  published_at, source, optional teams).

Konvention: OSError (Netzwerkfehler) fangen die Adapter selbst und
liefern eine ggf. partielle Liste; alle anderen Exceptions duerfen
hochlaufen, refresh_news fangt sie und meldet status=error.
"""
