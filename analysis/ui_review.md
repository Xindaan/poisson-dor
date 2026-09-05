# UI-Review Haupt-Dashboard — Design-System-Extraktion und Migrationsplan

**Datum:** 2026-07-21
**Umfang:** `index.html`, `assets/styles.css`, `assets/app.js` gegen den
Qualitaetsmassstab `analysis/wm_journey.py` (Pokalkurs) und
`analysis/pool_review_render.py` (Pool-Review).
**Status:** Analyse + Plan. In diesem Lauf wurde **keine** Produktivdatei
geaendert.

## Verifikationsbasis — welche Tabs ich tatsaechlich gesehen habe

Dashboard lokal gestartet mit `serve-dashboard --port 8002` (via
`.claude/launch.json`-Config `dashboard`, nicht `http.server`).

| Tab | Screenshot | Struktur ausgelesen | Datenlage |
|---|---|---|---|
| Spiele | ja (1280px) | ja | 104 Predictions, voll |
| News-Radar | ja | ja | voll (56 Quellen, 15 kritische News) |
| Quoten & Maerkte | ja | ja | voll (103/104 Konsens) |
| Bonus | ja | ja | voll |
| Watchlist | ja | ja | voll, aber Fokus-Check-Liste **leer** ("Heute keine faelligen Fokus-Checks") |
| History | ja | ja | voll (94 Events) |
| Finale Tipps | ja | ja | voll (32 KO-Spiele) |
| Pipeline | ja (oberer Teil) | ja (`outerHTML` der Ein-Klick-Update-Sektion) | voll |

**Wichtige Einschraenkung:** Screenshots unterhalb des ersten Viewports
liefen im Preview-Pane ins Leere (weisse Flaeche trotz korrekt gesetztem
`scrollY`) — ein Werkzeugproblem, kein Seitenproblem. Fuer alles unterhalb
der Falz habe ich deshalb **Struktur-Auslesen** benutzt (`outerHTML`,
`getBoundingClientRect`, `getComputedStyle`, `document.styleSheets`). Das
betrifft konkret: die Ein-Klick-Update-Sektion im Pipeline-Tab, das
`.drill-grid` in History, und die Messung `#pipeline` = 9178 px Hoehe.

Zusaetzlich verifiziert: Viewport 820 px und 375 px (`resize_window`),
beide per Screenshot.

**Nicht gesehen, weil keine Daten:** die Fokus-Check-Zeilen im Matchday
Command Center (Liste ist heute leer — Leerzustand gesehen, Vollzustand
nicht), sowie der Fehlerpfad `app.js:133` (fehlende `dashboard.json`).

---

## A1 — Design-System der Referenz-Frontends (extrahiert)

Alle Zeilenangaben sind Quellzeilen der Generatoren. `wm_journey.py`
substituiert `__SITE_ACCENT__` zur Generierzeit (Zeile 45, 681); der
tatsaechlich ausgelieferte Wert in `analysis/site/index.html` ist
verifiziert `--acc:#34c759`.

### Farben

| Rolle | Pokalkurs (`wm_journey.py`) | Pool-Review (`pool_review_render.py`) | Empfehlung |
|---|---|---|---|
| Seitenhintergrund | `--bg:#fbfbfd` (:715) | `SURFACE = "#fcfcfb"` (:24) | **`#fbfbfd`** — neutral-kuehl, wie im Auftrag vorgegeben. `#fcfcfb` ist minimal warm (B < G). |
| Hintergrund 2 / Rille | `--bg2:#f1f1f4` (:715) | — (nutzt `#fff` auf `SURFACE`) | **`#f1f1f4`** uebernehmen; Pool-Review hat keine zweite Ebene, das Dashboard braucht sie (Toolbar, Chips, Code-Bloecke). |
| Kartenflaeche | `--card:#ffffff` (:715) | `#fff` literal (:559, 633, 668, 677) | **`#ffffff`** |
| Text primaer | `--ink:#1d1d1f` (:715) | `INK = "#0f1720"` (:25) | **`#1d1d1f`** (Apple-Neutral). `#0f1720` ist leicht blaustichig. |
| Text sekundaer | `--ink2:#3c3c43` (:715) | — | **`#3c3c43`** |
| Text gedaempft | `--muted:#6e6e73` (:715) | `MUTED = "#6b7280"` (:26) | **`#6e6e73`** (gleiche Familie wie `--ink`) |
| Text sehr blass | `--faint:#a5a5ac` (:715) | — | **`#a5a5ac`** |
| Haarlinie | `--line:#e6e6ea` (:716) | `HAIRLINE = "#e6e7e4"` (:27) | **`#e6e6ea`** |
| Haarlinie innen | `--line2:#efeff2` (:716) | `#dcdedb` nur in `thead th` (:588) | **`#efeff2`** |
| **Akzent (Fuellung)** | `--acc:#34c759` (:717, Default :45) | `ACCENT = "#059669"` (:28) | **Widerspruch — siehe offene Frage F1.** Empfehlung: `#059669`. |
| **Akzent (Text/Link)** | `--acc-d:#1f8f3c` (:717) | `ACCENT_DEEP = "#047857"` (:29) | **`#047857`** (siehe F1) |
| Akzent weich | `--acc-soft:#e6f8ec` (:717) | `rgba(5,150,105,.06 / .10 / .13)` (:652, 685, 595) | **`#e6f8ec`** als Token + `rgba(5,150,105,.10)` als Hover/Fill-Variante |
| Blau (semantisch) | `--blue:#007aff` / `-soft:#e6f0ff` / `-d:#0a62cc` (:718) | — | uebernehmen |
| Amber (semantisch) | `--amber:#ff9500` / `-soft:#fff1dc` / `-d:#a25e00` (:719) | — | uebernehmen |
| Rot (semantisch) | `--red:#ff3b30` / `-soft:#ffe6e4` / `-d:#bf271e` (:720) | — | uebernehmen |
| Gold (semantisch) | `--gold:#c39214` / `-soft:#faf1d6` (:721) | — | uebernehmen |
| Sequentielle Rampe | — | `RAMP` 6-stufig `#f3f4f2 … #0f7d5d` (:33) | uebernehmen fuer Wahrscheinlichkeits-/Heat-Darstellung |

Beide nutzen konsequent das Muster **Basis / -soft (Fuellung) / -d (Text)**
je Semantikfarbe. Das ist der wichtigste strukturelle Unterschied zum
Dashboard, das pro Farbe nur einen Wert hat.

### Typografie

| Token | Pokalkurs | Pool-Review | Empfehlung |
|---|---|---|---|
| Schriftstack | `-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Segoe UI",system-ui,Roboto,sans-serif` (:731) | `-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif` (:535) | **Pokalkurs-Stack** (enthaelt SF Pro Display + `system-ui`) |
| Basisgroesse | `15px` (:732) | `17px` (:536) | **`15px`** — das Dashboard ist ein dichtes Arbeitswerkzeug wie Pokalkurs, kein Lesestueck wie Pool-Review |
| Zeilenhoehe | `1.5` (:732) | `1.55` (:536) | **`1.5`** |
| Ziffern | `font-variant-numeric:tabular-nums` (:733) | dito (:537) | uebernehmen — beide, ohne Ausnahme |
| Glaettung | `-webkit-font-smoothing:antialiased` (:732) | dito (:536) | uebernehmen |
| Ueberschrift-Gewicht | `800` (:735) | `640` (:539) | **`800`** fuer Zahlen/KPI, `700` fuer Karten-Titel — Pool-Review ist bewusst leiser (Editorial-Naehe), das Dashboard braucht Signal |
| Ueberschrift-Tracking | `-.022em` (:735), Hero `-.04em` (:760), Sektion `-.03em` (:769) | `-0.022em` (:539), Hero `-0.038em` (:556) | **identisch** — `-.022em` Basis, `-.03em`/`-.04em` bei grossen Graden |
| Fliesstitel-Skala | `h1 clamp(38px,8.5vw,76px)` (:760); `h2 clamp(23px,4vw,30px)` (:769); `.kpi .num 44px` (:778); `.hcard .m 19px` (:791) | `h2 clamp(24px,5vw,34px)` (:540); `h3 22px` (:541); `.mine-score .big 38px` (:641); `.card-v 26px` (:648) | Stufen: **34/26/19/15/13/12/11.5** + KPI-Grad **44** |
| Label/Eyebrow | 11.5–12px, `font-weight:700`, `letter-spacing:.02em`, uppercase (:777, 786, 799) | 12–13px, `font-weight:620`, `letter-spacing:.05–.16em`, uppercase (:554, 638, 646) | **12px / 700 / `.06em` / uppercase** |

### Spacing

Beide Generatoren definieren **keine** Spacing-Token — sie schreiben
Literale. Die faktisch verwendeten Cluster:

- Pokalkurs: `2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 22, 26, 34` (z.B. :736, 741, 757, 773, 774)
- Pool-Review: `6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 44, 48, 56, 64` (z.B. :538, 545, 549, 633, 667)

**Empfehlung:** eine 4er-Leiter als *neue* Token einfuehren
(`--s1:4 --s2:8 --s3:12 --s4:16 --s5:20 --s6:26 --s7:34 --s8:56`) — das ist
kein Neuentwurf, sondern eine Regularisierung der bereits vorhandenen
Cluster. Als offene Frage F4 vorgelegt, weil es der einzige Punkt ist, an
dem ich etwas einfuehre, das in der Referenz so nicht existiert.

Container: Pokalkurs `max-width:1120px; padding:0 18px` (:736);
Pool-Review `max-width:1080px; padding:0 20px` (:538). Empfehlung
**1120/18** (mehr Spalten noetig).

### Radien

| Stufe | Pokalkurs | Pool-Review | Empfehlung |
|---|---|---|---|
| gross (Sektionskarte) | `--r3:24px` (:725) | `22px` (`.mine` :633, `.mine-empty` :627) | **`--r3:22px`** |
| Standard (Karte) | `--r:18px` (:725) | `18px` (`.award` :668, `.spot` :677, `.h2h-score` :704) | **`--r:18px`** — beide einig |
| klein (Kachel/Zeile) | `--r2:13px` (:725) | `14px` (`.card` :645, `.quota` :652), `12px` (`.note` :664, `select` :700) | **`--r2:13px`** |
| Mikro (Score-Chip) | `7–9px` (:804, 843, 883, 892) | — | **`--r1:8px`** |
| Pille | `980px` (:748, 759, 765, 855) | `999px` (:573, 685) | **`999px`** |

### Schatten

