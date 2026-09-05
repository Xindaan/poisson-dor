"""Struktur-Regression fuer das Dashboard-Frontend (T-0163, Schritt S0).

Warum es diesen Test gibt: `index.html`, `assets/styles.css` und
`assets/app.js` hatten bis 2026-07-22 **keinerlei** Testabdeckung. Das
Markup der Tabs entsteht komplett zur Laufzeit aus Template-Strings in
`app.js`; ein CSS- oder Struktur-Umbau haette also stillschweigend Panels
leeren oder Event-Handler entkoppeln koennen, ohne dass ein Test rot wird.

Der Test nagelt bewusst nur den **Vertrag zwischen den drei Dateien**
fest, nicht das Aussehen:

  1. Jeder `data-tab`-Knopf hat ein `<section>` mit passender id (und
     umgekehrt) -- sonst zeigt ein Tab beim Klick auf eine leere Flaeche.
  2. Jede Klasse, an der JS-Verhalten haengt, existiert in beiden
     Dateien -- `run-command`, `card--clamp`, `card__toggle`, `is-open`,
     `panel`, `tab`, `active`.
  3. Jede von `app.js` erzeugte CSS-Klasse hat eine Regel in
     `styles.css`. Das ist der eigentliche Waechter fuer den
     Design-Umbau: wer eine Klasse umbenennt, muss beide Seiten anfassen.
  4. Die Toolbar-Steuerung kennt genau die `data-control`-Bloecke, die
     `index.html` auch hat.

Vorbild: `tests/test_pool_review.py` prueft ebenso Markup-Strings statt
Optik. Reine Stdlib, kein Browser, kein Parser-Paket -- es reicht,
Textmuster zu vergleichen.
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
STYLES = os.path.join(ROOT, "assets", "styles.css")
APP = os.path.join(ROOT, "assets", "app.js")

# Klassen, die zwar in app.js vorkommen, aber bewusst kein eigenes
# Styling haben (Verhaltens-Marker oder von Elternregeln miterfasst).
CLASSES_OHNE_EIGENE_REGEL = {
    "active",       # Zustand, gestylt als .tab.active / .panel.active
    "is-open",      # Zustand fuer die Quoten-Kacheln
    "compact",      # Modifier, gestylt als .metric.compact / .drill-list.compact
    "card--clamp",  # nur als #markets .card--clamp gestylt
    "card__body",   # dito
    "drill-row",    # Layout kommt von .drill-list
    "drill-section",
    # (`news-filters` stand hier bis T-0167 -- die Klasse war tot und ist
    #  mit den Panel-Filtern verschwunden.)
    # Ebenfalls wirkungslos: app.js:390 setzt class="round-tip", gestylt
    # wird der Kasten aber ausschliesslich ueber den Nachfahren-Selektor
    # `.round-tip-grid div` (styles.css:225). Beim Umbau ist das die
    # Gelegenheit, `.round-tip` zur echten Regel zu machen und den
    # Element-Selektor loszuwerden.
    "round-tip",
}

# Erlaubte CSS-Klassennamen. Alles andere in einem class="..."-Ausdruck ist
# JS-Syntax aus einem Template-Literal (`${x === y ? "a" : "b"}`) und darf
# nicht als Klasse gewertet werden.
KLASSENNAME = re.compile(r"^[a-zA-Z_-][\w-]*$")


def _lies(pfad: str) -> str:
    with open(pfad, encoding="utf-8") as fh:
        return fh.read()


class DashboardStrukturTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _lies(INDEX)
        cls.app = _lies(APP)
        # Die Stylesheet-Liste wird aus index.html abgeleitet, nicht
        # gepflegt: sonst prueft der Test nach dem naechsten <link> still
        # gegen eine unvollstaendige Menge und wird gruen, obwohl er
        # blind ist.
        blaetter = re.findall(r'<link rel="stylesheet" href="assets/([\w.-]+)"', cls.index)
        assert blaetter, "keine Stylesheets in index.html gefunden"
        cls.styles = "\n".join(
            _lies(os.path.join(ROOT, "assets", name)) for name in blaetter
        )

    # --- 1. Tabs und Panels passen zusammen ------------------------------

    def test_jeder_tab_hat_ein_panel(self):
        tabs = set(re.findall(r'data-tab="([\w-]+)"', self.index))
        panels = set(re.findall(r'<section id="([\w-]+)" class="panel', self.index))
        self.assertTrue(tabs, "keine data-tab-Knoepfe gefunden")
        self.assertEqual(
            tabs,
            panels,
            "Tab-Knoepfe und Panel-Sections laufen auseinander -- "
            "ein Klick wuerde auf eine leere Flaeche zeigen",
        )

    def test_genau_ein_tab_und_ein_panel_sind_initial_aktiv(self):
        self.assertEqual(len(re.findall(r'class="tab active"', self.index)), 1)
        self.assertEqual(len(re.findall(r'class="panel active"', self.index)), 1)

    def test_jedes_panel_wird_von_app_js_befuellt(self):
        """Ein Panel gilt als befuellt, wenn app.js entweder direkt
        hineinschreibt oder in einen seiner Container `<panel>-<name>`
        schreibt. Die zweite Form gibt es, seit `analyse` in
        `analyse-cards` (wird bei jedem Filterwechsel neu gebaut) und
        `analyse-rival-lab` (haelt eigenen Zustand, wird genau einmal
        montiert) zerfaellt.
        """
        panels = set(re.findall(r'<section id="([\w-]+)" class="panel', self.index))
        geschrieben = set(re.findall(r'getElementById\("([\w-]+)"\)', self.app))
        for panel in panels:
            with self.subTest(panel=panel):
                bedient = panel in geschrieben or any(
                    ziel.startswith(f"{panel}-") for ziel in geschrieben
                )
                self.assertTrue(
                    bedient,
                    f"Panel '{panel}' existiert im Markup, aber app.js "
                    f"schreibt weder hinein noch in einen '{panel}-*'-Container "
                    f"-- es bliebe leer",
                )

    # --- 2. Verhaltens-Klassen existieren auf beiden Seiten ---------------

    def test_verhaltensklassen_sind_in_app_js_und_styles_vorhanden(self):
        # Diese Klassen tragen Klick-Verhalten. Wird eine davon einseitig
        # umbenannt, funktioniert die UI weiter, sieht aber kaputt aus --
        # oder umgekehrt. Beides faellt sonst niemandem auf.
        for klasse in ("run-command", "card__toggle", "tab", "panel"):
            with self.subTest(klasse=klasse):
                self.assertIn(klasse, self.app, f"'{klasse}' fehlt in app.js")
                self.assertIn(klasse, self.styles, f"'{klasse}' fehlt in styles.css")

    def test_ein_klick_update_ist_verdrahtet(self):
        # Die Hauptaktion der Seite: Knopf, Endpunkt, Handler, Styling.
        # Der Kommandoname steht NICHT literal im Markup -- er kommt aus
        # den Daten (`data-command="${esc(row.command)}"`, app.js:1802);
        # "update-all" taucht nur als Nachschlage-Schluessel auf.
        self.assertIn('class="run-command"', self.app)
        self.assertIn('data-command="${esc(row.command)}"', self.app)
        self.assertIn('"update-all"', self.app)
        self.assertIn("/api/run-command", self.app)
        self.assertIn('querySelectorAll(".run-command")', self.app)
        self.assertIn(".run-command", self.styles)

    def test_jede_id_die_app_js_sucht_existiert_auch(self):
        """Fehlerklasse aus T-0168: ein Panel wird entfernt, app.js greift
        weiter darauf zu und stirbt beim ersten Render -- ohne dass ein
        Test rot wird. Beim Tab-Umbau ist das dreimal passiert
        (`bonus`, `watchlist`, `pipeline`). Eine gesuchte id muss also
        entweder im Markup stehen oder von app.js selbst erzeugt werden.
        """
        gesucht = set(re.findall(r'getElementById\("([\w-]+)"\)', self.app))
        im_markup = set(re.findall(r'id="([\w-]+)"', self.index))
        # Zwei Wege, wie app.js selbst ein Element mit id erzeugt: als
        # Markup-Attribut in einem Template-String, oder per Zuweisung
        # (`el.id = "tt"` beim Tooltip des Rival-Labs).
        von_js_erzeugt = set(re.findall(r'id="([\w-]+)"', self.app)) | set(
            re.findall(r'\.id\s*=\s*"([\w-]+)"', self.app)
        )
        fehlend = sorted(gesucht - im_markup - von_js_erzeugt)
        self.assertEqual(
            [],
            fehlend,
            f"app.js sucht Elemente, die es nicht gibt: {fehlend}",
        )

    def _sichtbarkeitstabelle(self):
        """Liest TOOLBAR_SICHTBARKEIT aus app.js als {control: [tabs]}."""
        block = re.search(
            r"const TOOLBAR_SICHTBARKEIT = \{(.*?)\n\};", self.app, re.S
        )
        self.assertIsNotNone(block, "TOOLBAR_SICHTBARKEIT nicht gefunden")
        tabelle = {}
        for zeile in block.group(1).splitlines():
            treffer = re.match(r'\s*"([\w-]+)":\s*\[([^\]]*)\]', zeile)
            if treffer:
                tabelle[treffer.group(1)] = re.findall(r'"([\w-]+)"', treffer.group(2))
        return tabelle

    def test_toolbar_sichtbarkeitsregeln_nennen_existierende_tabs(self):
        """Verschwindet ein Tab, bleibt sein Name in der Tabelle still
        stehen und die Regel laeuft ins Leere (so geschehen mit
        `watchlist`, das nach dem Tab-Umbau in SORT_TABS zurueckblieb).
        """
        tabs = set(re.findall(r'data-tab="([\w-]+)"', self.index))
        for control, genannte in self._sichtbarkeitstabelle().items():
            with self.subTest(control=control):
                self.assertEqual(
                    set(),
                    set(genannte) - tabs,
                    f"'{control}' nennt Tabs, die es nicht mehr gibt: "
                    f"{sorted(set(genannte) - tabs)}",
                )

    def test_toolbar_steuerung_kennt_die_vorhandenen_bloecke(self):
        im_markup = set(re.findall(r'data-control="([\w-]+)"', self.index))
        in_tabelle = set(self._sichtbarkeitstabelle())
        self.assertTrue(im_markup, "keine data-control-Bloecke im Markup")
        self.assertEqual(
            im_markup,
            in_tabelle,
            "index.html und TOOLBAR_SICHTBARKEIT kennen unterschiedliche "
            "Filter-Bloecke -- einer davon wird nie ein- oder ausgeblendet",
        )

    def test_karten_mit_tabellen_sind_als_breit_markiert(self):
        """R-25 als Klasse, nicht als Einzelfall.

        Eine Karte im Raster ist ~370px breit. Eine Tabelle mit 4-5
        Textspalten passt da nicht und ragte bisher unerreichbar ueber den
        Rand. Betroffen waren gleich DREI Karten (Quoten-Coverage,
        Quoten-Freshness, Exact-Score) -- wer die naechste Tabelle in eine
        Karte haengt, soll nicht denselben Fehler wiederholen duerfen.

        Regel: liefert eine Render-Funktion eine `.table-wrap` und wird ihr
        Ergebnis an `marketCard` uebergeben, muss die Karte `breit` sein.
        """
        # Welche Render-Funktionen erzeugen eine Tabelle?
        mit_tabelle = set()
        for treffer in re.finditer(r"\nfunction (render\w+)\(\) \{(.*?)\n\}", self.app, re.S):
            if "table-wrap" in treffer.group(2):
                mit_tabelle.add(treffer.group(1))
        self.assertTrue(mit_tabelle, "keine tabellenerzeugende Render-Funktion gefunden")

        # Welche Variable haelt das Ergebnis welcher Funktion?
        quelle = dict(re.findall(r"const (\w+) = (render\w+)\(\);", self.app))

        # Jeder marketCard-Aufruf mit so einer Variable muss breit sein.
        for aufruf in re.finditer(
            r'marketCard\(\s*"([^"]+)"\s*,\s*(\w+)\s*(,\s*true\s*)?\)', self.app
        ):
            titel, variable, breit = aufruf.group(1), aufruf.group(2), aufruf.group(3)
            if quelle.get(variable) in mit_tabelle:
                with self.subTest(karte=titel):
                    self.assertIsNotNone(
                        breit,
                        f"Karte '{titel}' enthaelt eine Tabelle, ist aber nicht "
                        f"als breit markiert -- die Spalten waeren am "
                        f"Kartenrand abgeschnitten",
                    )

    def test_breite_karten_haben_eine_rasterregel(self):
        self.assertIn(".card--wide", self.styles)
        self.assertIn("grid-column: 1 / -1", self.styles)

    def test_jeder_toolbar_filter_ist_genau_einmal_verdrahtet(self):
        """T-0167: Die Panel-Filter wurden frueher bei jedem Render neu
        erzeugt UND neu gebunden. Jetzt stehen sie fest im Markup und
        duerfen genau einmal gebunden werden -- ein zweiter bind-Aufruf
        wuerde jeden Wechsel doppelt ausloesen.
        """
        for select_id in ("news-severity", "news-category", "news-impact",
                          "history-trigger"):
            with self.subTest(filter=select_id):
                self.assertIn(
                    f'id="{select_id}"',
                    self.index,
                    f"'{select_id}' steht nicht im Markup",
                )
                self.assertNotIn(
                    f'<select id="{select_id}"',
                    self.app,
                    f"'{select_id}' wird in app.js erzeugt -- dann lebt der "
                    f"Handler nur bis zum naechsten Render",
                )
        # Nur AUFRUFE zaehlen, nicht die Funktionsdefinition.
        aufrufe = re.findall(r"(?<!function )bindToolbarFilters\(\)", self.app)
        self.assertEqual(
            1,
            len(aufrufe),
            "bindToolbarFilters darf genau einmal aufgerufen werden",
        )

    # --- 3. Der eigentliche Waechter fuer den Design-Umbau ----------------

    def test_jede_von_app_js_erzeugte_klasse_ist_gestylt(self):
        erzeugt: set[str] = set()
        for treffer in re.findall(r'class=\\?"([^"\\]+)', self.app):
            for klasse in treffer.split():
                if "$" in klasse or not KLASSENNAME.match(klasse):
                    continue  # dynamisch gesetzt, s. naechster Test
                erzeugt.add(klasse)

        # Der Negative-Lookahead ist wesentlich: ohne ihn wuerde eine
        # Regel `.tip-badges-row-neu` als Treffer fuer die Klasse
        # `tip-badges-row` durchgehen, und genau das Umbenennen einer
        # Regel soll dieser Test ja bemerken.
        ungestylt = sorted(
            k
            for k in erzeugt - CLASSES_OHNE_EIGENE_REGEL
            if not re.search(rf"\.{re.escape(k)}(?![\w-])", self.styles)
        )
        self.assertEqual(
            [],
            ungestylt,
            "app.js erzeugt Klassen ohne jede CSS-Regel: "
            f"{ungestylt} -- entweder Tippfehler oder beim Umbau vergessen",
        )

    def test_statusklassen_der_badges_sind_vollstaendig_gestylt(self):
        # statusClass()/qualityClass() liefern diese Werte dynamisch; sie
        # tauchen deshalb nicht als literales class="..." auf.
        for zustand in ("stabil", "volatil", "warte"):
            with self.subTest(zustand=zustand):
                self.assertIn(
                    f".badge.{zustand}",
                    self.styles,
                    f"Badge-Zustand '{zustand}' hat keine eigene Farbe",
                )

    # --- 4. Grundgeruest bleibt bedienbar --------------------------------

    def test_stylesheet_ist_eingebunden(self):
        self.assertIn('rel="stylesheet"', self.index)
        self.assertIn("assets/app.js", self.index)

    def test_seite_laedt_nichts_aus_dem_netz(self):
        # Das Dashboard laeuft lokal; externe Fonts/CDNs waeren ein
        # stiller Offline-Bruch (und ein Datenschutz-Leck).
        for datei, name in ((self.index, "index.html"), (self.styles, "styles.css")):
            with self.subTest(datei=name):
                self.assertNotIn("//fonts.", datei)
                self.assertNotIn("cdn.", datei)
                self.assertNotIn("@import url(http", datei)


class RivalLabGeteilteAssetsTests(unittest.TestCase):
    """Seit T-0165 speisen dieselben drei Dateien zwei Ziele: den
    Dashboard-Tab "Analyse" und die standalone `analysis/rival_lab.html`.
    Genau da entsteht die naechste Drift -- wird `mountRivalLab`
    umbenannt oder ein Asset verschoben, faellt eines der beiden Ziele
    still aus. Diese Tests halten den Vertrag fest.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _lies(INDEX)
        cls.app = _lies(APP)
        cls.lab_js = _lies(os.path.join(ROOT, "assets", "rival_lab.js"))

    def test_einstiegspunkt_heisst_in_allen_dreien_gleich(self):
        self.assertIn("function mountRivalLab(", self.lab_js)
        self.assertIn("mountRivalLab(payload)", self.app)
        self.assertIn('src="assets/rival_lab.js"', self.index)

    def test_lab_wird_nur_einmal_montiert(self):
        # Aus renderAll heraus wuerde das Lab bei jedem Tastendruck in der
        # Suche neu gebaut und verlore Runde, Unter-Tab und Filter.
        self.assertNotIn("mountRivalLabPanel()", self.app.split("function renderAll")[1].split("}")[0])

    def test_standalone_seite_bleibt_self_contained(self):
        import sys

        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        from rival_lab_render import render_html

        markup = render_html({"probe": True})
        # CSS und JS muessen INLINE stehen -- die Datei wird per
        # Doppelklick geoeffnet, ohne Server und ohne Netz.
        self.assertNotIn('<link rel="stylesheet"', markup)
        self.assertNotIn('src="assets/', markup)
        self.assertIn("function mountRivalLab(", markup)
        self.assertIn("--acc:", markup, "tokens.css wurde nicht eingebettet")
        self.assertIn(".rival-lab", markup, "rival_lab.css wurde nicht eingebettet")
        self.assertNotIn("http://", markup)
        self.assertNotIn("https://", markup)

    def test_keine_dark_theme_reste_in_der_render_logik(self):
        """Die Fehlerklasse aus T-0165: das Lab war ein Dark Theme, und
        einzelne Farben stecken als Literale in der Chart-Logik statt im
        CSS. Uebersieht man eine, bleibt genau ein Element dunkel.
        """
        dunkel = [
            "#0d1117", "#161b22", "#1c2230", "#e6edf3", "#58a6ff",
            "#30363d", "#8b949e", "#11161f", "#0b0f16", "#08111f",
            "#f97316", "#38bdf8", "#a3e635", "#c084fc", "#22d3ee",
        ]
        gefunden = sorted(farbe for farbe in dunkel if farbe in self.lab_js)
        self.assertEqual([], gefunden, f"Dark-Theme-Reste: {gefunden}")

    def test_helle_rampe_stimmt_mit_pool_review_ueberein(self):
        """Die Heatmap-Rampe wurde aus pool_review_render.py uebernommen,
        damit beide Frontends dieselbe Skala zeigen. Laeuft eine der
        beiden weg, ist der Vergleich zwischen den Seiten wertlos.
        """
        import sys

        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        from pool_review_render import RAMP

        for hexwert in RAMP[1:]:
            r, g, b = (int(hexwert[i:i + 2], 16) for i in (1, 3, 5))
            with self.subTest(farbe=hexwert):
                self.assertIn(
                    f"[{r},{g},{b}]",
                    self.lab_js,
                    f"Stufe {hexwert} der Pool-Review-Rampe fehlt in heatColor",
                )


