# Kostenlose Datenquellen und Fallbacks

## Fixtures

- FIFA-Spielplan als Referenz
- `openfootball/worldcup` als frei abrufbarer Fixture-Seed
- Lokaler Fallback: `data/fixtures.json`

## KO-Bracket

- FIFA World Cup 2026 Regulations als offizielle Quelle fuer Round-of-32,
  Achtelfinale, Viertelfinale, Halbfinale und Finale.
- FIFA-Knockout-Bracket-Seite als oeffentliche Referenz fuer die
  Round-of-32-Slots und die Pools der besten Drittplatzierten.
- `data/bracket_2026.json` enthaelt die offiziellen Matchnummern und
  Pfade plus die 495 Annexe-C-Kombinationen fuer beste Drittplatzierte.
  Die maschinenlesbare 495er-Tabelle stammt aus einem frei sichtbaren
  Mirror und wird gegen Spalten, Rowcount und Slotgruppen validiert.

## News und Team-Intelligence

Prioritaet haben offizielle und frei erreichbare Quellen:

- FIFA und Turnierseiten
- Nationale Verbaende und Teamkanaele
- Frei erreichbare Medienartikel
- RSS-Suchen und GDELT
- Manuelle Notizen in `data/manual_news.json`

Aktive RSS-Quellen sind BBC, ESPN, Kicker, SkySports, 90min,
FourFourTwo, Inside World Football, World Soccer und seit 2026-05-19
der offizielle Canada-Soccer-Feed. Der RSS-Adapter sendet einen
Browser-aehnlichen User-Agent, weil einige freie WordPress-Feeds
sonst fuer Python-urllib 403 liefern. Weitere Verbandsfeeds bleiben
Watch-Kandidaten: US Soccer war per 403 geblockt, TheFA lieferte HTML
statt RSS, DFB und ScottishFA lieferten 404 fuer getestete RSS-Pfade.
We Global Football ist als nationalteamnaher Analyse-Feed dokumentiert,
aber nicht im Default-Refresh, weil der Feed aktuell stale ist.

`data/team_intel_sources.json` katalogisiert zusaetzlich freie Watch-Ziele:
offizielle Verbandsseiten fuer 48/48 Fixture-Teams, FIFA
Scores/Fixtures als Matchday-Lineup-Ziel, FotMob als nicht-offiziellen
Lineup-Crosscheck sowie offizielle Wetterquellen fuer USA, Kanada und
Mexiko. Der CLI-Befehl `team-intel-report` fasst Status, Teamabdeckung,
Reachability, Freshness und Host-Kontext zusammen; das Dashboard zeigt
diese Quelle im News-Radar. `refresh-team-intel-sources` prueft
kostenlose Reachability per `curl` und speichert HTTP-Status,
Effective-URL, Content-Type und Diagnose; gezielte Rechecks laufen ueber
`--statuses` und `--ids`. Stand 2026-05-20: 47 `active_page`,
1 `active_rss`, 1 `active_json`, 6 `blocked_curl_manual_watch`,
1 `manual_watch_unverified` (Iran/FFIRI Timeout). FIFA News, Canada
Soccer men's page, U.S. Soccer USMNT und Mi Seleccion wurden beim
Recheck auf `active_page` promotet. Mexiko hat mit
`mexico_miseleccion_json` zusaetzlich offizielle JSON-Endpunkte fuer
Kalender, News, Medien und Kaderlisten; die verbleibenden Browser-/
Manual-Quellen plus Iran dokumentieren verworfene Ersatzpfade in
`machine_readability_decision`. `team-intel-checklist` exportiert
chronologisch 72 Spieltagszeilen fuer Reise, Wetter, Pitch, erwartete
Lineups, finale Wetterpruefung und bestaetigte Lineups. Neue
Verbandsseiten ohne Live-Probe bleiben `manual_watch_unverified`, bis
sie kostenlos erreichbar verifiziert sind.