| Stufe | Pokalkurs | Pool-Review | Empfehlung |
|---|---|---|---|
| sm (Ruhe) | `--sh-sm:0 .5px 1.5px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.05)` (:722) | `0 1px 2px rgba(16,24,32,.04)` (:559, 634) | **Pokalkurs `--sh-sm`** (zweilagig, feiner) |
| md (Hover/aktiv) | `--sh:0 1px 2px rgba(0,0,0,.04),0 8px 22px rgba(0,0,0,.06)` (:723) | — | uebernehmen |
| lg (Overlay) | `--sh-lg:0 2px 8px rgba(0,0,0,.05),0 22px 50px rgba(0,0,0,.1)` (:724) | `0 12px 40px rgba(16,24,32,.16)` (`#pop` :883) | **Pokalkurs `--sh-lg`** |

Kernregel beider: **Karten in Ruhe tragen `sh-sm`, nicht `sh`.** Der grosse
Schatten ist Hover- bzw. Overlay-Zustand.

### Breakpoints

- Pokalkurs: `max-width:560px` (:912, 946), `min-width:560px` (:871, 875)
- Pool-Review: `max-width:640px` (:718)
- Empfehlung: **560px** (Dichte/Mobil) + **860px** (Layout-Kollaps, bereits
  im Dashboard vorhanden). Beides, nicht eins.

### Motion

| Aspekt | Pokalkurs | Pool-Review |
|---|---|---|
| Standarddauer | `.15s` / `.16s` (:748, 775, 856, 901) | `.18s ease` (:576, 678) |
| Eintritts-Animation | `@keyframes rise .4s cubic-bezier(.2,.7,.2,1)` (:752, 754) | — |
| Hover-Geste | `transform:translateY(-1px … -2px)` + Schatten-Wechsel (:776, 857, 902) | Schatten/Farbe |
| Reduced Motion | — | `@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}` (:734) |

**Empfehlung:** Dauern und Hover-Geste von Pokalkurs, den
`prefers-reduced-motion`-Guard von Pool-Review. Beide Generatoren zusammen
ergeben erst das vollstaendige Muster.

### Komponenten-Muster

| Muster | Pokalkurs | Pool-Review | Kern |
|---|---|---|---|
| **Sticky-Topbar** | `.topbar` `position:sticky;top:0;z-index:30;background:rgba(251,251,253,.8);backdrop-filter:blur(18px) saturate(1.4);border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top)` (:739-741) | `.picker` `position:sticky;top:0;z-index:40;background:rgba(252,252,251,.86);backdrop-filter:saturate(180%) blur(14px)` (:566-567) | Navigation bleibt **immer** erreichbar, halbtransparent + Blur |
| **Pill-Nav** | `nav button` transparent/`--muted`, `border-radius:980px`, `padding:8px 13px`, `min-height:38px`, `transition:.16s`; aktiv `.on{color:#fff;background:var(--ink)}` (:747-750) | `.chip` `border-radius:999px`, `min-height:40px`, `padding:9px 15px`, `transition:.18s`; aktiv `[aria-pressed=true]{background:ACCENT_DEEP;color:#fff}` (:573-577) | randlose Pille, Zustand ueber Fuellung. **Aktivfarbe divergiert (F2).** |
| **KPI-Karte** | `.kpi` Karte + `sh-sm` + Hover-Lift; `.lab` 12px/600/muted, `.num` **44px/800/-.04em**, `.sub` 12.5px/muted; Varianten `.kpi.acc`, `.kpi.warn` faerben nur die Zahl (:773-781) | `.card`/`.card-k`/`.card-v` 12px-Label + **26px/680** Wert (:645-649); `.quota` als weich gefuellte Variante (:652-655) | Label klein/leise **ueber** grosser Zahl; Farbe nur auf der Zahl |
| **Chip / Badge** | `.pill` (Karte+Rand+`sh-sm`+Punkt, :764-766), `.tg` (`--bg2`-Fuellung, :795-796) | `.sp-badge` (`rgba(5,150,105,.10)`-Fuellung + `ACCENT_DEEP`-Text, :684-685) | **weiche Fuellung + kraeftiger Text**, nicht Rand-mit-Farbe |
| **Bottom-Sheet / Popover** | `.pickwrap` fixed + `rgba(20,20,30,.34)` + `backdrop-filter:blur(2px)`, `.pickcard` `border-radius:22px 22px 0 0`, `max-height:78vh`, ab 560px zentriert (:869-878) | `#pop` fixed unten, `width:min(560px,100vw-32px)`, `--sh-lg`, `max-height:60vh` (:881-883) | Detail *ueber* der Seite statt inline |
| **Heatmap-Tabelle** | — | `.heat` `min-width:640px`; `th[scope=row]` `position:sticky;left:0`; `td` `text-align:center` + `border-bottom/right:2px solid SURFACE` als Gutter; Zeilen-Highlight per `outline` (:596-604) | sticky Zeilenkopf + Farbflaechen mit Luft |
| **Tabelle allgemein** | `th` 10.5px uppercase `.03em` `--faint` rechtsbuendig, `td` `border-top:1px solid var(--line2)` rechtsbuendig, `td.l` linksbuendig, `td.pts` 800 (:829-837) | `th,td` `padding:10px 12px`, `thead th` 12px uppercase `.06em` muted, `.num` rechtsbuendig + tabular (:585-592) | Zahlen rechts, Text links, Kopf leise und klein |
| **Funnel-/Rail-Nav** | `.rail`/`.rnode` scrollbare Knotenreihe, `scrollbar-width:none` (:898-911) | `.chips` mit `scrollbar-width:none` (:571-572) | horizontale Scroller **ohne** sichtbare Scrollbar |

---

## A2 — Ist-Zustand `assets/styles.css` (gleiche Kategorien)

### Farben (`styles.css:1-14`)

| Rolle | Ist | Verhaeltnis zur Referenz |
|---|---|---|
| Hintergrund | `--bg:#f5f2ed` (:2) | **warmes Creme** — genau die im Auftrag verbotene Familie |
| Kartenflaeche | `--surface:#fffaf3` (:3) | warmes Off-White, nicht `#ffffff` |
| Flaeche 2 | `--surface-2:#eef6f4` (:4) | Mintgruen — semantisch belegt (Tipp-Boxen), nicht als neutrale zweite Ebene |
| Text | `--text:#1f2523` (:5) | einziger Textwert; **kein** `ink2`, **kein** `faint` |
| Gedaempft | `--muted:#68736f` (:6) | gruenstichig |
| Linie | `--line:#d9d2c6` (:7) | warmes Beige; **kein** `line2` |
| Akzent | `--accent:#0c7a6b` (:8) | Petrol/Teal, nicht Emerald |
| Akzent 2 | `--accent-2:#b24b37` (:9) | **Terracotta** — im Auftrag ausdruecklich verboten |
| Warn / Bad / Good | `--warn:#ad6a00` (:10), `--bad:#a83c3c` (:11), `--good:#256d44` (:12) | je **ein** Wert; keine `-soft`/`-d`-Varianten |
| Schatten | `--shadow:0 10px 28px rgba(44,35,25,.08)` (:13) | **ein** Wert, braun getoent, auf jeder Karte |
| Ausserhalb der Token | `#efe7dc` (`th` :362), `#cfe5df` (`.round-tip-grid div` :230), `#1f2523`/`#fffaf3` (`.command-output` :426-427), `#ffffff` (`.prob` :308), `#fff` (`.drill-grid section` :401) | 5 hartcodierte Werte |

### Typografie

| Aspekt | Ist | Referenz |
|---|---|---|
| Schriftstack | `Inter, ui-sans-serif, system-ui, -apple-system, …` (:24) | **`Inter` ist im Auftrag verboten** und steht hier *vor* `-apple-system` |
| Basisgroesse | nicht gesetzt → **16px** (gemessen) | 15px |
| Zeilenhoehe | nicht gesetzt → **`normal`** (gemessen, ≈1.2) | 1.5 |
| `tabular-nums` | **nicht gesetzt** (gemessen: `normal`) | ueberall gesetzt |
| Tracking | `letter-spacing: 0` explizit auf `.eyebrow` (:43), `h1` (:49), `.card h2/h3` (:202), `th` (:365) | `-.022em` bis `-.04em` bzw. `+.02em` bei Labels |
| Grade | `h1 32px` (:47), `.card h2/h3 18px` (:201), `.metric b 18px` (:68), `.round-tip-grid b 26px` (:243), `.prob b 18px` (:319) | KPI-Grad 44px, Titel bis 34px |

### Spacing / Radien / Schatten / Breakpoints / Motion

| Aspekt | Ist | Referenz |
|---|---|---|
| Spacing-Token | keine; Literale `6,8,10,11,12,14,16,18,22,28,32,40` | keine Token, aber breitere Leiter |
| Radien | **`8px` fuer praktisch alles** (:63, 102, 119, 169, 193, 231, 279, 307, 343, 375, 400) + `999px` (Badge :251) + `6px` (`.card__toggle` :474) | 4-stufige Skala + Pille |
| Schatten | **ein** `--shadow`, identisch auf `.card` (:195) und `.table-wrap` (:344) | 3-stufig, Ruhe = `sh-sm` |
| Breakpoints | **`max-width:860px`** — einziger (:432) | 560 (+640) |
| Transitions | **null** im gesamten Stylesheet (verifiziert per grep) | `.15–.18s` durchgaengig |
| `:focus` / `:focus-visible` | **null** Regeln (verifiziert per grep) | ebenfalls keine — aber das Dashboard hat zusaetzlich gar keine ARIA-Struktur |
| `:hover` | **eine** Regel, `#markets .card__toggle:hover` (:480) | durchgaengig |
| `prefers-reduced-motion` | keine | Pool-Review `:734` |
| Container | kein `max-width`; `main{padding:18px 32px 40px}` (:145-147) | 1080–1120px zentriert |
| Sticky | keine | Topbar in beiden |
| `env(safe-area-inset-*)` | keine | Pokalkurs `:736, 740, 874` |

### Komponenten — Gegenueberstellung

| Muster | Referenz | Dashboard Ist |
|---|---|---|
| Topbar | sticky + Blur | `.app-header` statisch, scrollt weg (:27-35) |
| Nav | randlose Pille 980/999px | `.tab` umrandete 8px-Box, aktiv = Akzentfuellung (:96-111) |
| KPI | Label klein ueber **44px**-Zahl | `.metric` Zahl **18px** (:66-69) |
| Chip | weiche Fuellung + kraeftiger Text | `.badge` weisse Flaeche + 32%-Alpha-Rand (:246-271) |
| Popover | Bottom-Sheet / `#pop` | `<details>` inline (:380-388) |
| Tabelle | Zahlen rechts, sticky Kopf, Gutter | eine Formatierung fuer alles, `min-width:720px` global (:347-366) |
| Scroller | `scrollbar-width:none` | `.tabs{overflow-x:auto}` ohne (:92) |
| Code/Terminal | — | `.command-output` **dunkel** `#1f2523` (:420-430) |

