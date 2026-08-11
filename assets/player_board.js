// Spieler-Impact-Board -- Render-Logik, geteilt zwischen zwei Zielen:
//   1. analysis/wm_player_board.html (standalone, von
//      analysis/wm_player_ratings.py erzeugt; CSS und JS werden dort inline
//      eingebettet, damit die Datei ohne Server und ohne Netz laeuft)
//   2. Dashboard-Tab "Analyse" (assets/app.js ruft mountPlayerBoard)
// Die Datei ist die EINZIGE Quelle dieser Logik -- nicht kopieren (T-0165).
//
// Balkenfarben: Werte aus assets/tokens.css, literal notiert weil sie als
// style-Attribut gesetzt werden. Vorher standen hier ein Terracotta- und
// ein systemfremder Violett-Ton (Hex-Werte bewusst nicht zitiert, sonst
// schlagen die Farb-Waechter in tests/test_dashboard_ui.py darauf an).
function mountPlayerBoard(DATA, host) {
  const ziel = host || document.getElementById("analyse-player-board");
  if (!ziel) return;

  const BALKEN = {
    finisher: "#047857",  // --acc-d
    keeper: "#0a62cc",    // --blue-d
    kreator: "#a25e00",   // --amber-d
    hot: "#c39214",       // --gold
  };

  const esc = (wert) => String(wert ?? "").replace(/[&<>"']/g, (z) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[z]);

  const balken = (anteilProzent, farbe) =>
    `<div class="pb-bar"><i style="width:${Math.max(0, Math.min(100, anteilProzent)).toFixed(0)}%;background:${farbe}"></i></div>`;

  // Die drei Tags kommen aus wm_player_ratings.club_tag().
  const tagPille = (tag, verhaeltnis) => {
    if (!tag) return "";
    return `<span class="pill pill--${esc(tag)}">${esc(tag)} · ${esc(verhaeltnis)}× Club</span>`;
  };

  const zeile = (titel, zusatz, wert, einheit, breite, farbe, meta) => `
    <div class="r">
      <div class="rt">
        <span class="nm">${esc(titel)}<span class="tm">${esc(zusatz)}</span></span>
        <span class="v">${wert}${einheit ? `<span class="su"> ${esc(einheit)}</span>` : ""}</span>
      </div>
      ${breite === null ? "" : balken(breite, farbe)}
      ${meta ? `<div class="pb-meta">${meta}</div>` : ""}
    </div>`;

  const finisher = (DATA.finishers || []).slice(0, 12).map((p) => zeile(
    p.name, p.team, esc(Number(p.talent90).toFixed(2)), "G+A/90",
    p.talent90 / 1.55 * 100, BALKEN.finisher,
    `${esc(p.G)}G ${esc(p.A)}A · ${esc(p.min)}min ${tagPille(p.club_tag, p.club_ratio)}`
  )).join("");

  // keepers kommen als Tupel (prev, name, team, sota, ga, cs).
  const keeper = (DATA.keepers || []).slice(0, 6).map((k) => {
    const [prev, name, team, sota, ga, cs] = k;
    return zeile(
      name, team, `+${Number(prev).toFixed(2)}`, "",
      prev / 3.4 * 100, BALKEN.keeper,
      `${esc(sota)} Schuesse aufs Tor, ${esc(ga)} kassiert · ${esc(cs)}× zu Null`
    );
  }).join("");

  const kreatoren = (DATA.creators || []).slice(0, 5).map((p) => zeile(
    p.name, p.team, esc(p.A), "Assists",
    p.A / 3 * 100, BALKEN.kreator, `${esc(p.G)} eigene Tore`
  )).join("");

  const hot = (DATA.hot || []).slice(0, 5).map((p) => zeile(
    p.name, `${p.min}min`, `<span class="su">${esc(p.raw90)} &rarr; ${esc(p.talent90)}</span>`,
    "", p.heat / 1.2 * 100, BALKEN.hot, ""
  )).join("");

  const kalt = (DATA.cold || []).slice(0, 5).map((p) => zeile(
    p.name, p.team, `<span class="su">${esc(p.talent90)} vs ${esc(p.club_xga90)}</span>`,
    "", null, "", ""
  )).join("");

  const stumm = (DATA.misfiring || [])
    .map((eintrag) => `<span class="mp">${esc(eintrag[0])} · 0</span>`).join("");

  const fortschritt = DATA.played == null || DATA.total == null
    ? "Turnierstand unbekannt"
    : `Turnier ${esc(DATA.played)}/${esc(DATA.total)} Spiele`;

  ziel.innerHTML = `
    <p class="cs">${fortschritt} · Spielerdaten Stand ${esc(DATA.daten_stand)} ·
       freie Zaehldaten (FBref) + Club-xG (Understat 25/26) · Empirical-Bayes-geglaettet</p>
    <div class="pb-grid">
      <div class="cd">
        <p class="ct">&#127919; Finisher &mdash; Talent-Rate</p>
        <p class="cs">G+A/90 gegen Minuten geschrumpft; Tag = WM vs Club-xGA90</p>${finisher}
      </div>
      <div class="cd">
        <p class="ct">&#129508; Torhüter &mdash; Goals Prevented</p>
        <p class="cs">verhinderte Tore gegenüber Schnitt, schussvolumen-bereinigt</p>${keeper}
      </div>
      <div class="cd">
        <p class="ct">&#128095; Kreatoren &mdash; Vorlagen</p>
        <p class="cs">Wert aus dem Auflegen, nicht dem Toreschießen</p>${kreatoren}
      </div>
      <div class="cd">
        <p class="ct">&#128293; Hot-Streak &mdash; Regression</p>
        <p class="cs">rohe Rate » Talent bei kleiner Stichprobe → kühlt ab</p>${hot}
        <p class="cs" style="margin:14px 0 6px">Kalt &mdash; Elite unter Club-Niveau, Aufwärts-Potenzial:</p>${kalt}
      </div>
    </div>
    <div class="mis">
      <p class="ct" style="font-size:15px">&#9888;&#65039; Angriff streikt &mdash; Predictions-Watch</p>
      <p class="cs">0 Spieler-Tore in der Gruppenphase &mdash; bei hoher Modell-Stärke Übertippen-Gefahr</p>${stumm}
    </div>
    <p class="foot">Methodik: rohe Per-90-Raten bei 90&ndash;180 Min sind verrauscht →
      Empirical-Bayes-Shrinkage gegen einen Prior (0,45 G+A/90, Stärke 2 Spiele).
      Club-xGA90 = (xG+xA)/90 der Vereinssaison 25/26, direkt vergleichbar.
      „heiss" = WM über Club (Regression wahrscheinlich), „kalt" = unter Club (Potenzial).
      Keeper: verhinderte Tore = Schussvolumen × Liga-Gegentorquote − tatsächliche Gegentore.
      Kein Modell-/Tipp-Input &mdash; rein deskriptiv.</p>`;
}