`matchday-command` buendelt diese Quellen operativ: pro Spiel werden
Watchlist-Status, Tipp, faellige/naechste Checks und direkte
Quellenlinks in `data/matchday_command_center.json` und
`exports/matchday_command_center.md` zusammengefuehrt. Manuelle
Pruefstaende liegen getrennt in `data/matchday_command_state.json`,
damit Quellen- und Tippdaten reproduzierbar bleiben.

Verifizierte Turnierausfaelle und Kader-Exclusions koennen in
`data/manual_news.json` ein `effective_until` bis zum Turnierende
bekommen. Tracking-Parameter in RSS-URLs werden beim Dedupe ignoriert,
damit manuelle kanonische Quellen nicht doppelt neben Feed-Items stehen.

Kategorien:

- Verletzung
- Erkrankung
- Sperre
- Form
- Trainerentscheidung
- Kader
- erwartete Aufstellung
- bestaetigte Aufstellung
- Wetter
- Reise
- Spielort/Pitch

## Hitze/WBGT und Kontext

Heat-Stress ist kein normales News-Item, sondern ein Spielkontextsignal
pro Fixture. Die Pipeline fuehrt fuer jedes Stadion einen kostenlosen
WBGT-Prior aus frei erreichbaren Heat-Stress-Analysen und kann ihn
spaeter durch Matchday-Wetter ersetzen.

- Quellenanker: SportRxiv-Preprint zu WM-2026-Umweltstress,
  World-Weather-Attribution/FIFPRO-Heat-Reporting, frei erreichbare
  Bloomberg-/NPR-artige WBGT-Auswertungen und Open-Meteo/amtliche
  Wetterquellen im Matchday-Check.
- Modellfelder: `estimated_wbgt_c`, `effective_wbgt_c`,
  `ambient_risk`, `risk`, `air_conditioned`, Team-Adaptation und
  kleine `home_xg_delta`/`away_xg_delta`.
- Schwellen: ab 24C WBGT `elevated`, ab 26C `moderate`/Cooling-Break-
  Watch, ab 28C `high`/Postponement-Watch. Klimatisierte Stadien werden
  aktuell mit 17.6C effektivem WBGT modelliert, behalten aber den
  Ambient-Hinweis fuer Watchlist und Quellenarbeit.
- Quantitative Nutzung: hohe Hitze senkt vorsichtig das Spieltempo und
  verschiebt die relative Chance leicht zugunsten besser hitzeangepasster
  Teams. Dieser Effekt ist capped und bleibt im Dashboard-Drilldown als
  `heat_effect` sichtbar.

## Teamstaerke

- FIFA/Coca-Cola Men's World Ranking als kostenloser Ranking-Anker
- World-Football-Elo via frei erreichbarer Elo-Tabelle als Spielstaerke-Anker
- Form-/Quali-Notizen als kleine, explizite Anpassungen in `data/team_strength_inputs.json`
- Spielerpool-Proxy aus `data/player_pool.json` als kleine, gecappte
  xG-Anpassung fuer aktuelle Scorer-Tiefe und Topscorer-Abhaengigkeit
- Generierter Modell-Input: `data/team_strength.json`

Die Modellstaerke wird reproduzierbar gebaut, nicht manuell geraten: World-Elo dominiert, FIFA-Rang kalibriert, kleine Form-/Quali-Adjustments bleiben sichtbar.

## Bonus / Gruppensieger

- Gruppensieger A-L werden aus derselben kostenlosen WM-2026-
  Turniersimulation abgeleitet, die auch Weltmeister- und
  Halbfinalistenwahrscheinlichkeiten liefert.
- Die Simulation nutzt die 72 Gruppenspiele aus `data/fixtures.json`,
  Teamstaerken aus `data/team_strength.json`, Poisson-Score-Sampling,
  FIFA-2026-Gruppenqualifikation mit besten Drittplatzierten und die
  offiziellen KO-Slots aus `data/bracket_2026.json`.
- Die Ergebnisse stehen in `bonus.group_winners` als Mapping von Gruppe
  zu Team-Wahrscheinlichkeit und werden im Dashboard-Bonus-Tab sowie in
  Tipprunden mit Gruppensieger-Bonusfrage genutzt.