---

## A3 — Review-Befunde

Meldedisziplin wie beauftragt: **alles**, auch Unsicheres und Geringfuegiges.
Priorisierung erfolgt erst in B.

### 1 — Header / Kopfzeile

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-01 | Farbwelt ist warmes Creme (`#f5f2ed` / `#fffaf3`) statt neutral-kuehlem `#fbfbfd`; der Header legt zusaetzlich einen Creme-Verlauf darueber | `assets/styles.css:2-3`, `:34` vs `analysis/wm_journey.py:715` | hoch | sicher | nein |
| R-02 | Header ist statisch und scrollt weg. Kein `position:sticky`, kein `backdrop-filter`. Im Pipeline-Tab (gemessen 9178 px Panelhoehe) verliert man Titel **und** Tabs vollstaendig | `assets/styles.css:27-35` vs `analysis/wm_journey.py:739-741`, `analysis/pool_review_render.py:566-567` | hoch | sicher | nein |
| R-03 | `h1` 32px mit `letter-spacing:0`; die Referenz skaliert responsiv und zieht das Tracking auf `-.04em` zusammen | `assets/styles.css:46-50` vs `analysis/wm_journey.py:760` | mittel | sicher | nein |
| R-04 | `.eyebrow` ist blanker uppercase-Text; in beiden Referenzen ist der Eyebrow eine gefuellte Pille (`acc-soft` bzw. `kicker` mit `.16em`) | `assets/styles.css:37-44` vs `analysis/wm_journey.py:758-759`, `analysis/pool_review_render.py:554-555` | niedrig | sicher | nein |
| R-05 | `.status-strip{min-width:440px}` erzwingt einen frueheren Umbruch, als das Layout braucht; feste 4 Spalten statt `auto-fit` | `assets/styles.css:52-57` vs `analysis/wm_journey.py:773` | mittel | sicher | nein |
| R-06 | Die vier Kopf-KPIs stehen in **18px** — sie lesen sich nicht als Kennzahlen. Referenz-KPI ist 44px/800/`-.04em` | `assets/styles.css:66-69`, Markup `assets/app.js:173` vs `analysis/wm_journey.py:778` | hoch | sicher | ja |

### 2 — Tab-Navigation

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-07 | Tabs sind umrandete 8px-Boxen; die Referenz nutzt randlose Pillen (980/999px) mit Fuellung als Zustand | `assets/styles.css:96-105` vs `analysis/wm_journey.py:747-750` | hoch | sicher | nein |
| R-08 | Aktiver Tab wird mit dem **Akzent** gefuellt. Pokalkurs faerbt aktive Nav mit `--ink` und haelt den Akzent fuer Datenaussagen frei — hier wird der einzige Akzent dekorativ verbraucht | `assets/styles.css:107-111` vs `analysis/wm_journey.py:750` | mittel | wahrscheinlich | nein |
| R-09 | Keine `transition` auf `.tab` (im gesamten Stylesheet null Transitions) | `assets/styles.css` (grep) vs `analysis/wm_journey.py:748` | niedrig | sicher | nein |
| R-10 | `.tabs{overflow-x:auto}` ohne `scrollbar-width:none` → bei 375 px liegt eine sichtbare graue Scrollbar unter der Tableiste (im Screenshot verifiziert) | `assets/styles.css:88-94` vs `analysis/wm_journey.py:745-746`, `analysis/pool_review_render.py:571-572` | mittel | sicher | nein |
| R-11 | Keine Tab-Semantik: `nav[aria-label]` ist da, aber `role="tablist"/"tab"/"tabpanel"`, `aria-selected` und `aria-controls` fehlen; die Panels sind `<section>` ohne `aria-labelledby` | `index.html:19-28`, `index.html:62-69` | mittel | sicher | nein |
| R-12 | Keine Pfeiltasten-Navigation zwischen Tabs (nur Tab-Taste). Kein Blocker, aber die Referenz-Chips haben wenigstens `aria-pressed` | `assets/app.js:1891-1901` vs `analysis/pool_review_render.py:744` | niedrig | sicher | ja |

### 3 — Tab „Spiele"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-13 | Karten-Radius 8px statt 18px; die gesamte Radienskala fehlt | `assets/styles.css:190-196` vs `analysis/wm_journey.py:725`, `:826` | mittel | sicher | nein |
| R-14 | Jede Karte traegt in Ruhe den **grossen** Schatten (`0 10px 28px`). Referenz: Ruhe = `sh-sm`, grosser Schatten nur im Hover | `assets/styles.css:195` vs `analysis/wm_journey.py:774-776` | mittel | sicher | nein |
| R-15 | Karten haben keinen Hover-Zustand und keine Lift-Geste | `assets/styles.css:190-196` vs `analysis/wm_journey.py:776` | niedrig | sicher | nein |
| R-16 | `.round-tip-grid div` hat `border:1px solid #cfe5df` — hartcodiert, ausserhalb jedes Tokens | `assets/styles.css:230` | niedrig | sicher | nein |
| R-17 | Die Tipp-Zahl (26px/800) ist groesser als der Kartentitel (18px). Vermutlich Absicht (der Tipp ist die Kernaussage), aber die Titelgroesse ist dann zu klein statt die Zahl zu gross | `assets/styles.css:241-244` vs `:198-203` | niedrig | unsicher | nein |
| R-18 | In `renderMatchCard` liegen Badge-Gruppen in `<div class="list">` — `.list` ist ein Grid, die inneren `<div>` strecken sich; die Top-Score-Badges brechen ohne echten Wrap-Container | `assets/app.js:362-365`, `assets/styles.css:322-325` | mittel | sicher | ja |
| R-19 | **`body` hat keine `line-height`** — gemessen `normal` (≈1.2). Die Erklaerungstexte (`assets/app.js:361`) sind dadurch spuerbar enger gesetzt als in beiden Referenzen (1.5 / 1.55). Das ist der groesste einzelne Lesbarkeitsunterschied | `assets/styles.css:20-25` (gemessen) vs `analysis/wm_journey.py:732`, `analysis/pool_review_render.py:536` | hoch | sicher | nein |
| R-20 | Kein `font-variant-numeric:tabular-nums` (gemessen `normal`) → Prozent- und EP-Spalten springen beim Neurendern | `assets/styles.css:20-25` vs `analysis/wm_journey.py:733`, `analysis/pool_review_render.py:537` | mittel | sicher | nein |

### 4 — Tab „News"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-21 | Die drei News-Filter (Schwere/Kategorie/Wirkung) werden **im Panel** erzeugt und stehen damit unter der globalen Toolbar — zwei uebereinanderliegende Filterleisten (im Screenshot verifiziert) | `assets/app.js:398-418`, `:561` vs `index.html:31-60` | mittel | sicher | ja |
| R-22 | `renderDataQuality` legt `<span class="badge">` **direkt** in `<div class="list">`. `.list` ist `display:grid` → jede Badge wird ein Grid-Item ueber die volle Breite. Verifiziert: „rss: ok (167/322 frisch)" als ~1500 px breite Pille | `assets/app.js:477`, `assets/styles.css:322-325`, `:246-256` | hoch | sicher | ja |
| R-23 | Tabellenkopf-Hintergrund `#efe7dc` ist ein hartcodiertes Warmbeige ohne Token; die Referenz laesst `th` transparent und macht ihn nur ueber Groesse/Farbe leise | `assets/styles.css:361-366` vs `analysis/wm_journey.py:830`, `analysis/pool_review_render.py:587-588` | mittel | sicher | nein |
| R-24 | Externe Links (`target=_blank`) sind nur ueber `a{color:var(--accent)}` markiert — keine Unterstreichung, kein Hover, kein externes Zeichen | `assets/app.js:557`, `assets/styles.css:368-370` vs `analysis/pool_review_render.py:563` | niedrig | sicher | ja |

### 5 — Tab „Quoten"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-25 | **Tabellen in Karten werden abgeschnitten.** `table{min-width:720px}` gilt global, die Karten sind aber `minmax(330px,1fr)` breit. Im Screenshot verifiziert: Spalte „KONSENS" endet mit abgeschnittenem `b…`, die naechste Kopfzelle ist nur noch als `R` sichtbar | `assets/styles.css:347-351`, `:184-188`, Markup `assets/app.js:845` | hoch | sicher | ja |
| R-26 | `#markets .card--clamp .card__body{max-height:19rem}` ist nicht nur Stil, sondern **Logik**: `clampMarketCards` entscheidet ueber `body.scrollHeight > body.clientHeight + 4`, ob der Aufklapp-Button erscheint. Eine Aenderung des Werts aendert das Verhalten | `assets/styles.css:465-468`, `assets/app.js:770-781` | mittel | sicher | ja |
| R-27 | `.card__toggle` nutzt `rem`-Padding und `border-radius:6px` — vierter Radienwert, bricht aus der 8px-Einheit aus | `assets/styles.css:469-479` | niedrig | sicher | nein |
| R-28 | Der Aufklapp-Button setzt nur `textContent` um; kein `aria-expanded`, kein Fokusstil | `assets/app.js:1914`, `assets/styles.css:469-483` | mittel | sicher | ja |

### 6 — Tab „Bonus"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-29 | Bonuszeilen sind `.line` mit `justify-content:space-between`; ohne `tabular-nums` und ohne feste Zahlenspalte flattert die Prozentspalte optisch (Screenshot: 16%/12%/6%/5% nicht buendig) | `assets/app.js:1348-1353`, `assets/styles.css:327-337` | mittel | sicher | ja |
| R-30 | Keine visuelle Kodierung der Wahrscheinlichkeit — nur Zahlen. Pool-Review hat dafuer die sequentielle `RAMP`, Rival-Lab die `.barmini` | `assets/app.js:1348-1367` vs `analysis/pool_review_render.py:33`, `analysis/rival_lab_render.py:93-94` | mittel | sicher | ja |
| R-31 | Die drei Bonus-Karten haben `h2` in derselben Groesse wie Karten-`h3` (18px) — keine Hierarchie zwischen Sektions- und Kartentitel | `assets/styles.css:198-203`, `assets/app.js:1350` | niedrig | sicher | nein |