class PlayerBoardGeteilteAssetsTests(unittest.TestCase):
    """Zweites Paar aus T-0165, gleiche Fehlerklasse wie beim Rival-Lab:
    `assets/player_board.js` speist den Dashboard-Tab UND die standalone
    `analysis/wm_player_board.html`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _lies(INDEX)
        cls.app = _lies(APP)
        cls.board_js = _lies(os.path.join(ROOT, "assets", "player_board.js"))

    def test_einstiegspunkt_heisst_in_allen_dreien_gleich(self):
        self.assertIn("function mountPlayerBoard(", self.board_js)
        self.assertIn("mountPlayerBoard(payload, rumpf)", self.app)
        self.assertIn('src="assets/player_board.js"', self.index)

    def test_keine_editorial_palette_mehr(self):
        """Die alte Fassung war warmes Off-White mit Terracotta und einem
        systemfremden Violett -- genau die verworfene Linie.
        """
        verboten = ["#D85A30", "#993C1D", "#534AB7", "#BA7517", "#f6f6f4",
                    "#e6e5e0", "#efeee9", "#FAECE7", "#E6F1FB", "#1D9E75"]
        for datei, name in (
            (self.board_js, "player_board.js"),
            (_lies(os.path.join(ROOT, "assets", "player_board.css")), "player_board.css"),
            (_lies(os.path.join(ROOT, "analysis", "wm_player_ratings.py")), "wm_player_ratings.py"),
        ):
            gefunden = sorted(f for f in verboten if f in datei)
            with self.subTest(datei=name):
                self.assertEqual([], gefunden, f"{name}: {gefunden}")

    def test_standalone_board_bleibt_self_contained(self):
        import sys

        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        import wm_player_ratings

        markup = wm_player_ratings.render_html(wm_player_ratings.build())
        self.assertNotIn("<link", markup)
        self.assertNotIn('src="assets/', markup)
        self.assertIn("function mountPlayerBoard(", markup)
        self.assertIn("--acc:", markup, "tokens.css wurde nicht eingebettet")
        self.assertIn(".player-board", markup, "player_board.css wurde nicht eingebettet")
        self.assertNotIn("http://", markup)
        self.assertNotIn("https://", markup)

    def test_gescopte_klassen_kollidieren_nicht_mit_dem_dashboard(self):
        """`.grid`, `.bar` und `.meta` gibt es im Dashboard bereits mit
        anderer Bedeutung. Das Board benutzt darum eigene Namen bzw. ist
        durchgaengig unter `.player-board` gescopt.
        """
        css = _lies(os.path.join(ROOT, "assets", "player_board.css"))
        for zeile in css.splitlines():
            zeile = zeile.strip()
            if not zeile or zeile.startswith(("/*", "*", "-", "}")) or "{" not in zeile:
                continue
            selektor = zeile.split("{")[0].strip()
            with self.subTest(selektor=selektor):
                self.assertTrue(
                    selektor.startswith(".player-board"),
                    f"Selektor '{selektor}' ist nicht gescopt und kann ins "
                    f"Dashboard durchschlagen",
                )


if __name__ == "__main__":
    unittest.main()