## Quoten und Marktsignale

Quellen sind austauschbar:

- Bwin/Bet&Win oder Quotenvergleich per manuellem CSV
- Betano-World-Cup-Seite als frei lesbarer Bootstrap fuer 2026-Matchquoten, wenn ohne Login abrufbar
- bet365-World-Cup-Seite als frei lesbare Matchquoten-Quelle; US/American Odds werden in Decimal Odds umgerechnet
- Bwin.de-World-Cup-Seite als frei lesbare Matchquoten-Quelle mit Decimal Odds; aktueller Stand 2026-05-19: 24 sichtbare Spiele, 21 Gesamtwetten, 1 Spezialmarkt. Die freie Bwin-CDS-`fixture-view`-API liefert fuer die sichtbaren Eventseiten den Markt `Genaues Ergebnis - regulaere Spielzeit`, wenn public access id, `lang=de`, `country=DE` und `userCountry=DE` gesetzt sind. `data/manual_exact_score_odds.json` enthaelt 24/24 sichtbare Bwin-Eventseiten mit 596 expliziten Exact-Score-Preisen. Exact-Score ist im Dashboard sichtbar, bleibt aber wegen fehlendem freien historischen Exact-Score-Snapshot-Datensatz ein Watch-/Gegencheck-Signal und veraendert Tipps nicht direkt. `data/exact_score_calibration_sources.json` dokumentiert den Stand 2026-05-20: 6 Kandidaten gesucht, 0 akzeptiert.
- Bwin.de-Gesamtwetten fuer Bonusfragen: Weltmeister und Halbfinalisten sind direkt nutzbar; "Top Team Goalscorer" ist ein Spieler-pro-Team-Markt und deshalb nicht identisch mit der Kicktipp-Bonusfrage "Mannschaft mit Torschuetzenkoenig".
- PokerStars-Sports-World-Cup-Seite als frei lesbare Matchquoten-Liste, wenn Spiele dort bereits bepreist sind
- SportyTrader-World-Cup-Seite als frei lesbarer Best-Odds-Vergleich fuer alle 72 Gruppenspiele. Diese Quelle ist kein einzelner Buchmacher; Unterrounds sind moeglich, weil 1/X/2 aus unterschiedlichen Bestpreisen stammen koennen.
- WinComparator-World-Cup-Seite als frei lesbarer Predictions-/Best-Odds-Vergleich fuer aktuell sichtbare WM-2026-Matchmaerkte. Wird zur Corroboration bisheriger SportyTrader-only-Spiele genutzt; Unterrounds sind wie bei Vergleichsseiten moeglich.
- Oddschecker-US-World-Cup-Seite als frei lesbarer Best-Odds-Vergleich fuer aktuell sichtbare WM-2026-Matchmaerkte. US/American Odds werden in Decimal Odds umgerechnet; Unterrounds sind wie bei Vergleichsseiten moeglich.
- Odds.School-FIFA-World-Cup-Seite als frei lesbarer Odds-Analyse- und Best-Odds-Vergleich fuer aktuell sichtbare WM-2026-Matchmaerkte. Wird zur Corroboration bisheriger Single-Source-Spiele genutzt; Unterrounds sind wie bei Vergleichsseiten moeglich.
- BetVictor-World-Cup-Seite als zweite frei lesbare Matchquoten-Quelle
- talkSPORT-BET-World-Cup-Seite als dritte frei lesbare Quelle, aber nur fuer corroborierte Preise bzw. nach Ausreisserpruefung
- TipsterArea-Datumsseiten fuer historische Backtests; die dortigen Werte sind als Pre-Match-Durchschnittsquoten mehrerer Buchmacher gekennzeichnet
- Kostenlose Odds-APIs, falls ohne Zahlung/Kreditkarte nutzbar
- Prediction Markets nur als Zusatzsignal, wenn frei lesbar und relevant