### 7 — Tab „Watchlist"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-32 | `.metrics-row` ist starr `repeat(3, …)`; das Command Center liefert 5 Metriken → zwei Waisen in Zeile 2 (verifiziert). Referenz nutzt `auto-fit` | `assets/styles.css:77-82`, `assets/app.js:1388-1417` vs `analysis/wm_journey.py:773` | mittel | sicher | ja |
| R-33 | `.metric.compact{box-shadow:none}` — `.metric` hat gar keinen Schatten. Tote Regel | `assets/styles.css:59-64`, `:84-86` | niedrig | sicher | nein |
| R-34 | Leerzustaende nutzen einen **gestrichelten** Rahmen. In beiden Referenzen gibt es kein `dashed` — ein leerer Zustand sieht dadurch nach Fehler aus statt nach Ruhe (Pool-Review nutzt `dashed` nur einmal, fuer die aktive Aufforderung `.mine-empty`) | `assets/styles.css:372-378` vs `analysis/pool_review_render.py:626-627`, `:662` | niedrig | wahrscheinlich | nein |
| R-35 | Markup-Bug: im Matchday-Probelauf steht „offen · " mit haengendem Trenner, weil ein leeres Feld nicht gefiltert wird (im Screenshot verifiziert) | `assets/app.js:1437-1464` | niedrig | sicher | ja |

### 8 — Tab „History"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-36 | Der Filter „Ausloeser" steht zwischen Zusammenfassungskarte und Tabelle, ohne eigenen Container und ohne Abstand nach oben — er klebt an der Karte (verifiziert) | `assets/app.js:1565-1575`, `:1602` | mittel | sicher | ja |
| R-37 | Tabellenzeilen ohne Zebra, ohne Hover, Kopfzeile nicht sticky. Bei 94 Events scrollt der Kopf sofort weg | `assets/styles.css:339-366` vs `analysis/pool_review_render.py:597` | mittel | sicher | nein |
| R-38 | `.drilldown summary` ist akzentfarben **und** fett — optisch staerker als echte Links, die nur farbig sind | `assets/styles.css:384-388`, `:368-370` | niedrig | sicher | nein |
| R-39 | `.drill-grid` ist `repeat(2, minmax(260px,1fr))` und wird in einer Tabellenzelle gerendert (`renderHistoryDetails`). Minimum 2×260+12 = 532 px in einer Zelle, deren Breite nicht garantiert ist | `assets/styles.css:390-395`, `assets/app.js:1531`, `:1541` | mittel | wahrscheinlich | ja |

### 9 — Tab „Tipps"

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-40 | **32 KO-Spiele als volle Breitenpillen.** `listedBadges` legt `<span class="badge">` direkt in `.list` (Grid) → 32 Zeilen, jede eine ~1500 px breite Pille mit linksbuendigem Text (verifiziert). Gleiche Fehlerklasse wie R-22 | `assets/app.js:1641-1643`, `:1661`, `assets/styles.css:322-325` | hoch | sicher | ja |
| R-41 | Die Metrik „Beste Dritte" traegt den Wert `BDEFIJKL` im 18px-KPI-Slot — als Kennzahl unlesbar, gehoert als Chipreihe dargestellt | `assets/app.js:1650`, `:1655-1656` | niedrig | sicher | ja |
| R-42 | Die 7-spaltige Tipp-Tabelle nutzt `<br><span class="meta">` fuer Zweitzeilen; ausser `.meta` (13px) gibt es keine Sekundaertypo-Stufe | `assets/app.js:1677-1685`, `assets/styles.css:205-208` | mittel | sicher | ja |

### 10 — Tab „Pipeline" (inkl. Ein-Klick-Update)

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-43 | `.command-output` ist eine **dunkle** Flaeche (`#1f2523` auf `#fffaf3`-Text). Das ist der einzige Dark-Bereich der Anwendung und widerspricht der Vorgabe „kein Dark Mode in jeglicher Form" | `assets/styles.css:420-430`, Markup `assets/app.js:1818-1819` | hoch | sicher | ja |
| R-44 | `.command-output{max-width:520px}` ist fix — in der breiten Kommando-Tabellenzelle wird die Ausgabe unnoetig frueh umgebrochen bzw. abgeschnitten | `assets/styles.css:420-421`, `assets/app.js:1731` | mittel | sicher | ja |
| R-45 | Der Primaerbutton „Alles updaten" ist mit `min-height:32px` **kleiner** als Tabs (36px) und Formularfelder (38px). Referenz: `.btn{min-height:42px}`. Die wichtigste Aktion der Seite ist ihr kleinstes Bedienelement | `assets/styles.css:113-123`, Markup `assets/app.js:1802` vs `analysis/wm_journey.py:855-856` | hoch | sicher | nein |
| R-46 | Laufzustand nur ueber `disabled` + `opacity:.72` und den Text „Laeuft…". Kein Fortschritt, kein `aria-busy`, kein `aria-live` — ein `update-all` laeuft minutenlang ohne Rueckmeldung | `assets/styles.css:125-128`, `assets/app.js:1797-1799`, `:1833-1866` | mittel | sicher | ja |
| R-47 | Jeder Tastenanschlag im Suchfeld ruft `renderAll()` und rendert damit auch das Pipeline-Panel neu — gemessene Panelhoehe 9178 px, 45 Kommandozeilen mit `<pre>`-Bloecken | `assets/app.js:1919-1922`, `:1879-1889` | mittel | sicher | ja |
| R-48 | `.pipeline-primary` ist die einzige Stelle mit `border-top`-Trenner — Ad-hoc-Layout statt wiederverwendbarer Sektionskomponente | `assets/styles.css:130-143` | niedrig | sicher | nein |
| R-49 | Die Quality-Gate-Badges liegen wieder direkt in `.list` (`renderUpdateQuality`) → volle Breite, dritte Fundstelle derselben Klasse | `assets/app.js:1777-1780` | mittel | sicher | ja |

### 11 — Tabellen-Darstellung generell

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-50 | **Eine** Tabellenformatierung fuer alle sechs Tabellen: kein rechtsbuendiger Zahlensatz, kein `tabular-nums`, kein sticky Kopf, kein Zebra, kein Zeilen-Hover, `vertical-align:top` fuer alles | `assets/styles.css:347-366` vs `analysis/wm_journey.py:829-837`, `analysis/pool_review_render.py:585-604` | hoch | sicher | nein |
| R-51 | `table{min-width:720px}` gilt global und trifft damit auch Tabellen in Karten (siehe R-25). Der Wert gehoert an `.table-wrap table`, nicht an `table` | `assets/styles.css:347-351` | hoch | sicher | nein |
| R-52 | `.table-wrap` traegt denselben grossen Schatten wie eine Karte und wird dadurch optisch zur Karte, obwohl es nur ein Scroll-Container ist | `assets/styles.css:339-345` | niedrig | sicher | nein |

### 12 — Badge-/Status-Darstellung

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-53 | `.badge` ist weisse Flaeche + farbiger Text + Rand mit 32 % Alpha. Auf `--surface:#fffaf3` ist die weisse Flaeche kaum unterscheidbar. Die Referenz nutzt **weiche Fuellung** (`acc-soft`, `rgba(5,150,105,.10)`) mit kraeftigem Text | `assets/styles.css:246-271` vs `analysis/wm_journey.py:717-721`, `analysis/pool_review_render.py:684-685` | hoch | sicher | nein |
| R-54 | Drei Zustandsklassen (`stabil`/`volatil`/`warte`) tragen mindestens sieben verschiedene Semantiken: News-Schwere, Quoten-Coverage, CLI-Status, Quality-Gates, Artefakt-Existenz, KO-Slot-Status, Datenqualitaet. „warte auf Lineup" und „single_source" sehen identisch aus | `assets/app.js:55-78`, `:470`, `:177-181`, `:1642`, `:1771`, `:1787` | mittel | sicher | ja |
| R-55 | `--bad:#a83c3c` (Warnung) und `--accent-2:#b24b37` (Dekor der Quoten-Warnbox) liegen farblich sehr nah beieinander — Warnung und Dekoration verschmelzen | `assets/styles.css:9`, `:11`, `:273-292` | mittel | wahrscheinlich | nein |
| R-56 | `.badge` steckt an einer Stelle in einem `<b>` (`<b><span class="badge warte">…</span></b>`) — semantisch und typografisch doppelt gemoppelt | `assets/app.js:1645` | niedrig | sicher | ja |

### 13 — Lade-, Leer- und Fehlerzustaende

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-57 | Kein Ladezustand. Bis `loadData()` fertig ist, sind alle acht Panels leer — kein Skeleton, kein Spinner, kein Text | `assets/app.js:127-141` | mittel | sicher | ja |
| R-58 | Der Datenfehlerfall ersetzt das komplette `<main>` per `innerHTML`. Die Tabs bleiben stehen, zeigen danach aber ins Nichts, und die Toolbar ist mit weg | `assets/app.js:133` | mittel | sicher | ja |
| R-59 | Leerzustaende sind blanker Text in `.empty` — kein Icon, keine Handlungsaufforderung ausser im Datenfehlerfall | `assets/app.js:1875-1877`, `assets/styles.css:372-378` | niedrig | sicher | ja |
| R-60 | Kommando-Ergebnisse (`renderCommandResult`) erscheinen ohne `aria-live` — ein Screenreader bekommt vom Ausgang eines `update-all` nichts mit | `assets/app.js:1806-1825` | mittel | sicher | ja |

### 14 — Verhalten unter 860 px

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-61 | **Einziger Breakpoint.** `.metrics-row` (3 Spalten), `.prob-grid` (3 Spalten) und `.round-tip-grid` haben darunter keinerlei Anpassung. Bei 375 px verifiziert: `.metrics-row` bleibt dreispaltig, die vierte Metrik steht allein | `assets/styles.css:432-462`, `:77-82`, `:298-303` | hoch | sicher | nein |
| R-62 | Kein `env(safe-area-inset-*)` — auf iPhone mit Notch/Home-Indikator laeuft Inhalt unter die Systemflaechen. Pokalkurs behandelt das an drei Stellen | `index.html`, `assets/styles.css` (grep) vs `analysis/wm_journey.py:736`, `:740`, `:874` | mittel | sicher | nein |
| R-63 | `input,select{min-width:min(280px, calc(100vw - 36px))}` unter 860 px: die Suche nimmt fast die volle Breite, die Selects springen in eigene Zeilen — die Toolbar wird zum Stapel ohne Ordnung | `assets/styles.css:458-461`, `:149-155` | niedrig | sicher | nein |
| R-64 | Kein `<meta name="theme-color">`; Pokalkurs setzt es (plus `apple-mobile-web-app-*`) | `index.html:3-8` vs `analysis/wm_journey.py:707-711` | niedrig | sicher | nein |