Breiter Spread, geringe Liquiditaet, veraltete Daten oder unklare Resolution fuehren zu `watch_only`.
Bei Matchquoten erzeugt die Pipeline pro Spiel einen no-vig-Konsens aus allen brauchbaren Quellen. Einzelquellen mit unplausiblem Overround oder klarer Abweichung gegen den Mehrquellen-Median werden nicht in den Konsens gemischt; sie bleiben im Rohdatenblick nachvollziehbar.
Der Coverage-Stand fuer alle 72 Gruppenspiele ist ueber `odds-report` und im Dashboard-Tab `Quoten & Maerkte` sichtbar.
Der Ablation-Report `backtest-report` nutzt TipsterArea-`pre_odds` nur
als 1X2-Baseline fuer einen daraus kalibrierten Score-Tipp. Er ist kein
Exact-Score-Markt-Backtest und darf deshalb nicht als Nachweis einer
Betting-Edge gelesen werden. Die aktuelle Odds-Scoreform nutzt die
1X2-Remiswahrscheinlichkeit, um die erwartete Torhoehe vorsichtig an
den Markt anzupassen; das Live-Ensemble mischt no-vig-Matchquoten mit
15% Gewicht bei. Diese beiden Kalibrierungsentscheidungen sind im
2010/2014/2018/2022-`backtest-report` und im Dashboard-Block
`Lohnt sich das?` sichtbar.
Der neue `market_score_v1`-Kalibrator unterstuetzt ausserdem Over/Under,
BTTS und Handicap als Scoreline-Constraints. Der Import nutzt dafuer
CheckBestOdds-Archivseiten als freie historische Zusatzmarktquelle:
Archivseiten listen historische 1X2-Best-Odds und die Matchseiten liefern
per frei sichtbarem `xajax`-Nachlade-POST Over/Under-, BTTS- und
Asian-Handicap-Tabellen, soweit vorhanden. Importstand 2026-06-07:
107 importierte Spiele (2018=43, 2022=64), davon 105 auf den aktuellen
WM-Backtest gemappt; `over_under=105`, `btts=105`, `handicap=105` im
Report. Die zwei ungemappten Spiele sind Spiele um Platz 3. 2014 wird
bewusst abgelehnt, weil die Archiv-Matchlinks derzeit 404 liefern.
FCTables-Under/Over-Seiten sind ebenfalls abgelehnt, weil sie Statistik
und keine Pre-Match-Quoten sind.
Der Zusatzmarkt-Backtest bleibt backtest-only: `odds_market_score_v1`
holt aktuell +3 Punkte gegen die 1X2-only-Scoreform (351 vs 348 auf
189 Quoten-Spielen), aber noch keinen grossen genug validierten Vorteil,
um Live-Tipps automatisch zu veraendern.

## Spielerpool / Topscorer-Team

- `martj42/international_results` `goalscorers.csv` als CC0-Quelle fuer Nationalmannschafts-Torschuetzen.
- Lokaler Transform: `data/player_pool.json`.
- Filter: Spiele ab `2024-01-01`, keine Eigentore, nur WM-2026-Fixture-Teams bzw. dokumentierte Team-Aliasse.
- Modellwert: pro Team die Top-3-Torschuetzen, `goal_share` normalisiert auf die Summe der Top-3-Tore.
- Zusatzanker: offizielle FIFA-Kaderlisten und frei erreichbare
  Guardian-Player-Guides dienen als Rollen-, Kader- und Tiefencheck,
  wenn die Aussagen in lokale strukturierte Notizen/Overrides uebernommen
  werden. Lange Profiltexte werden nicht kopiert.
- Zweck: Bonusfrage "Mannschaft mit Torschuetzenkoenig" plus kleiner
  aktueller Scorer-Tiefen-Proxy fuer Spiel-xG; keine Klubwerte, keine
  Transfermarkt-Daten.

## Ausgeschlossen

- Bezahl-APIs
- Trials mit Kreditkarte
- Paywall-Daten
- Automatisches Wetten oder Trading
- Automatische Kicktipp-Eingabe