### 15 — Fokus-Sichtbarkeit und Tastaturbedienbarkeit

| ID | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|
| R-65 | **Null `:focus`- oder `:focus-visible`-Regeln** im gesamten Stylesheet (per grep verifiziert). Es bleibt der Browser-Standardring, der auf Creme schwach steht. Anmerkung zur Fairness: auch die beiden Referenzen haben keine — das ist eine gemeinsame Luecke, kein Rueckstand | `assets/styles.css` (grep) | hoch | sicher | nein |
| R-66 | Ohne `role="tab"`/`aria-selected` gibt die Tableiste ihren Zustand nicht an assistive Technik weiter; visuell ist der Zustand da, semantisch nicht | `index.html:19-28`, `assets/app.js:1891-1901` | mittel | sicher | nein |
| R-67 | `<details class="drilldown">` und `.card__toggle` haben keinen eigenen Fokusstil und der Toggle kein `aria-expanded` | `assets/styles.css:380-388`, `:469-479`, `assets/app.js:1914` | mittel | sicher | ja |
| R-68 | Kein „Skip to content" — vor dem Inhalt liegen 8 Tabs plus bis zu 4 Toolbar-Felder | `index.html:9-30` | niedrig | sicher | nein |
| R-69 | **Unbedenklichkeitsaussage:** Die Aufklapp-Steuerung in `#markets` ist per Tastatur bedienbar, weil sie ein echtes `<button>` mit delegiertem Click-Handler ist (Enter/Space loesen `click` aus). Kein Handlungsbedarf ausser dem Fokusstil aus R-67 | `assets/app.js:1905-1915` | — | sicher | ja |

### Nachtraege — Flaechen, die in der Scope-Liste fehlen

| ID | Flaeche | Befund | Beleg | Sev | Konf | app.js? |
|---|---|---|---|---|---|---|
| R-70 | **Toolbar / Filterleiste** (nicht in der Liste) | Die Toolbar scrollt mit weg; ihre Steuerelemente werden per **Inline-Style** `style.display` ein-/ausgeblendet. Jede kuenftige CSS-`display`-Regel auf `label` verliert gegen den Inline-Style | `assets/app.js:25-32`, `index.html:31-60` | mittel | sicher | ja |
| R-71 | **Toolbar** | `label {display:grid; …}` ist ein **globaler Element-Selektor** — er trifft jedes `<label>` im Dokument, auch kuenftige in Panels | `assets/styles.css:157-163` | mittel | sicher | nein |
| R-72 | **Drilldown-Komponente** | Es gibt vier Varianten (`drilldown`, `drilldown compact`, `drill-list`, `drill-list compact`), aber `.drilldown.compact` hat gar keine eigene Regel — die Klasse ist wirkungslos | `assets/styles.css:380-418`, `assets/app.js:644`, `:1819` | niedrig | sicher | ja |
| R-73 | **Druck/Export** | Kein `@media print`. Bei einem Werkzeug, aus dem man Tipps abschreibt, ist eine druckbare Tippliste plausibel | `assets/styles.css` (grep) | niedrig | unsicher | nein |
| R-74 | **Dokumentkopf** | Kein Favicon verlinkt → jeder Seitenaufruf erzeugt einen 404 auf `/favicon.ico` im Server-Log | `index.html:3-8` | niedrig | wahrscheinlich | nein |
| R-75 | **Alle Panels** | Kein `max-width`-Container. Auf einem breiten Monitor laufen Kartenraster und Tabellen ueber die volle Fensterbreite; beide Referenzen zentrieren auf 1080–1120 px | `assets/styles.css:145-147` vs `analysis/wm_journey.py:736`, `analysis/pool_review_render.py:538` | mittel | sicher | nein |

**Unbedenklichkeitsaussage tote CSS-Regeln:** Ich habe alle Klassenselektoren
aus `assets/styles.css` extrahiert und gegen `assets/app.js` + `index.html`
geprueft — **keine** ungenutzte Klasse. Einzige Ausnahmen sind die *wirkungs-*
losen Regeln R-33 (`.metric.compact`) und R-72 (`.drilldown.compact`), bei
denen die Klasse benutzt wird, die Regel aber nichts tut.

---

## A4 — Verifikationsprotokoll

| Was | Wie | Ergebnis |
|---|---|---|
| Server | `serve-dashboard --port 8002` ueber `.claude/launch.json` | laeuft, alle Tabs liefern Daten |
| Alle 8 Tabs | Klick + Screenshot bei 1280 px | siehe Tabelle oben |
| 820 px / 375 px | `resize_window` + Screenshot | R-10, R-61 bestaetigt |
| `body` Typo | `getComputedStyle(document.body)` | `font-size:16px`, `line-height:normal`, `font-variant-numeric:normal` → R-19, R-20 |
| Panelhoehe Pipeline | `getBoundingClientRect()` | 9178 px → R-02, R-47 |
| Badge-Streckung | Screenshot News + Finale Tipps | volle Breite bestaetigt → R-22, R-40, R-49 |
| Tabellen-Abschnitt in Karten | Screenshot Quoten | Spaltentext abgeschnitten → R-25 |
| Ein-Klick-Update-Markup | `outerHTML` von `.pipeline-primary` | dunkles `<pre>`, 32px-Button, Badges in `.list` → R-43, R-45, R-49 |
| Fokus/Transition/Hover | `grep -n "focus\|outline\|:hover\|transition" assets/styles.css` | 1 Treffer (`.card__toggle:hover`) → R-09, R-15, R-65 |
| ARIA | `grep -n "aria-\|role=\|tabindex" assets/app.js index.html` | 1 Treffer (`nav[aria-label]`) → R-11, R-60, R-66 |
| Tote CSS-Klassen | Selektor-Extraktion + Gegenprobe | keine |
| Ausgelieferter Pokalkurs-Akzent | `grep -o -- "--acc:#…" analysis/site/index.html` | `#34c759` (nicht Emerald) → F1 |
| Test-Abdeckung | `grep -rn "assets/\|index.html" tests/` | **0 Treffer** bei 60 Testdateien → Ausgangslage Punkt 2 bestaetigt |

**Widerlegt habe ich nichts** aus der vorgegebenen Ausgangslage. Praezisiert:
Die zehn genannten `innerHTML`-Stellen sind exakt
`assets/app.js:133, 146, 168, 210, 561, 845, 1339, 1385, 1602, 1687` — dazu
kommt eine elfte, `:1735` (Pipeline). Der Panel-Aufbau haengt zusaetzlich an
`.list` als generischem Grid-Container, der an **34 Stellen** benutzt wird.

---

## B1 — Umsetzungsarchitektur

### Empfehlung

**`assets/tokens.css` als einzige Quelle, plus ein ~30-zeiliger
stdlib-Leser, der die Datei fuer die Python-Generatoren aufbereitet.**

Aufbau:

```
assets/tokens.css      <- :root{ --bg: …; --acc: …; } — die Wahrheit
assets/styles.css      <- @import? NEIN: <link> beide Dateien in index.html
analysis/design_tokens.py
                       <- load() -> (roher CSS-Text, {"--acc": "#059669", …})
```

- Das **Dashboard** verlinkt `tokens.css` und `styles.css` als zwei
  `<link>`-Tags. Kein Build-Step, kein Import-Roundtrip.
- Die **Generatoren** lesen `tokens.css` per `pathlib.Path.read_text()` und
  **inlinen den Text** in ihren `<style>`-Block. Das Ergebnis bleibt eine
  einzige, self-contained HTML-Datei ohne Netzzugriff — die Bedingung aus
  `tests/test_pool_review.py:180-195` (`assertNotIn("http://")`,
  `assertNotIn("https://")`) bleibt erfuellt, weil nichts verlinkt wird.
- Wo ein Generator einen Farbwert **als Wert** braucht (Pool-Review setzt
  `ACCENT` als SVG-`fill`-Attribut, `pool_review_render.py:228-231`,
  `:261-262`), liefert `design_tokens.load()` zusaetzlich das Dict. Der
  Parser ist trivial: Zeilen zwischen `:root{` und `}` an `:` splitten.
- stdlib-only: `pathlib` + `re`. Kein Drittpaket.

### Alternative, die ich verworfen habe

**„Jedes Frontend bleibt ein Silo, das Dashboard bekommt nur ein neues
`styles.css` mit den kopierten Werten."**

Dafuer spricht: null Risiko fuer die zwei ausgelieferten Seiten, kein neues
Modul, kein Netlify-Risiko. Dagegen spricht: es reproduziert genau die
Fehlerklasse, die B5 unten empirisch nachweist — inzwischen **fuenf**
unabhaengige Token-Saetze im Repo, von denen zwei bereits gegen Andres
festgelegte Linie verstossen. Eine sechste Kopie macht die naechste Drift
sicher.

**Kompromiss, den ich vorschlage und der beide Vorteile behaelt:**
`assets/tokens.css` **jetzt** in der geteilten Form anlegen, aber in der
ersten Sitzung **nur das Dashboard** anschliessen. Die Generatoren bleiben
unangetastet, bis ihre Migration einzeln verifiziert werden kann (Pokalkurs
haengt an Netlify — jede Aenderung dort ist ein Deploy-Risiko). Damit
existiert die gemeinsame Quelle ab Tag 1, ohne dass die zwei guten
Frontends angefasst werden.

### Wie weit muss `app.js` angefasst werden?

Ein reines CSS-Redesign traegt weiter, als die Ausgangslage vermuten laesst,
weil `app.js` bereits **semantische Klassen** vergibt (`.card`, `.badge`,
`.metric`, `.list`, `.line`, `.table-wrap`). Zwingend anfassen muss man:

| Funktion | Zeile | Warum |
|---|---|---|
| `renderDataQuality` | `:477` | Badges in `.list` → braucht `.chips`-Wrapper (R-22) |
| `renderKnockoutStatus` | `:1641-1643`, `:1661-1662` | 32 Badges in `.list` (R-40); `.metric compact` mit Textwert (R-41) |
| `renderUpdateQuality` | `:1777-1780` | Badges in `.list` (R-49) |
| `renderMatchCard` | `:362-365` | Badge-Gruppen in `.list` (R-18) |
| `renderMarkets` / `marketCard` | `:757-769`, `:845` | Tabellen in Karten brauchen `.table-wrap` statt nackter `<table>` (R-25) |
| `renderNewsFilters` | `:398-418` | Filter aus dem Panel in die Toolbar (R-21) — **optional**, groesserer Eingriff |
| `renderHistoryFilters` | `:1565-1575` | dito (R-36) |
| `renderStatus` | `:173` | KPI-Markup `<b>/<span>` → `.kpi .num`/`.kpi .lab` (R-06) |
| `updateToolbarForTab` | `:25-32` | Inline-`style.display` → `hidden`-Attribut oder Klasse (R-70) |
| `renderCommandResult` | `:1806-1825` | `aria-live`, helle Code-Flaeche (R-43, R-60) |

Alles andere (Tabellenzeilen, `.line`, `.prob`, `.meta`, Drilldowns) kann
rein ueber CSS gehoben werden.

---

## B2 — Regressionsschutz vor dem Umbau

Neue Datei `tests/test_dashboard_ui.py`, stdlib `unittest`, liest die drei
Dateien als Text. Vorbild: `tests/test_pool_review.py:180-195`.

**Warum genau diese Pruefungen:** Jede davon deckt einen Vertrag ab, dessen
Bruch *lautlos* ist — die Seite laedt weiter, sie funktioniert nur nicht mehr.

| # | Pruefung | Deckt ab | Belegstelle des Vertrags |
|---|---|---|---|
| 1 | Die acht `data-tab`-Werte in `index.html` sind **exakt** die acht `<section id=…>` | Tabumschaltung macht `getElementById(button.dataset.tab)` — ein Tippfehler wirft still `null.classList` | `assets/app.js:1896`, `index.html:20-27`, `:62-69` |
| 2 | `.tab` und `.panel` existieren im Markup, `.panel{display:none}` und `.panel.active{display:block}` in `styles.css` | Der Klassenname `active` ist der einzige Zustandstraeger | `assets/app.js:1893-1896`, `assets/styles.css:176-182` |
| 3 | Die IDs `search`, `status-filter`, `sort-order`, `round-filter`, `status-strip`, `round-eyebrow` sind in `index.html` vorhanden | `app.js` bindet sie beim Laden per ID; eine Umbenennung killt die Toolbar ohne Fehlermeldung | `assets/app.js:1919-1937`, `:144`, `:149`, `:168` |
| 4 | `label[data-control="status"|"sort"|"round"]` vorhanden | `updateToolbarForTab` selektiert genau diese drei | `assets/app.js:26-28` |
| 5 | Jedes `document.getElementById("X")` in `app.js`, das ein Panel adressiert, hat ein `id="X"` in `index.html` (Regex-Kreuzprobe) | faengt kuenftige Panels ab, die im HTML vergessen werden | alle `innerHTML`-Stellen |
| 6 | `styles.css` enthaelt Regeln fuer den kritischen Klassensatz: `.card`, `.badge`, `.badge.stabil`, `.badge.volatil`, `.badge.warte`, `.metric`, `.metrics-row`, `.list`, `.line`, `.table-wrap`, `.empty`, `.grid`, `.prob-grid`, `.round-tip-grid`, `.drilldown`, `.drill-grid`, `.drill-list`, `.command-output`, `.run-command`, `.pipeline-primary`, `.toolbar`, `.tip-badges-row`, `.odds-warning`, `.card--clamp`, `.card__body`, `.card__toggle`, `.is-open` | **Das ist der Kern.** `app.js` emittiert diese Namen aus Template-Strings; faellt eine Regel beim Redesign weg, entsteht ein ungestyltes Panel ohne jeden Fehler | `assets/app.js` (34× `.list`, 11× `innerHTML`) |
| 7 | `app.js` enthaelt `class="run-command"` **und** `data-command=` | Der POST-Pfad haengt an beidem: Selektor beim Binden, Attribut beim Senden | `assets/app.js:1802`, `:1828-1829`, `:1838` |
| 8 | `app.js` enthaelt `card__toggle`, `data-card-toggle`, `card--clamp`, `is-open`; `styles.css` enthaelt `.card--clamp:not(.is-open) .card__body{max-height:…}` | Die delegierte Aufklapp-Logik prueft alle vier Namen, und die `max-height` ist Teil der Logik (R-26) | `assets/app.js:1905-1913`, `:770-781`, `assets/styles.css:465-468` |
| 9 | `index.html` verlinkt `assets/styles.css`; nach Schritt S1 zusaetzlich `assets/tokens.css` | verhindert, dass ein halb migriertes Token-Set stumm ins Leere greift | `index.html:7` |
| 10 | **Design-Linter (nach der Migration):** `styles.css` + `tokens.css` enthalten weder `Inter` noch `Georgia`/`Fraunces`/`Playfair`/`Lora`, weder `#f5f2ed`/`#fffaf3`/`#f4f1ea`/`#faf7f2`, noch `prefers-color-scheme: dark` | Das ist der einzige Test, der die **Design-Entscheidung selbst** festnagelt statt nur die Struktur — sonst driftet die naechste Sitzung zurueck ins Creme | Auftrag „Du erfindest kein Design"; Memory `feedback_light_theme_no_dark` |

Pruefung 10 kommt bewusst **nach** dem Umbau in Kraft (sie wuerde heute
rot sein) — deshalb steht sie in Schritt S3, nicht in S0.

---

## B3 — Schnittfolge

Hausregel: max. 1–3 Aenderungen pro Schritt. Rollback-Punkt ist jeweils der
letzte gruene Commit; jeder Schritt bleibt ein eigener Commit.

| Nr | Aenderung | Dateien | Verifikation | Erwartet | Rollback |
|---|---|---|---|---|---|
| **S0** | Regressionstest einfuehren (B2 Pruefungen 1–9), **ohne** jede Produktivaenderung | `tests/test_dashboard_ui.py` (neu) | `PYTHONPATH=src python3 -m pytest` | 600 + n passing, alle neuen gruen **gegen den Ist-Zustand** | Testdatei loeschen |
| **S1** | `assets/tokens.css` anlegen (nur `:root`, Werte aus A1) + `<link>` in `index.html`. `styles.css` noch unveraendert | `assets/tokens.css` (neu), `index.html` | Tests; Browser: Seite sieht **identisch** aus | keine sichtbare Aenderung — Tokens sind noch ungenutzt | `git checkout index.html`, Datei loeschen |
| **S2** | `styles.css:1-14` auf die neuen Tokens umstellen (Farben + Font-Stack + `line-height` + `tabular-nums`). Nur `:root` und `body` | `assets/styles.css` | Tests; Screenshot aller 8 Tabs | Creme → neutral-weiss, Inter → SF Pro, Text wird luftiger. Layout unveraendert | ein `git checkout` |
| **S3** | Design-Linter aktivieren (B2 Pruefung 10) | `tests/test_dashboard_ui.py` | `pytest` | gruen — beweist, dass S2 vollstaendig war | Pruefung auskommentieren |
| **S4** | Radien-, Schatten- und Motion-Skala einfuehren; `.card`, `.table-wrap`, `.tab`, `.badge` darauf umstellen | `assets/styles.css` | Tests; Screenshot | Pill-Nav, weiche Badge-Fuellungen, feinere Karten | ein `git checkout` |
| **S5** | Sticky-Topbar: `.app-header` + `.tabs` in einen `position:sticky`-Container mit `backdrop-filter` | `index.html`, `assets/styles.css` | Tests (Pruefung 1–2 schuetzen die Tabs); Scrolltest im Pipeline-Tab | Navigation bleibt sichtbar | zwei `git checkout` |
| **S6** | Tabellen-Fix: `min-width` von `table` auf `.table-wrap table` verschieben; Zahlenspalten rechts; `th` sticky | `assets/styles.css` | Tests; Quoten-Tab prueft R-25 | Karten-Tabellen nicht mehr abgeschnitten | ein `git checkout` |
| **S7** | `app.js`: `.list` mit Badge-Kindern auf einen `.chips`-Wrapper umstellen — die vier Stellen `:362-365`, `:477`, `:1661`, `:1777` | `assets/app.js`, `assets/styles.css` | Tests; News-, Tipps-, Pipeline-Tab | Badges sind wieder Pillen statt Balken | ein `git checkout` |
| **S8** | KPI-Komponente: `renderStatus:173` und `.metric`/`.metrics-row` auf `auto-fit` + 44px-Zahl | `assets/app.js`, `assets/styles.css` | Tests; 375px-Check | KPIs lesen sich als KPIs, keine Waisen mehr | ein `git checkout` |
| **S9** | Fokus + ARIA: `:focus-visible`-Ring global, `role=tab`/`aria-selected`, `aria-expanded`, `aria-live` fuer Kommandoausgabe | `index.html`, `assets/app.js`, `assets/styles.css` | Tests; Tastaturdurchlauf | Fokus ueberall sichtbar | drei `git checkout` |
| **S10** | Zweiter Breakpoint (560px) + `env(safe-area-inset-*)` + `max-width`-Container | `assets/styles.css` | Tests; 375/820/1280 px | mobil brauchbar | ein `git checkout` |
| **S11** | Primaerbutton + helle Kommandoausgabe (R-43, R-45) | `assets/styles.css` | Tests; Pipeline-Tab | „Alles updaten" ist das groesste Element seiner Sektion; kein Dark-Block mehr | ein `git checkout` |
| **S12** *(optional, spaeter)* | Generatoren an `tokens.css` anschliessen — **einzeln**, Pool-Review zuerst (hat Tests), Pokalkurs zuletzt (Netlify) | `analysis/design_tokens.py` (neu), `analysis/pool_review_render.py` | `pytest`; Diff der generierten `site-pool/index.html` | nur erwartete Farbaenderungen | ein `git checkout` |

---

## B4 — Risiken: was funktional kaputtgehen kann

| Risiko | Mechanik | Beleg | Schutz |
|---|---|---|---|
| **Tabumschaltung tot** | `.active` ist der einzige Zustandstraeger und wird gleichzeitig als CSS-Selektor und als JS-Klasse benutzt. Ein Redesign, das die Pill-Nav mit `.on` (wie Pokalkurs) umsetzt, killt die Umschaltung stumm | `assets/app.js:1893-1896`, `assets/styles.css:176-182`, `:107-111` | B2-Pruefung 2 |
| **Panel bleibt leer** | `getElementById(button.dataset.tab)` — `data-tab` **muss** die Section-ID sein | `assets/app.js:1896` | B2-Pruefung 1 |
| **Ein-Klick-Update tot** | Der Handler wird bei jedem `renderPipeline()` neu ueber `.run-command` gebunden, weil `innerHTML` die Knoten ersetzt. Wandert der Button aus dem neu geschriebenen `innerHTML` heraus, verliert er beim ersten Re-Render den Handler — und ein Re-Render passiert bei **jedem Suchtastenanschlag** | `assets/app.js:1735-1746`, `:1827-1831`, `:1919-1922` | B2-Pruefung 7 |
| **POST bricht** | `runCliCommand` liest `button.dataset.command`; das Attribut kommt aus `renderCommandAction` | `assets/app.js:1802`, `:1829`, `:1833-1854` | B2-Pruefung 7 |
| **Aufklappen der Quoten-Kacheln bricht** | Delegation auf `#markets` prueft `.card__toggle`, liest `data-card-toggle`, sucht `.card--clamp` und schaltet `is-open`. Vier Namen, alle im CSS gespiegelt | `assets/app.js:1905-1915`, `:770-781`, `assets/styles.css:465-468` | B2-Pruefung 8 |
| **Aufklapp-Button verschwindet oder erscheint immer** | `clampMarketCards` misst `body.scrollHeight > body.clientHeight + 4`. Aendert man `max-height:19rem` oder das Box-Modell des Karteninhalts, aendert sich, welche Kacheln ueberhaupt einen Toggle bekommen — **ein CSS-Wert steuert Verhalten** | `assets/app.js:777`, `assets/styles.css:465-468` | B2-Pruefung 8 + manueller Check in S6 |
| **Toolbar-Felder verschwinden dauerhaft** | `updateToolbarForTab` setzt `style.display` **inline**. Inline schlaegt Stylesheet — eine neue `.toolbar label{display:flex}`-Regel kann ein ausgeblendetes Feld nicht zurueckholen, und ein `display:grid`-Layout behaelt die Luecke | `assets/app.js:29-31` | B2-Pruefung 4 + Umstellung auf `hidden` in S9 |
| **News-/History-Filter verlieren ihre Handler** | Beide Filterleisten liegen **innerhalb** des Panel-`innerHTML` und werden direkt danach neu gebunden. Verschiebt man sie in die Toolbar, muss die Bindung mitwandern — sonst sind sie tot | `assets/app.js:561-562`, `:1602-1603`, `:419-426`, `:1576-1579` | manueller Check in S7 (falls R-21/R-36 angefasst werden) |
| **Watchlist-Interaktionen** | **Entwarnung:** Die Watchlist hat keine eigenen Event-Handler. Sie rendert nur (`assets/app.js:1368-1387`); die einzigen Bedienelemente darin sind `.run-command`-Buttons aus `renderCommandRow`, die ueber `bindPipelineActions` mitlaufen — dieselbe Bindung wie im Pipeline-Tab | `assets/app.js:1368-1387`, `:1418-1436` | B2-Pruefung 7 |
| **Fokusverlust beim Tippen** | `renderAll()` ersetzt bei jedem Anschlag alle acht Panels. `#search` selbst liegt in `index.html` und ueberlebt — aber ein fokussierter News-Filter im Panel wuerde mitten im Tippen ersetzt | `assets/app.js:1879-1889`, `:1919-1922` | bekannt, nicht Teil des Redesigns (siehe Folge-Task) |

---

## B5 — Isomorphie-Check (ausgefuehrt)

**Fehlerklasse:** „Styling-Regel existiert nur in einem der Frontends und
driftet."

**Vorgehen:** `grep -n "<style>\|CSS = \|:root"` ueber alle HTML-erzeugenden
Python-Dateien in `analysis/`, danach die gefundenen Bloecke gelesen.

**Ergebnis: drei weitere Fundstellen, alle mit eigenem, unabhaengigem
Token-Satz.**

| Fundstelle | Tokens | Verhaeltnis zur Hauslinie |
|---|---|---|
| `analysis/rival_lab_render.py:24-28` | `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3; --accent:#58a6ff` + sechs Kategoriefarben `--c0…--c5` | **Vollstaendiges Dark Theme.** Widerspricht „kein Dark Mode in jeglicher Form" direkt. Zusaetzlich ein blauer Primaerakzent statt Emerald und eine 6-Farben-Kategoriepalette, die es sonst nirgends gibt |
| `analysis/wm_player_ratings.py:359` | `--bg:#f6f6f4; --card:#fff; --bd:#e6e5e0; --tx:#1a1a18; --mut:#6b6a64; --ter:#efeee9` | Hell, aber **warm** (`#f6f6f4`, `#e6e5e0`) statt neutral-kuehl. Radius durchgaengig **16px** (vierter Radienwert im Repo). Und: `.mp{background:#FAECE7;color:#993C1D}` (`:381`) ist ein **Terracotta-Chip** — genau die im Auftrag verbotene Akzentfamilie |
| `assets/styles.css:1-14` | das Dashboard selbst | Creme + Inter + Terracotta `--accent-2` |

**Damit existieren fuenf unabhaengige Token-Saetze im Repo**, von denen drei
gegen die festgelegte Linie verstossen (Dashboard: Creme/Inter/Terracotta;
Rival-Lab: Dark Mode; Player-Board: warm + Terracotta-Chip). Zwei stimmen
mit der Linie ueberein (Pokalkurs, Pool-Review) — und selbst diese beiden
widersprechen sich im Akzentwert (siehe F1).

**Regression-Check, der die Klasse abdeckt:** B2-Pruefung 10 (der
Design-Linter) sollte **nicht** auf `assets/` beschraenkt bleiben, sondern
ueber alle CSS-erzeugenden Dateien laufen — dann faellt jede kuenftige
sechste Kopie sofort auf. Fuer Rival-Lab und Player-Board braucht es dafuer
aber erst eine Entscheidung (siehe F3), sonst ist der Test am Tag seiner
Einfuehrung rot.

Merksatz aus dieser Runde, passend zum bestehenden Memory-Eintrag
`reference_public_guard_pipefail_and_reflog` („Zentralisieren verschiebt
Drift auf die naechste Ebene"): **Eine gemeinsame `tokens.css` verhindert
Drift nur fuer die Dateien, die sie auch lesen. Wer nicht angeschlossen ist,
driftet weiter — nur unsichtbarer, weil es jetzt so aussieht, als gaebe es
ein System.**

---

## B6 — Aufwand und erste Sitzung

| Schritt | Groesse | Begruendung |
|---|---|---|
| S0 Regressionstests | **M** | ~10 Pruefungen, Regex-Kreuzprobe ist der aufwendige Teil |
| S1 `tokens.css` + Link | **S** | reines Anlegen, keine Wirkung |
| S2 Farben/Typo umstellen | **S** | `:root` + `body`, ~20 Zeilen |
| S3 Design-Linter | **S** | eine Testmethode |
| S4 Radien/Schatten/Motion | **M** | betrifft ~15 Regeln quer durchs Stylesheet |
| S5 Sticky-Topbar | **M** | Markup-Umbau im Header, Z-Index-Klaerung |
| S6 Tabellen | **M** | `min-width`-Umzug + Spaltenausrichtung + sticky `th` |
| S7 `.list`/Chips in `app.js` | **M** | 4 Renderfunktionen + neue CSS-Komponente |
| S8 KPI-Komponente | **M** | Markup in 3 Renderfunktionen (`:173`, `:1656`, `:1708`) |
| S9 Fokus + ARIA | **L** | beruehrt alle drei Dateien, braucht Tastaturdurchlauf durch 8 Tabs |
| S10 Breakpoints/Safe-Area | **M** | zweiter Breakpoint quer durchs Stylesheet |
| S11 Primaerbutton + helle Ausgabe | **S** | ~15 Zeilen CSS |
| S12 Generatoren anschliessen | **L** | Netlify-Risiko, Diff-Verifikation je Seite |

**Vorschlag erste Sitzung: S0 → S1 → S2 → S3 → S4.**

Das ist ein M + drei S + ein M und liefert den mit Abstand groessten
sichtbaren Sprung: Creme→neutral, Inter→SF Pro, Zeilenhoehe, Radien,
Schatten, Pill-Nav, weiche Badges. Danach steht ein Regressionsnetz **und**
ein Linter, der die Design-Entscheidung festhaelt — ab da kann jede weitere
Sitzung gefahrlos einzelne Schritte nachziehen.

Bewusst **nicht** in die erste Sitzung: S9 (gross, eigener Fokus) und S12
(Netlify-Deploy-Risiko, braucht eine Ansage).

---

## Entscheidungen (Andre, 22.07.2026)

| # | Entscheidung | Folge |
|---|---|---|
| **F1** | „keine Meinung" → **meine Empfehlung gilt: `--accent:#059669`, `--accent-deep:#047857`** (Pool-Review-Paar) | Dashboard und ausgelieferte Pokalkurs-Seite (`#34c759`) haben danach verschiedene Gruentoene. Angleichen per `WM_SITE_ACCENT=#059669` beim Generieren — **eigener Schritt, eigener Deploy**, nicht Teil des Dashboard-Umbaus |
| **F2** | „keine Meinung" → **meine Empfehlung gilt: aktive Tab-Pille `--ink`, aktive Filter-Chips Akzent** | Sichtbarste Einzelaenderung: der aktive Tab ist danach dunkel statt gruen |
| **F3** | **Ja — Rival-Lab und Player-Board werden mitgezogen.** „Idealerweise ist es sogar integriert." | Der Design-Linter darf repo-weit greifen. **Was „integriert" heisst, ist noch offen — siehe F3a** |
| **F4** | offen — Beschreibung unten | |
| **F5** | offen — Beschreibung unten | |

**F3a — Was heisst „integriert"?** Zwei Lesarten, die sehr weit
auseinanderliegen:

- **(a) Token-integriert:** Rival-Lab und Player-Board lesen dieselbe
  `assets/tokens.css` wie alles andere. Sie bleiben eigenstaendige,
  self-contained HTML-Dateien. Aufwand: **M** je Datei, Risiko gering, die
  bewusste Trennung aus `project_rival_lab_dashboard.md` (A/B zu
  `rival-profiles/`) und `project_analysis_explorative_artefakt.md`
  (`analysis/` darf pandas/plotly) bleibt erhalten.
- **(b) Seiten-integriert:** Beide werden Bereiche/Tabs des Dashboards
  statt eigener Dateien. Aufwand: **L–XL**, und es hebt zwei bewusst
  gesetzte Grenzen auf — `analysis/` ist der Nicht-stdlib-Explorationsraum
  mit read-only-Charakter, das Dashboard ist stdlib-only Produktivpfad mit
  einem POST-Endpunkt.

**Meine Empfehlung: (a).** Sie loest das Problem, das der
Isomorphie-Check gefunden hat (fuenf divergierende Paletten), ohne eine
Architekturgrenze zu opfern, die aus guten Gruenden existiert. (b) waere
ein eigenes Vorhaben mit eigener Begruendung, nicht ein Anhang an ein
Redesign.

Zusaetzlich zu klaeren, falls (a): Rival-Lab ist ein **vollstaendiges Dark
Theme**. „Mitziehen" heisst dort nicht Token tauschen, sondern die Seite
auf hell umbauen — Kategoriefarben (`--c0…--c5`), Tooltip, Gridlines und
Tabellen-Highlights sind alle auf dunklen Grund gerechnet. Das ist **L**,
nicht M, und gehoert in einen eigenen Schritt nach S12.

---

## Offene Fragen — vor Umsetzung zu entscheiden

**F1 — Welcher Emerald ist kanonisch?** *(entschieden: Empfehlung gilt.
Begruendung bleibt hier stehen.)* Die beiden Referenzen widersprechen
sich, und der Auftrag nennt beide Kandidaten.

- Pokalkurs liefert real `--acc:#34c759` (iOS-Systemgruen) mit
  `--acc-d:#1f8f3c` fuer Text (`wm_journey.py:717`, `:45`; verifiziert in
  `analysis/site/index.html`).
- Pool-Review nutzt `#059669` / `#047857` (`pool_review_render.py:28-29`).

**Meine Empfehlung: `#059669` / `#047857`.** Vier Gruende:
(1) Der Auftrag selbst nennt Emerald `#059669`.
(2) Kontrast auf `#fbfbfd` (nachgerechnet, WCAG 2.1): `#047857` = **5.31:1**
(AA fuer Fliesstext bestanden), `#1f8f3c` = **4.02:1** (**nicht**
bestanden, Schwelle 4.5). Zum Vergleich: `#059669` = 3.65:1 und
`#34c759` = 2.15:1 — beide taugen nur als Fuellung, nicht als Textfarbe,
weshalb das Paar Basis/Deep in beiden Referenzen kein Zufall ist. Ein
Dashboard hat mehr Kleintext als eine Erzaehlseite.
(2b) Randnotiz: Der heutige `--accent:#0c7a6b` erreicht auf dem heutigen
Creme-Grund 4.69:1 und ist damit **nicht** das Barrierefreiheitsproblem
des Dashboards — das sind der fehlende Fokusring (R-65) und die
Badge-Fuellungen (R-53).
(3) `#34c759` ist in Pokalkurs **nie Textfarbe** — nur Fuellung (Ball,
Punkte, Trennstriche). Es als „den Akzent" zu adoptieren, hiesse eine
reine Fuellfarbe zur Systemfarbe zu erklaeren.
(4) Pool-Reviews Wert ist eine harte Konstante (Designentscheidung),
Pokalkurs' Wert ist ein per `WM_SITE_ACCENT` ueberschreibbarer Default
(Deployment-Schalter) — der Schalter hat den schwaecheren Anspruch auf
Kanonizitaet.

**Konsequenz, die du mitentscheidest:** Danach haetten Dashboard
(`#059669`) und die ausgelieferte Pokalkurs-Seite (`#34c759`) verschiedene
Gruentoene. Angleichen ginge ohne Code-Aenderung ueber
`WM_SITE_ACCENT=#059669` beim Generieren — aber das aendert die
oeffentliche Seite und braucht einen Netlify-Deploy. Alternative: Dashboard
auf `#34c759`/`#1f8f3c` ziehen und den Kontrastnachteil hinnehmen.

**F2 — Womit wird die aktive Nav-Pille gefuellt: `--ink` oder Akzent?**
Pokalkurs faerbt aktive Nav mit `--ink` (`:750`) und haelt den Akzent fuer
Datenaussagen frei; Pool-Review faerbt aktive Chips mit `ACCENT_DEEP`
(`:577`). Meine Empfehlung: **`--ink` fuer die Tab-Navigation**
(Navigation ist keine Datenaussage), **Akzent fuer Filter-Chips** — das ist
genau die Aufteilung, die die beiden Referenzen zusammen ergeben. Aber es
ist der sichtbarste Einzelunterschied zum heutigen Zustand (heute: gruener
aktiver Tab), deshalb lege ich ihn vor.

**F3 — Gilt die Linie auch fuer Rival-Lab und Player-Board?**
*(Entschieden 22.07.26: ja, beide. Restfrage F3a oben.)*
`rival_lab_render.py` ist ein vollstaendiges Dark Theme, `wm_player_ratings.py`
warmes Hell mit Terracotta-Chip. Der Design-Linter aus B2/B5 darf damit
repo-weit greifen — braucht aber eine Uebergangsfrist, bis beide Seiten
umgebaut sind, sonst ist er am Tag seiner Einfuehrung rot.

---

### F4 — Spacing-Token einfuehren, obwohl die Referenz keine hat?

**Worum es geht.** Abstaende (Innenabstand, Aussenabstand, Rasterluecken)
werden heute ueberall als nackte Zahl geschrieben. Es gibt keine Regel,
welcher Wert wann gilt.

**Ist-Zustand — die faktisch benutzten Werte:**

| Datei | Werte |
|---|---|
| `assets/styles.css` | 6, 8, 10, 11, 12, 14, 16, 18, 22, 28, 32, 40 |
| `analysis/wm_journey.py` | 2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 22, 26, 34 |
| `analysis/pool_review_render.py` | 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 44, 48, 56, 64 |

**Keine** dieser Dateien hat Spacing-Token. Sichtbare Folge im Dashboard:
`.round-tip-grid div` hat 11px Innenabstand (`styles.css:231`), `.prob` hat
9px (`:306`), `.metric` 10/12px (`:60`), `.line` 10px (`:332`), `.card`
16px (`:194`) — sieben verschiedene Werte fuer denselben Zweck, ohne dass
irgendwo steht, warum.

**Der Vorschlag:** eine benannte Leiter in `tokens.css`, an der sich neue
Regeln orientieren.

```
--s1:  4px    --s5: 20px
--s2:  8px    --s6: 26px
--s3: 12px    --s7: 34px
--s4: 16px    --s8: 56px
```

Die Stufen sind nicht frei erfunden — sie sind die Verdichtung der drei
Spalten oben (die haeufigsten Werte liegen bei 8, 12, 16, 18–20, 26).

**Dafuer:** „Welcher Abstand ist hier richtig" ist danach keine freie
Entscheidung mehr, sondern eine Auswahl aus acht. Ein Test kann das
erzwingen. Genau die Beliebigkeit, die den Ist-Zustand unruhig macht,
verschwindet.

**Dagegen — und das ist der ehrliche Punkt:** Der Auftrag sagt „Du
erfindest kein Design". Die Referenz hat diese Token **nicht**. Ich waere
hier also nicht Uebersetzer, sondern Autor. Zweitens: halb eingefuehrte
Spacing-Token sind schlechter als keine — dann existieren Leiter *und*
Literale nebeneinander, und man weiss bei jeder Zeile nicht, welche der
beiden Wahrheiten gerade gilt.

**Meine Empfehlung: ja, aber ohne Big Bang.** Leiter anlegen, **nur neu
geschriebenes CSS** darauf verpflichten, bestehende Literale mitziehen wenn
man die Regel ohnehin anfasst. Kein Suchen-und-Ersetzen ueber 483 Zeilen.
Aufwand dann **S** statt M, und das „halb eingefuehrt"-Risiko wird zu einem
kontrollierten Uebergang statt zu einem Dauerzustand.

**Wenn du Nein sagst:** kein Schaden. Dann uebernehme ich die Abstaende der
Referenz als Literale, so wie die Referenz es auch tut. Die Seite sieht
identisch aus; nur die naechste Aenderung ist wieder eine freie
Entscheidung.

---

### F5 — Wie weit sollen die Panel-Filter in die Toolbar wandern?

**Worum es geht.** Das Dashboard hat heute **zwei** Filtersysteme
uebereinander.

**System 1 — die globale Toolbar** (`index.html:31-60`): vier Felder
(Suche, Status, Sortierung, Tipprunde). `updateToolbarForTab`
(`app.js:25-32`) blendet drei davon je nach Tab ein und aus; nur „Suche"
steht immer.

**System 2 — Filter im Panel**, von `app.js` in den Panel-Inhalt gerendert:

| Tab | Filter | Erzeugt in | Gebunden in |
|---|---|---|---|
| News | Schwere, Kategorie, Wirkung (3 Selects) | `app.js:398-418` | `app.js:419-426`, aufgerufen nach jedem Render (`:562`) |
| History | Ausloeser (1 Select) | `app.js:1565-1575` | `app.js:1576-1579`, aufgerufen nach jedem Render (`:1603`) |

**Was man im Browser sieht** (verifiziert): Im News-Tab stehen zwei
Filterzeilen untereinander — oben „Suche", darunter „Schwere / Kategorie /
Wirkung", optisch verschieden weit eingerueckt. Im History-Tab klebt
„Ausloeser" ohne Abstand zwischen Zusammenfassungskarte und Tabelle
(R-36).

**Die drei Optionen:**

- **(1) Voll zusammenlegen** — die vier Panel-Selects wandern nach
  `index.html`, `updateToolbarForTab` bekommt sechs statt drei
  Sichtbarkeitsregeln, die Optionen werden aus den Daten befuellt (so wie
  `populateRoundFilter` es fuer die Tipprunde schon macht,
  `app.js:142-155`). **Aufwand L.** Der Kostenpunkt ist nicht das Markup,
  sondern das **Zustandsmodell**: heute werden die Selects nach jedem
  Render neu erzeugt und neu gebunden; danach existieren sie dauerhaft und
  duerfen genau **einmal** gebunden werden. Dazu kommt das
  Inline-`style.display`-Problem aus R-70, das dann sechs Felder betrifft
  statt drei.
- **(2) Nur optisch angleichen** — die Panel-Filter bleiben wo sie sind und
  behalten ihre Bindung, bekommen aber die Toolbar-Formatierung und einen
  festen Platz direkt unter der Toolbar. **Aufwand S.** Reine
  CSS-/Positionsfrage, kein Eingriff ins Zustandsmodell, kein Risiko aus
  B4. Bringt den sichtbaren Teil des Nutzens (eine Filterzone statt zwei
  verstreuter) ohne den teuren Teil.
- **(3) Nichts tun** — bleibt wie es ist.

**Meine Empfehlung: (2) im Zuge des Redesigns, (1) spaeter als eigener
Task oder gar nicht.** Der Unterschied zwischen (1) und (2) ist fuer dich
im Browser klein, im Code aber der zwischen „Stil" und „Architektur" — und
Architekturumbauten gehoeren nicht in einen Schritt, dessen Verifikation
„sieht besser aus" lautet.
