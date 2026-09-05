const state = {
  data: null,
  search: "",
  sort: "kickoff",
  status: "",
  round: "",
  news_severity: "",
  news_category: "",
  news_impact: "",
  history_trigger: "",
  runningCommands: new Set(),
  commandResults: {},
  expandedCards: new Set(),
};

const NEWS_SEVERITIES = ["critical", "important", "context", "noise"];
const NEWS_CATEGORIES = ["injury", "illness", "suspension", "form", "coach", "squad", "expected_lineup", "confirmed_lineup", "weather", "travel", "pitch", "general"];
const HISTORY_TRIGGERS = ["News", "News-Lage", "Quoten/Markt", "Teamstaerke/Kontext", "Modell", "Bonus-Recalc"];

const SEVERITY_ORDER = { critical: 3, important: 2, context: 1, noise: 0 };

// In welchen Tabs ist welcher Filter sichtbar. Eine Tabelle statt sieben
// fast gleicher if-Zeilen -- ein neuer Filter ist damit ein Eintrag, keine
// weitere Kopie.
const TOOLBAR_SICHTBARKEIT = {
  "status": ["matches", "tips"],
  "sort": ["matches", "tips", "markets"],
  "round": ["tips"],
  "news-severity": ["news"],
  "news-category": ["news"],
  "news-impact": ["news"],
  "history-trigger": ["history"],
};

function updateToolbarForTab(tab) {
  Object.entries(TOOLBAR_SICHTBARKEIT).forEach(([control, tabs]) => {
    const label = document.querySelector(`label[data-control="${control}"]`);
    // `hidden` statt style.display: ein Inline-Stil gewinnt gegen JEDE
    // CSS-Regel und macht das Layout spaeter unkorrigierbar (R-70).
    if (label) label.hidden = !tabs.includes(tab);
  });
}

const fmtPct = (value) => `${Math.round((value || 0) * 100)}%`;
const fmtPct1 = (value) => value === null || value === undefined ? "n/a" : `${((value || 0) * 100).toFixed(1)}%`;
const fmtValue = (value) => value === null || value === undefined || value === "" ? "n/a" : value;
const fmtDate = (value) => {
  if (!value) return "offen";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;",
}[char]));

function matchesSearch(text) {
  return text.toLowerCase().includes(state.search.toLowerCase());
}

function statusClass(status) {
  if (status === "stabil") return "stabil";
  if (status === "volatil") return "volatil";
  return "warte";
}

function commandStatusClass(status) {
  if (status === "geprueft" || status === "gespielt") return "stabil";
  if (status === "kritisch") return "volatil";
  return "warte";
}

function cliStatusClass(status) {
  if (status === "ok") return "stabil";
  if (status === "missing") return "volatil";
  return "warte";
}

function qualityClass(status) {
  if (status === "ok" || status === "fresh") return "stabil";
  if (status === "warning" || status === "skipped" || status === "stale") return "warte";
  return "volatil";
}

function sortKey(item, sort) {
  const fixture = item.fixture || item;
  if (sort === "expected_points") {
    return -Number(item.recommended_tip?.expected_points ?? item.expected_points ?? 0);
  }
  if (sort === "match_number") {
    return Number(fixture.match_number ?? item.match_number ?? 9999);
  }
  return Date.parse(fixture.kickoff_utc || item.kickoff_utc || "") || 0;
}

function parseTs(value) {
  const t = Date.parse(value || "");
  return Number.isNaN(t) ? null : t;
}

// Kommende Spiele zuerst (naechstes oben), vergangene danach (zuletzt
// gespieltes zuerst), undatierte ans Ende. getTs(item) -> ms | null.
function upcomingFirstComparator(getTs) {
  const now = Date.now();
  return (a, b) => {
    const ta = getTs(a);
    const tb = getTs(b);
    if (ta === null || tb === null) return (ta === null) - (tb === null);
    const aFuture = ta >= now;
    const bFuture = tb >= now;
    if (aFuture !== bFuture) return aFuture ? -1 : 1;
    return aFuture ? ta - tb : tb - ta;
  };
}

function matchNumber(item) {
  return Number((item.fixture || item).match_number ?? item.match_number ?? 9999);
}

function sortRows(rows) {
  if (state.sort === "kickoff") {
    // Default-Sort: kommende Spiele zuerst, vergangene nach unten.
    const compare = upcomingFirstComparator((it) => parseTs((it.fixture || it).kickoff_utc || it.kickoff_utc));
    return [...rows].sort((a, b) => compare(a, b) || matchNumber(a) - matchNumber(b));
  }
  return [...rows].sort((a, b) => {
    const primary = sortKey(a, state.sort) - sortKey(b, state.sort);
    if (primary) return primary;
    return matchNumber(a) - matchNumber(b);
  });
}

async function loadData() {
  try {
    const response = await fetch("data/dashboard.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
  } catch (error) {
    document.querySelector("main").innerHTML = `<div class="empty">Dashboard-Daten fehlen noch. Pipeline ausfuehren: <code>PYTHONPATH=src python3 -m wm_tipps.cli build-predictions</code> und <code>export-tips</code>.</div>`;
    return;
  }
  populateRoundFilter();
  populateFilterSelects();
  bindToolbarFilters();
  renderAll();
  mountRivalLabPanel();
  mountPlayerBoardPanel();
}

// Rundenauswahl kommt aus dem Payload, nicht aus fest verdrahtetem Markup --
// so passt das Dashboard zu jeder in rounds_local.py definierten Runde.
// Die Optionen der Panel-Filter stehen als Konstanten in dieser Datei --
// sie einmal beim Start einzuhaengen ist ehrlicher, als sie bei jedem
// Render neu zu erzeugen (T-0167).
function populateFilterSelects() {
  const fuellen = (id, werte) => {
    const select = document.getElementById(id);
    if (!select) return;
    const grundwert = select.options[0];
    select.innerHTML = "";
    select.appendChild(grundwert);
    werte.forEach(([wert, beschriftung]) => {
      const option = document.createElement("option");
      option.value = wert;
      option.textContent = beschriftung;
      select.appendChild(option);
    });
  };
  fuellen("news-severity", NEWS_SEVERITIES.map((s) => [s, s]));
  fuellen("news-category", NEWS_CATEGORIES.map((c) => [c, c]));
  fuellen("news-impact", [["with", "Nur mit Wirkung"], ["without", "Ohne Wirkung"]]);
  fuellen("history-trigger", HISTORY_TRIGGERS.map((t) => [t, t]));
}

// Einmal binden. Bis T-0167 wurden diese Selects bei jedem Render neu
// erzeugt und neu gebunden -- die Handler lebten nur so lange wie das
// Markup, und ein vergessener bind-Aufruf haette den Filter stumm gemacht.
function bindToolbarFilters() {
  const verdrahten = (id, schluessel, neuzeichnen) => {
    const select = document.getElementById(id);
    if (!select) return;
    select.addEventListener("change", (event) => {
      state[schluessel] = event.target.value;
      neuzeichnen();
    });
  };
  verdrahten("news-severity", "news_severity", renderNews);
  verdrahten("news-category", "news_category", renderNews);
  verdrahten("news-impact", "news_impact", renderNews);
  verdrahten("history-trigger", "history_trigger", renderHistory);
}

function populateRoundFilter() {
  const rounds = state.data.rounds || [];
  const select = document.getElementById("round-filter");
  if (select) {
    select.innerHTML = `<option value="">Alle Runden</option>` +
      rounds.map((r) => `<option value="${esc(r.id)}">${esc(r.name || r.id)}</option>`).join("");
  }
  const eyebrow = document.getElementById("round-eyebrow");
  if (eyebrow) {
    eyebrow.textContent = rounds.map((r) => r.name || r.id).join(" · ");
  }
}

// Runden-Zugriff zentral, damit keine Runden-ID im Frontend fest verdrahtet ist.
function defaultRoundId() {
  return state.data.default_round_id || ((state.data.rounds || [])[0] || {}).id || "";
}

function roundList() {
  return (state.data.rounds || []).map((r) => [r.id, r.name || r.id]);
}

function renderStatus() {
  const data = state.data;
  // Nur offene Spiele: fuer ein gespieltes ist "volatil" keine Aussage
  // mehr, sondern ein Rechenrest (dieselbe Klasse wie T-0169).
  const offen = data.predictions.filter((item) => item.fixture?.status !== "played");
  const volatileCount = offen.filter((item) => item.stability !== "stabil").length;
  const criticalNews = data.news.filter((item) => item.severity === "critical").length;
  // Drei echte Kennzahlen. "Watchlist" ist raus (zeigte zuletzt schlicht
  // die Spielanzahl ein zweites Mal, s. T-0169), "Stand" ist kein KPI und
  // steht als Nebenzeile unter dem Titel.
  document.getElementById("status-strip").innerHTML = [
    ["Spiele", data.fixture_count || data.predictions.length],
    ["Volatile Tipps", volatileCount],
    ["Kritische News", criticalNews],
  ].map(([label, value]) => `<div class="metric"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const stand = document.getElementById("stand");
  if (stand) stand.textContent = `Stand ${fmtDate(data.updated_at)}`;
}

const ODDS_STATUS_LABELS = {
  strong: { text: "Quoten 3+ Quellen", cls: "stabil" },
  ok: { text: "Quoten 2 Quellen", cls: "stabil" },
  single_source: { text: "Quoten 1 Quelle", cls: "warte" },
  watch_only: { text: "Quoten watch-only", cls: "warte" },
  missing: { text: "keine Quoten", cls: "volatil" },
};

function oddsStatusByMatch() {
  const matches = (state.data.odds_coverage && state.data.odds_coverage.matches) || [];
  const map = {};
  for (const row of matches) {
    if (row.match_id) map[row.match_id] = row.status;
  }
  return map;
}

function exactScoreByMatch() {
  const matches = (state.data.exact_score_odds && state.data.exact_score_odds.matches) || [];
  const map = {};
  for (const row of matches) {
    if (row.match_id) map[row.match_id] = row;
  }
  return map;
}

function renderMatches() {
  const rows = sortRows(state.data.predictions.filter((item) => {
    const haystack = `${item.fixture.home_team} ${item.fixture.away_team} ${item.fixture.venue} ${item.stability}`;
    return matchesSearch(haystack) && (!state.status || item.stability === state.status);
  }));
  const oddsStatus = oddsStatusByMatch();
  const oddsFreshness = state.data.odds_status_by_match || {};
  const exactScores = exactScoreByMatch();
  document.getElementById("matches").innerHTML = rows.length
    ? `<div class="grid">${rows.map((item) => renderMatchCard(item, oddsStatus[item.match_id], exactScores[item.match_id], oddsFreshness[item.match_id])).join("")}</div>`
    : empty("Keine Spiele fuer den Filter.");
}

function renderMatchDrilldown(item) {
  const fixture = item.fixture;
  const home = fixture.home_team;
  const away = fixture.away_team;
  const b = item.xg_breakdown || {};
  const bh = b.home || {};
  const ba = b.away || {};
  const heat = b.heat_stress || item.context?.heat_stress || {};
  const altitude = b.altitude_stress || item.context?.altitude_stress || {};
  const travel = b.travel_stress || item.context?.travel_stress || {};
  const model = item.probabilities?.model || {};
  const blended = item.probabilities?.blended || {};
  const topScoresGrid = (item.top_scores || []).slice(0, 12).map((s) => `<span class="badge">${esc(s.score)} ${fmtPct1(s.probability)}</span>`).join(" ");
  const xgRows = [
    ["base_xg", `Basis (1.28 · exp(±Elo-Diff/780))`],
    ["advantage_xg", `Heimvorteil-Kontext (USA/MEX/CAN)`],
    ["heat_effect", `Heat-Stress/WBGT und Anpassung`],
    ["altitude_effect", `Hoehenlage (Tempo + Akklimatisierung)`],
    ["travel_effect", `Reise/Erholung seit letztem Spiel`],
    ["prep_disruption_effect", `Einreise/Prep-Stoerung`],
    ["lineup_absence_effect", `XI-Ausfall Schluesselspieler`],
    ["player_intel_effect", `Player-Intel-Proxy`],
    ["news_effect", `News-Effekt (Critical/Important)`],
    ["raw", `Roh-Summe vor Clamp`],
    ["clamped", `Final (clamp 0.25-3.75)`],
  ];
  const xgTable = xgRows.map(([k, label]) => `<div class="drill-row"><span>${esc(label)}</span><b>${esc(home)} ${fmtValue(bh[k])}</b><b>${esc(away)} ${fmtValue(ba[k])}</b></div>`).join("");
  const heatHtml = heat.risk ? `
    <div class="drill-section">
      <h4>Heat-Stress</h4>
      <div class="drill-list">
        <div class="drill-row"><span>Risiko</span><b>${esc(heat.risk)}</b><b>ambient ${esc(fmtValue(heat.estimated_wbgt_c))}C</b></div>
        <div class="drill-row"><span>Effektive WBGT</span><b>${esc(fmtValue(heat.effective_wbgt_c))}C</b><b>${heat.air_conditioned ? "klimatisiert" : "offen"}</b></div>
        <div class="drill-row"><span>Anpassung</span><b>${esc(home)} ${esc(fmtValue(heat.home_adaptation))}</b><b>${esc(away)} ${esc(fmtValue(heat.away_adaptation))}</b></div>
      </div>
    </div>` : "";
  const altitudeHtml = (altitude.risk && altitude.risk !== "low") ? `
    <div class="drill-section">
      <h4>Hoehenlage</h4>
      <div class="drill-list">
        <div class="drill-row"><span>Risiko</span><b>${esc(altitude.risk)}</b><b>${esc(fmtValue(altitude.altitude_m))} m</b></div>
        <div class="drill-row"><span>Tempo-xG</span><b>${esc(fmtValue(altitude.pace_xg_delta))}</b><b></b></div>
        <div class="drill-row"><span>Akklimatisiert</span><b>${esc(home)} ${altitude.home_acclimatized ? "ja" : "nein"}</b><b>${esc(away)} ${altitude.away_acclimatized ? "ja" : "nein"}</b></div>
      </div>
    </div>` : "";
  const hasTravel = (travel.home_km != null || travel.away_km != null);
  const travelHtml = hasTravel ? `
    <div class="drill-section">
      <h4>Reise / Erholung</h4>
      <div class="drill-list">
        <div class="drill-row"><span>Distanz seit letztem Spiel</span><b>${esc(home)} ${esc(fmtValue(travel.home_km))} km</b><b>${esc(away)} ${esc(fmtValue(travel.away_km))} km</b></div>
        <div class="drill-row"><span>Erholung</span><b>${esc(home)} ${esc(fmtValue(travel.home_rest_hours))} h</b><b>${esc(away)} ${esc(fmtValue(travel.away_rest_hours))} h</b></div>
        <div class="drill-row"><span>xG-Effekt</span><b>${esc(home)} ${esc(fmtValue(travel.home_xg_delta))}</b><b>${esc(away)} ${esc(fmtValue(travel.away_xg_delta))}</b></div>
      </div>
    </div>` : "";
  const prep = b.prep_disruption || {};
  const prepSides = [prep.home, prep.away].filter(Boolean);
  const prepHtml = prepSides.length ? `
    <div class="drill-section">
      <h4>Einreise / Prep-Stoerung</h4>
      <div class="drill-list">
        ${prepSides.map((s) => `<div class="drill-row"><span>${esc(s.team)} <span class="badge ${s.basis === "manual" ? "stabil" : "warte"}">${esc(s.basis)}</span></span><b>xG ${esc(fmtValue(s.xg_delta))}</b><b>${esc(s.reason || "")}</b></div>`).join("")}
      </div>
      <p class="meta">Kleiner geclampter Malus (manueller Override schlaegt News). Nicht backtestbar -> bewusst klein, hier sichtbar statt still im Tipp.</p>
    </div>` : "";
  const probCompare = ["home", "draw", "away"].map((o) => {
    const label = o === "home" ? home : o === "away" ? away : "Remis";
    return `<div class="drill-row"><span>${esc(label)}</span><b>Modell ${fmtPct1(model[o])}</b><b>Blended ${fmtPct1(blended[o])}</b></div>`;
  }).join("");
  return `
    <details class="drilldown">
      <summary>Modell-Drilldown</summary>
      <div class="drill-section">
        <h4>xG-Aufbau (Elo-Diff ${esc(fmtValue(b.rating_diff))})</h4>
        <div class="drill-list">${xgTable}</div>
      </div>
      ${heatHtml}
      ${altitudeHtml}
      ${travelHtml}
      ${prepHtml}
      <div class="drill-section">
        <h4>Outcome-Wahrscheinlichkeiten (Modell vs. Quoten-Blend)</h4>
        <div class="drill-list">${probCompare}</div>
      </div>
      <div class="drill-section">
        <h4>Top-12 Score-Matrix</h4>
        <div class="list">${topScoresGrid}</div>
      </div>
    </details>
  `;
}

function oddsWarning(fresh) {
  if (!fresh || fresh.state === "ok") return "";
  if (fresh.state === "missing") {
    return `<div class="odds-warning"><b>⚠ Keine aktuellen Wettquoten</b> — der Tipp ist rein modellbasiert und <b>nicht marktkorrigiert</b>. Quoten in <code>data/manual_odds.csv</code> pflegen (oder via Claude für Chrome holen), dann <code>refresh-markets</code> + <code>build-predictions</code>.</div>`;
  }
  const days = fresh.age_hours != null ? Math.round(fresh.age_hours / 24) : null;
  const stand = fresh.last_updated ? fmtDate(fresh.last_updated) : "unbekannt";
  const alter = days != null ? ` · ${days} Tg alt` : "";
  return `<div class="odds-warning odds-warning--stale"><b>⚠ Wettquoten veraltet</b> — Stand ${esc(stand)}${esc(alter)}; Tipp evtl. nicht marktkorrigiert.</div>`;
}

// T-0144: News hat den Tipp gegen einen klaren Marktfavoriten gedreht. Live kosten
// genau diese Flips im Schnitt -2.10 Pkt (n=10), Flips MIT dem Markt nur -0.23.
function newsMarketWarning(matchId) {
  const rows = ((state.data.context_ablation || {}).news_market_conflicts || [])
    .filter((row) => row.match_id === matchId);
  if (!rows.length) return "";
  const c = rows[0];
  const seite = c.market_favorite === "home" ? "Heim" : "Auswärts";
  const ohne = [...new Set(rows.map((r) => r.without_news_tip))].join(" / ");
  return `<div class="odds-warning odds-warning--news">
    <b>⚠ News dreht den Tipp gegen den Markt</b> — der Markt sieht ${esc(seite)} bei
    <b>${fmtPct(c.market_probability)}</b>; ohne den News-Effekt wäre der Tipp <b>${esc(ohne)}</b>.
    Solche Flips kosteten live im Schnitt <b>−2,1 Pkt</b> (n=10); der dPkt-Gate stuft
    <code>news</code> auf <code>halve</code>. Vor Abgabe prüfen.
  </div>`;
}

function renderMatchCard(item, oddsStatus, exactScore, oddsFreshness) {
  const fixture = item.fixture;
  const p = item.probabilities.blended;
  const newsBadges = item.news.slice(0, 3).map((news) => `<span class="badge ${news.severity === "critical" ? "volatil" : "warte"}">${esc(news.severity)}: ${esc(news.categories?.[0] || "news")}</span>`).join(" ");
  const scores = item.top_scores.slice(0, 6).map((score) => `<span class="badge">${esc(score.score)} ${fmtPct(score.probability)}</span>`).join(" ");
  const oddsMeta = ODDS_STATUS_LABELS[oddsStatus];
  const oddsBadge = oddsMeta ? `<span class="badge ${oddsMeta.cls}">${esc(oddsMeta.text)}</span>` : "";
  const exactBadge = exactScore ? `<span class="badge warte">Bwin Exact-Score</span>` : "";
  return `
    <article class="card">
      <h2>${esc(fixture.home_team)} - ${esc(fixture.away_team)}</h2>
      <div class="meta">Spiel ${esc(fixture.match_number || "")} · ${fmtDate(fixture.kickoff_utc)} · ${esc(fixture.venue)} · Gruppe ${esc(fixture.group || "")}</div>
      <div class="tip-badges-row">
        <span class="badge ${statusClass(item.stability)}">${esc(item.stability)}</span>
        ${oddsBadge}
        ${exactBadge}
      </div>
      ${oddsWarning(oddsFreshness)}
      ${newsMarketWarning(item.match_id)}
      ${renderRoundTips(item)}
      <div class="prob-grid">
        <div class="prob"><span>${esc(fixture.home_team)}</span><b>${fmtPct(p.home)}</b></div>
        <div class="prob"><span>Remis</span><b>${fmtPct(p.draw)}</b></div>
        <div class="prob"><span>${esc(fixture.away_team)}</span><b>${fmtPct(p.away)}</b></div>
      </div>
      <p class="meta">xG ${esc(fixture.home_team)} ${item.xg.home} · ${esc(fixture.away_team)} ${item.xg.away}</p>
      <p>${item.explanation.map(esc).join("<br>")}</p>
      <div class="list">
        <div>${scores}</div>
        <div>${newsBadges || '<span class="badge stabil">keine frischen Flags</span>'}</div>
      </div>
      ${renderMatchDrilldown(item)}
    </article>
  `;
}

function deficitPolicyRec(roundId, matchId) {
  const rd = ((state.data.deficit_policy || {}).rounds || {})[roundId];
  if (!rd || !rd.upcoming) return null;
  return rd.upcoming.find((r) => r.match_id === matchId) || null;
}

function renderRoundTips(item) {
  const rounds = state.data.rounds || [];
  const tips = item.round_tips || {};
  const rows = rounds
    .map((round) => ({ round, tip: tips[round.id] }))
    .filter((row) => row.tip);
  if (!rows.length) return "";
  return `<div class="round-tip-grid">${rows.map(({ round, tip }) => {
    const pol = deficitPolicyRec(round.id, item.match_id);
    const chase = pol && pol.deviates_from_ep
      ? `<span class="badge volatil" title="Deficit-Policy: zurueck -> dekorrelieren (P(Feld schlagen) ${esc(pol.chase_pbeat)})">→ Chase ${esc(pol.policy_tip)}</span>`
      : "";
    return `
    <div class="round-tip">
      <span>Tipp ${esc(round.name || round.id)}</span>
      <b>${esc(tip.tip || "n/a")}</b>${chase}
      <small>EP ${esc(fmtValue(tip.expected_points))} · ${esc(round.result_scope || "")}</small>
    </div>`;
  }).join("")}</div>`;
}



function newsIsModelRelevant(item) {
  if (item.model_relevant === false) return false;
  if (item.relevance === "low") return false;
  return true;
}

function newsHasImpact(item) {
  if (item.freshness === "stale") return false;
  if (!item.teams || item.teams.length === 0) return false;
  if (!newsIsModelRelevant(item)) return false;
  return item.severity === "critical" || item.severity === "important";
}

function newsImpactLabel(item) {
  // Spiegelt news.team_news_impact + model.expected_goals: nur Injury/
  // Illness/Suspension bewegen xG direkt; andere kritische News sind Watchlist-Signale.
  const teams = item.teams || [];
  if (item.freshness === "stale") return "stale — kein Modell-Effekt";
  if (!newsIsModelRelevant(item)) {
    return item.relevance_reason ? `nicht modellrelevant (${item.relevance_reason})` : "nicht modellrelevant";
  }
  if (teams.length === 0) return "ohne Team-Tag — kein Effekt";
  const directCategories = ["injury", "illness", "suspension"];
  if (!(item.categories || []).some((category) => directCategories.includes(category))) {
    if (item.severity === "critical" || item.severity === "important") {
      return "Watchlist-Signal ohne direkte xG-Aenderung";
    }
    return "kein direkter Modell-Effekt";
  }
  const map = {
    critical: { attack: -0.18, defense: 0.10 },
    important: { attack: -0.07, defense: 0.04 },
  };
  const delta = map[item.severity];
  if (!delta) return "kein direkter Modell-Effekt";
  const opponent = (delta.defense * 0.45).toFixed(3);
  return `${teams.join(", ")}: xG ${delta.attack.toFixed(2)} · Gegner-xG +${opponent}`;
}

function renderDataQuality() {
  const dq = (state.data.data_quality && state.data.data_quality.news) || [];
  if (!dq.length) return "";
  const badge = (status) => status === "ok" ? "stabil" : status === "error" ? "volatil" : "warte";
  const items = dq.map((row) => {
    const total = row.items_total ?? 0;
    const fresh = row.items_fresh ?? 0;
    const error = row.error ? ` · ${esc(row.error)}` : "";
    return `<span class="badge ${badge(row.status)}">${esc(row.source)}: ${esc(row.status)} (${fresh}/${total} frisch)${error}</span>`;
  }).join(" ");
  return `<section class="card"><h3>Datenqualitaet (News-Quellen)</h3><div class="list">${items}</div></section>`;
}

function renderTeamIntel() {
  const intel = state.data.team_intel || {};
  const summary = intel.summary || {};
  const hostRows = intel.host_context || [];
  const checklist = (intel.matchday_checklist || []).slice(0, 8);
  const missingTeams = intel.missing_team_specific_official || [];
  if (!summary.source_count) return "";
  const statusCounts = Object.entries(summary.status_counts || {})
    .map(([status, count]) => `<span class="badge ${status.includes("blocked") ? "warte" : "stabil"}">${esc(status)} ${esc(count)}</span>`)
    .join(" ");
  const metrics = [
    ["Quellen", summary.source_count || 0],
    ["Offiziell", summary.official_source_count || 0],
    ["Aktiv", summary.active_sources || 0],
    ["Lineup-Watch", summary.lineup_watch_sources || 0],
    ["Teamspezifisch", `${summary.fixture_teams_with_team_specific_official || 0}/${summary.fixture_team_count || 0}`],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const hostHtml = hostRows.length ? hostRows.map((row) => `
    <div class="line">
      <div><b>${esc(row.name)}</b><br><span class="meta">${esc((row.countries || []).join(", "))} · ${esc((row.signals || []).join(", "))}</span></div>
      <div><span class="badge ${row.status === "active_page" ? "stabil" : "warte"}">${esc(row.status)}</span></div>
    </div>`).join("") : `<div class="empty">Noch keine Host-Kontext-Quellen katalogisiert.</div>`;
  const checklistHtml = checklist.length ? checklist.map((row) => {
    const due = Object.fromEntries((row.checks || []).map((check) => [check.type, check.due_at]));
    return `
      <div class="line">
        <div>
          <b>${esc(row.match)}</b><br>
          <span class="meta">Spiel ${esc(row.match_number || "")} · ${fmtDate(row.kickoff_utc)} · ${esc(row.venue || "")}</span><br>
          <span class="meta">Lineup ${fmtDate(due.confirmed_lineup)} · Wetter ${fmtDate(due.final_weather)} · Pitch ${fmtDate(due.pitch_context)}</span>
          ${(row.missing || []).length ? `<br><span class="meta">Luecken: ${esc((row.missing || []).join(", "))}</span>` : ""}
        </div>
        <div><span class="badge ${row.status === "scheduled" ? "stabil" : "warte"}">${esc(row.status)}</span></div>
      </div>`;
  }).join("") : `<div class="empty">Keine Matchday-Checklist vorhanden.</div>`;
  const missingHtml = missingTeams.length
    ? `<div class="meta">Noch ohne teamspezifische Verbandsquelle: ${esc(missingTeams.slice(0, 12).join(", "))}${missingTeams.length > 12 ? ` +${missingTeams.length - 12}` : ""}</div>`
    : `<div class="meta">Alle Fixture-Teams haben mindestens eine teamspezifische Verbandsquelle.</div>`;
  return `
    <section class="card">
      <h3>Team-Intel-Quellen</h3>
      <div class="metrics-row">${metrics}</div>
      <div class="list">${statusCounts}</div>
      ${missingHtml}
      <h4>Wetter / Host-Kontext</h4>
      <div class="list">${hostHtml}</div>
      <h4>Naechste Matchday-Checks</h4>
      <div class="list">${checklistHtml}</div>
    </section>`;
}

function renderNews() {
  const rows = state.data.news
    .filter((item) => matchesSearch(`${item.title} ${item.source} ${(item.teams || []).join(" ")} ${(item.categories || []).join(" ")}`))
    .filter((item) => !state.news_severity || item.severity === state.news_severity)
    .filter((item) => !state.news_category || (item.categories || []).includes(state.news_category))
    .filter((item) => {
      if (state.news_impact === "with") return newsHasImpact(item);
      if (state.news_impact === "without") return !newsHasImpact(item);
      return true;
    })
    .slice()
    .sort((a, b) => {
      const sev = (SEVERITY_ORDER[b.severity] || 0) - (SEVERITY_ORDER[a.severity] || 0);
      if (sev) return sev;
      return (Date.parse(b.published_at) || 0) - (Date.parse(a.published_at) || 0);
    });
  const tableHtml = rows.length ? `
    <div class="table-wrap"><table>
      <thead><tr><th>Zeit</th><th>Schwere</th><th>Kategorie</th><th>Teams</th><th>Wirkung</th><th>Meldung</th><th>Quelle</th></tr></thead>
      <tbody>${rows.map((item) => `
        <tr>
          <td>${fmtDate(item.published_at)}</td>
          <td><span class="badge ${item.severity === "critical" ? "volatil" : item.severity === "important" ? "warte" : "stabil"}">${esc(item.severity)}</span></td>
          <td>${esc((item.categories || []).join(", "))}</td>
          <td>${esc((item.teams || []).join(", "))}</td>
          <td><span class="meta">${esc(newsImpactLabel(item))}</span></td>
          <td>${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.title)}</a>` : esc(item.title || item.summary)}</td>
          <td>${esc(item.source)}</td>
        </tr>`).join("")}</tbody>
    </table></div>` : empty("Noch keine News. Manuelle Notizen in data/manual_news.json oder refresh-news --live nutzen.");
  document.getElementById("news").innerHTML = renderDataQuality() + renderTeamIntel() + tableHtml;
}

function impliedDecimal(prob) {
  if (typeof prob !== "number" || prob <= 0) return "—";
  return (1 / prob).toFixed(2);
}

function renderModelImplied() {
  const predictions = state.data.predictions || [];
  const filtered = sortRows(predictions.filter((item) => matchesSearch(`${item.fixture.home_team} ${item.fixture.away_team} ${item.fixture.venue}`)));
  if (!filtered.length) return `<div class="empty">Keine Spiele fuer den Filter.</div>`;
  return filtered.map((item) => {
    const f = item.fixture;
    const m = item.probabilities?.model || {};
    const b = item.probabilities?.blended || {};
    const importedOdds = item.odds;
    const sourceLabel = importedOdds?.source_count > 1
      ? `${importedOdds.source_count} Quellen (${(importedOdds.sources || []).join(", ")})`
      : importedOdds?.source;
    const importedRow = importedOdds && importedOdds.decimal_odds ? `<br><span class="meta">Import-Konsens (${esc(sourceLabel)}): ${esc(fmtValue(importedOdds.decimal_odds.home))} / ${esc(fmtValue(importedOdds.decimal_odds.draw))} / ${esc(fmtValue(importedOdds.decimal_odds.away))}</span>` : "";
    return `
      <div class="line">
        <div><b>${esc(f.home_team)} - ${esc(f.away_team)}</b><br><span class="meta">Spiel ${esc(f.match_number || "")} · ${fmtDate(f.kickoff_utc)}</span></div>
        <div>
          <span class="meta">Modell-Implied: ${impliedDecimal(m.home)} / ${impliedDecimal(m.draw)} / ${impliedDecimal(m.away)}</span><br>
          <span class="meta">Mit Markt-Blend: ${impliedDecimal(b.home)} / ${impliedDecimal(b.draw)} / ${impliedDecimal(b.away)}</span>
          ${importedRow}
        </div>
      </div>`;
  }).join("");
}

function coverageClass(status) {
  if (status === "strong" || status === "ok") return "stabil";
  if (status === "single_source" || status === "watch_only") return "warte";
  return "volatil";
}

function renderOddsCoverage() {
  const coverage = state.data.odds_coverage || {};
  const summary = coverage.summary || {};
  const rows = sortRows((coverage.matches || []).filter((item) => {
    const haystack = `${item.match} ${item.match_id} ${item.status} ${(item.raw_sources || []).join(" ")}`;
    return matchesSearch(haystack);
  }));
  const metrics = [
    ["Konsens", `${summary.with_consensus || 0}/${summary.total || 0}`],
    ["3+ Quellen", summary.strong || 0],
    ["Fehlend", summary.missing || 0],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const table = rows.length ? `
    <div class="table-wrap compact"><table>
      <thead><tr><th>Anpfiff</th><th>Spiel</th><th>Konsens</th><th>Rohquellen</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td>${fmtDate(row.kickoff_utc)}</td>
          <td>${esc(row.match)}<br><span class="meta">Spiel ${esc(row.match_number || "")} · ${esc(row.match_id)}</span></td>
          <td><span class="badge ${coverageClass(row.status)}">${esc(row.status)}</span><br><span class="meta">${esc(row.consensus_source_count || 0)} Quelle(n)</span></td>
          <td>${esc((row.raw_sources || []).join(", ") || "—")}<br><span class="meta">Overround ${esc(fmtValue(row.overround_min))} - ${esc(fmtValue(row.overround_max))}</span></td>
        </tr>`).join("")}</tbody>
    </table></div>` : empty("Keine Coverage-Daten fuer den Filter.");
  return `<div class="metrics-row">${metrics}</div>${table}`;
}

function renderOddsFreshness() {
  const freshness = state.data.odds_freshness || {};
  if (!freshness.source) {
    return empty("Noch keine Quoten-Freshness berechnet. Pipeline ausfuehren: build-dashboard oder update-all.");
  }
  const missing = sortRows(freshness.missing || []);
  const stale = sortRows(freshness.stale || []);
  const sources = freshness.sources || [];
  const metrics = [
    ["Status", freshness.status || "missing"],
    ["Bwin frisch", `${freshness.fresh_matches || 0}/${freshness.future_matches || 0}`],
    ["Fehlend", freshness.missing_matches || 0],
    ["Alt", freshness.stale_matches || 0],
    ["Letztes Bwin", fmtDate(freshness.latest_source_update)],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const gate = `<p class="meta"><span class="badge ${qualityClass(freshness.status)}">${esc(freshness.status || "missing")}</span> ${esc(freshness.status_detail || "")} Frisch = ${esc(freshness.max_age_hours || 24)}h.</p>`;
  const missingHtml = missing.length ? `
    <details class="drilldown compact" open><summary>Fehlende frische Bwin-Quoten (${esc(missing.length)})</summary>
      <div class="drill-list compact">${missing.map((row) => `
        <div class="line">
          <div><b>${esc(row.match)}</b><br><span class="meta">Spiel ${esc(row.match_number || "")} · ${fmtDate(row.kickoff_utc)} · ${esc(row.match_id)}</span></div>
          <div><span class="badge volatil">${esc(row.reason || "missing")}</span></div>
        </div>`).join("")}</div>
    </details>` : `<p class="meta">Keine fehlenden kommenden Bwin-Quoten.</p>`;
  const staleHtml = stale.length ? `
    <details class="drilldown compact"><summary>Alte Bwin-Quoten (${esc(stale.length)})</summary>
      <div class="drill-list compact">${stale.map((row) => `
        <div class="line">
          <div><b>${esc(row.match)}</b><br><span class="meta">Spiel ${esc(row.match_number || "")} · ${fmtDate(row.kickoff_utc)} · zuletzt ${fmtDate(row.last_updated)}</span></div>
          <div><span class="badge warte">${esc(row.age_hours)}h</span></div>
        </div>`).join("")}</div>
    </details>` : "";
  const sourceRows = sources.length ? `
    <details class="drilldown compact"><summary>Quellenalter (${esc(sources.length)})</summary>
      <div class="table-wrap compact"><table>
        <thead><tr><th>Quelle</th><th>Frisch</th><th>Letztes Update</th><th>Status</th></tr></thead>
        <tbody>${sources.map((row) => `
          <tr>
            <td>${esc(row.source)}</td>
            <td>${esc(row.fresh_rows || 0)}/${esc(row.rows || 0)}</td>
            <td>${fmtDate(row.latest_updated_at)}<br><span class="meta">${esc(fmtValue(row.latest_age_hours))}h alt</span></td>
            <td><span class="badge ${qualityClass(row.status)}">${esc(row.status || "watch")}</span></td>
          </tr>`).join("")}</tbody>
      </table></div>
    </details>` : "";
  return `<div class="metrics-row">${metrics}</div>${gate}${missingHtml}${staleHtml}${sourceRows}`;
}

function renderSourceWatch() {
  const watch = state.data.source_watch || {};
  const sources = (watch.sources || []).filter((item) => matchesSearch(`${item.name || ""} ${item.status || ""} ${(item.flags || []).join(" ")}`));
  if (!sources.length) return empty("Keine Source-Watch-Daten. Pipeline ausfuehren: source-watch oder watch.");
  return sources.map((source) => {
    const probe = source.live_probe || {};
    const manual = source.manual_observation || {};
    const flags = (source.flags || []).map((flag) => `<span class="badge ${source.status === "ok" ? "stabil" : "warte"}">${esc(flag)}</span>`).join(" ");
    const actions = (source.actions || []).map((action) => `<div class="meta">${esc(action)}</div>`).join("");
    const probeBits = [
      probe.status ? `Probe ${probe.status}` : "",
      Number.isInteger(probe.match_count) ? `${probe.match_count} Spiele sichtbar` : "",
      Number.isInteger(probe.overall_market_count) ? `${probe.overall_market_count} Gesamtwetten` : "",
      Number.isInteger(probe.special_market_count) ? `${probe.special_market_count} Spezial` : "",
      probe.exact_score_visible ? "Exact-Score-Hinweis sichtbar" : "",
    ].filter(Boolean).join(" · ");
    const manualBits = [
      manual.observed_at ? `Browser-Snapshot ${fmtDate(manual.observed_at)}` : "",
      Number.isInteger(manual.match_count) ? `${manual.match_count} Spiele` : "",
      Number.isInteger(manual.overall_market_count) ? `${manual.overall_market_count} Gesamtwetten` : "",
      Number.isInteger(manual.special_market_count) ? `${manual.special_market_count} Spezial` : "",
      Number.isInteger(manual.event_market_count) ? `${manual.event_market_count} Event-Maerkte` : "",
      manual.exact_score_status ? `Exact-Score ${manual.exact_score_status}` : "",
      Number.isInteger(manual.exact_score_prices_count) ? `${manual.exact_score_prices_count} Preise` : "",
      manual.exact_score_has_more ? "Mehr anzeigen offen" : "",
    ].filter(Boolean).join(" · ");
    const exactScoreSample = (manual.exact_score_sample || [])
      .slice(0, 6)
      .map((price) => `${price.selection} ${fmtValue(price.decimal_odds)}`)
      .join(" · ");
    return `
      <div class="line">
        <div>
          <b>${esc(source.name || source.id)}</b><br>
          <span class="meta">Import ${esc(source.imported_match_odds || 0)}/${esc(source.fixture_count || 0)} Spiele · ${esc(probeBits || "Live-Probe nicht gelaufen")}</span>
          ${manualBits ? `<br><span class="meta">${esc(manualBits)}</span>` : ""}
          ${exactScoreSample ? `<br><span class="meta">Exact-Score-Beispiel: ${esc(exactScoreSample)}</span>` : ""}
          <div class="list">${flags || '<span class="badge stabil">ok</span>'}</div>
          ${actions}
        </div>
        <div><span class="badge ${source.status === "ok" ? "stabil" : "warte"}">${esc(source.status || "watch")}</span></div>
      </div>`;
  }).join("");
}

function renderExactScoreMarkets() {
  const exact = state.data.exact_score_odds || {};
  const summary = exact.summary || {};
  const calibration = exact.calibration || {};
  const rows = sortRows((exact.matches || []).filter((item) => {
    const haystack = `${item.match || ""} ${item.match_id || ""} ${item.source || ""} ${item.model_favorite_score || ""} ${item.market_favorite_score || ""}`;
    return matchesSearch(haystack);
  }));
  const metrics = [
    ["Bwin sichtbar", summary.visible_bwin_events || 0],
    ["Importiert", summary.imported_matches || 0],
    ["Noch offen", summary.not_imported_visible_events || 0],
    ["Modell/Bwin abw.", summary.model_market_favorite_disagreements || 0],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const table = rows.length ? `
    <div class="table-wrap compact"><table>
      <thead><tr><th>Anpfiff</th><th>Spiel</th><th>Modell vs Bwin</th><th>Tipp-Quote</th><th>Top-Markt</th></tr></thead>
      <tbody>${rows.map((row) => {
        const top = (row.market_top_scores || []).slice(0, 5).map((s) => `${s.score} ${fmtValue(s.decimal_odds)}`).join(" · ");
        const reasons = (row.quality?.reasons || []).join(", ");
        return `<tr>
          <td>${fmtDate(row.kickoff_utc)}</td>
          <td>${esc(row.match)}<br><span class="meta">Spiel ${esc(row.match_number || "")} · ${esc(row.match_id)}</span></td>
          <td><span class="meta">Modell ${esc(row.model_favorite_score || "—")} · Bwin ${esc(row.market_favorite_score || "—")} @ ${esc(fmtValue(row.market_favorite_odds))}</span><br><span class="meta">Overlap ${esc((row.top_overlap || []).join(", ") || "—")} · expl. Overround ${esc(fmtValue(row.overround_explicit))}</span></td>
          <td><b>${esc(row.recommended_tip || "—")}</b><br><span class="meta">Bwin ${esc(fmtValue(row.recommended_tip_odds))} · ${esc(row.quality?.status || "watch_only")}${reasons ? ` · ${esc(reasons)}` : ""}</span></td>
          <td><span class="meta">${esc(top || "—")}</span></td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>` : `<div class="empty">Noch keine Exact-Score-Importe. Sichtbare Bwin-Event-URLs liegen in <code>data/manual_exact_score_odds.json</code>.</div>`;
  const audit = Number.isInteger(calibration.searched_sources_count)
    ? ` · Audit ${esc(calibration.accepted_sources_count || 0)}/${esc(calibration.searched_sources_count)} akzeptiert`
    : "";
  return `<div class="metrics-row">${metrics}</div><p class="meta">Bwin Exact-Score ist aktuell ${esc(calibration.status || "watch_only")}: ${esc(calibration.reason || "Backtest/Kalibrierung offen")}${audit}. Es veraendert Tipps erst nach positiver historischer Kalibrierung.</p>${table}`;
}

// Quoten-&-Maerkte-Kachel: Hoehe begrenzt + aufklappbar. Der Aufklapp-Status
// wird in state.expandedCards (per Titel) gehalten, ueberlebt also Re-Renders.
// `breit` fuer Karten mit mehrspaltigen Tabellen: im Raster ist eine Karte
// nur ~370px breit, eine Tabelle mit 4-5 Textspalten passt da nicht und
// wurde bisher am Kartenrand abgeschnitten (R-25). Solche Karten nehmen die
// volle Zeile ein, statt den Inhalt unerreichbar zu machen.
function marketCard(title, bodyHtml, breit = false) {
  const open = state.expandedCards.has(title);
  return `
      <section class="card card--clamp${breit ? " card--wide" : ""}${open ? " is-open" : ""}" data-card-title="${esc(title)}">
        <h2>${esc(title)}</h2>
        <div class="card__body">${bodyHtml}</div>
        <button type="button" class="card__toggle" data-card-toggle="${esc(title)}" hidden>${open ? "Einklappen ▴" : "Aufklappen ▾"}</button>
      </section>`;
}

// Zeigt den Aufklapp-Button nur, wenn die Kachel tatsaechlich ueberlaeuft
// (oder bereits offen ist). Messung braucht einen sichtbaren Tab -> wird
// nach dem Render UND beim Aktivieren des Markets-Tabs aufgerufen.
// Seit T-0168 stehen aufklappbare Kacheln in ZWEI Panels (markets +
// analyse). Wer hier nur #markets abfragt, laesst die Analyse-Kacheln
// stumm -- der Aufklapp-Knopf bliebe dort dauerhaft verborgen.
const CLAMP_PANELS = ["markets", "analyse"];

function clampMarketCards() {
  CLAMP_PANELS.forEach((id) => {
    const panel = document.getElementById(id);
    if (!panel) return;
    panel.querySelectorAll(".card--clamp").forEach((card) => {
      const body = card.querySelector(".card__body");
      const toggle = card.querySelector(".card__toggle");
      if (!body || !toggle) return;
      const overflowing = card.classList.contains("is-open") || body.scrollHeight > body.clientHeight + 4;
      toggle.hidden = !overflowing;
    });
  });
}

function renderMarkets() {
  const markets = (state.data.markets.markets || []).filter((item) => matchesSearch(`${item.market || ""} ${item.category || ""} ${item.source || ""} ${item.outcome || ""}`));
  const coverageHtml = renderOddsCoverage();
  const freshnessHtml = renderOddsFreshness();
  const backtestHtml = renderBacktestWorth();
  const ablationHtml = renderContextAblation();
  const blendSweepHtml = renderBlendSweep();
  const calibrateFitHtml = renderCalibrateFit();
  const strategyAbHtml = renderStrategyAb();
  const riskDialHtml = renderRiskDial();
  const favCalibHtml = renderFavoriteCalibration();
  const rivalProfilesHtml = renderRivalProfiles();
  const deficitPolicyHtml = renderDeficitPolicy();
  const roleAbHtml = renderRoleAb();
  const newsAuditHtml = renderNewsAudit();
  const liveEvalHtml = renderLiveEval();
  const sourceWatchHtml = renderSourceWatch();
  const exactScoreHtml = renderExactScoreMarkets();
  const impliedHtml = renderModelImplied();
  const oddsHistoryHtml = renderOddsHistory();
  const signalBreakerHtml = renderSignalBreaker();
  const totalsAdjustHtml = renderTotalsAdjust();
  const newsReviewHtml = renderNewsReview();
  const lineupLockHtml = renderLineupLock();
  const importedOdds = (state.data.markets.odds || []).filter((item) => matchesSearch(`${item.match_id} ${item.source}`));
  const importedHtml = importedOdds.length ? (() => {
    const byMatch = {};
    importedOdds.forEach((item) => { (byMatch[item.match_id] = byMatch[item.match_id] || []).push(item); });
    return Object.keys(byMatch).sort().map((mid) => {
      const books = byMatch[mid].slice().sort((a, b) => String(a.source).localeCompare(String(b.source)));
      const rows = books.map((item) => {
        const overround = typeof item.overround === "number" ? item.overround.toFixed(3) : "n/a";
        const quality = item.quality?.status || "watch_only";
        const reasons = (item.quality?.reasons || []).length ? ` · ${(item.quality.reasons || []).join(", ")}` : "";
        return `<div class="line">
          <div><span class="meta">${esc(item.source)} · ${fmtDate(item.last_updated)} · ${esc(quality)} · OR ${esc(overround)}${esc(reasons)}</span></div>
          <div>${fmtPct(item.probabilities.home)} / ${fmtPct(item.probabilities.draw)} / ${fmtPct(item.probabilities.away)}</div>
        </div>`;
      }).join("");
      return `<details class="drilldown compact"><summary><b>${esc(mid)}</b> · ${esc(books.length)} Quellen</summary><div class="drill-list compact">${rows}</div></details>`;
    }).join("");
  })() : `<div class="empty">
      <p>Keine importierten Quoten. <code>data/manual_odds.csv</code> manuell pflegen, dann <code>refresh-odds</code> oder <code>watch</code>.</p>
      <p class="meta">Format (eine Zeile pro Spiel, decimal odds; leere Zellen erlaubt):</p>
      <pre style="font-size: 12px; background: var(--surface); padding: 8px; border-radius: 4px; overflow-x: auto;">match_id,source,home,draw,away,last_updated
ga-001,bwin,3.20,3.40,2.20,2026-06-10T10:00:00+00:00
ga-002,quotenvergleich,1.85,3.50,4.20,2026-06-11T08:00:00+00:00</pre>
      <p class="meta">Pipeline bildet pro Spiel einen no-vig-Konsens aus brauchbaren Quellen und kalibriert damit den 80/20-Modell-Markt-Blend (T-0079).</p>
    </div>`;
  const marketHtml = markets.length ? markets.map((item) => `
    <div class="line">
      <div><b>${esc(item.market || item.category)}</b><br><span class="meta">${esc(item.source || "manual")} · ${esc(item.outcome || "")}</span></div>
      <div>${fmtPct(item.probability)} · ${esc(item.quality?.status || "watch_only")}</div>
    </div>`).join("") : `<div class="empty">
      <p>Keine zusaetzlichen Marktsignale. <code>data/manual_markets.json</code> manuell pflegen, dann <code>refresh-markets</code>.</p>
      <p class="meta">Format (Liste von dicts; category aus {world_champion, semifinalist, top_scorer_team}):</p>
      <pre style="font-size: 12px; background: var(--surface); padding: 8px; border-radius: 4px; overflow-x: auto;">[
  {"category": "world_champion", "outcome": "Spain", "probability": 0.16,
   "source": "bwin_de_gesamtwetten_2026", "source_type": "bookmaker_futures",
   "last_updated": "2026-05-10T12:00:00+00:00"}
]</pre>
      <p class="meta">Quality-Status (usable/watch_only) wird automatisch aus Markttyp, Wahrscheinlichkeit und Alter berechnet. market_probability erscheint als Info-Feld pro Team in den Bonus-Listen.</p>
    </div>`;
  // "Quoten & Maerkte" enthaelt nur noch, was wirklich Quoten und Maerkte
  // sind. Alles andere -- Modell-Diagnostik, Strategie/Pool und die
  // operativen Gates -- lag hier bisher unter falscher Ueberschrift und
  // wandert nach "Analyse" (T-0168).
  document.getElementById("markets").innerHTML = `
    <div class="grid">
      ${marketCard("Quoten-Coverage", coverageHtml, true)}
      ${marketCard("Quoten-Freshness", freshnessHtml, true)}
      ${marketCard("Source-Watch", sourceWatchHtml)}
      ${marketCard("Exact-Score (Bwin)", exactScoreHtml, true)}
      ${marketCard("Modell-Implied + Konsens", `<p class="meta">Modell-Implied kommt aus dem reinen Modell, Markt-Blend aus Modell plus no-vig-Quotenkonsens.</p>${impliedHtml}`)}
      ${marketCard("Rohquoten", importedHtml)}
      ${marketCard("Weitere Maerkte (Futures, Polymarket o.ae.)", marketHtml)}
      ${marketCard("Quotenbewegung (Snapshot-Historie)", oddsHistoryHtml)}
    </div>`;

  document.getElementById("analyse-cards").innerHTML = `
    <h2 class="section-head">Modell-Diagnostik</h2>
    <div class="grid">
      ${marketCard("Lohnt sich das?", backtestHtml)}
      ${marketCard("Kontext-Ablation", ablationHtml)}
      ${marketCard("Markt-Blend-Sweep", blendSweepHtml)}
      ${marketCard("Backtest-Fit (Kalibrierung)", calibrateFitHtml)}
      ${marketCard("Rollen-A/B (bringen Aufstellungen was?)", roleAbHtml)}
      ${marketCard("News-xG-Audit (Fehlzuordnung?)", newsAuditHtml)}
      ${marketCard("Live-Auswertung (echte Ergebnisse)", liveEvalHtml)}
    </div>

    <h2 class="section-head">Strategie und Pool</h2>
    <div class="grid">
      ${marketCard("Rivalen-Profile (Pool)", rivalProfilesHtml)}
      ${marketCard("Aggressivitaets-A/B (zu konservativ?)", strategyAbHtml)}
      ${marketCard("Risk-Dial (Chase vs Protect)", riskDialHtml)}
      ${marketCard("Deficit-Policy (Chase vs Protect)", deficitPolicyHtml)}
      ${marketCard("Favoriten-/Gastgeber-Kalibrierung", favCalibHtml)}
    </div>

    <h2 class="section-head">Gates und Queues</h2>
    <div class="grid">
      ${marketCard("Live-Signal-Breaker (gated)", signalBreakerHtml)}
      ${marketCard("Turnier-Torlevel (gated)", totalsAdjustHtml)}
      ${marketCard("News-Review-Queue (promote/dismiss)", newsReviewHtml)}
      ${marketCard("Lineup-Lock (Pre-Kickoff)", lineupLockHtml)}
    </div>

    <h2 class="section-head">Spieltag</h2>
    ${matchdaySections()}

    <h2 class="section-head">Pipeline</h2>
    ${pipelineSections()}`;
  bindPipelineActions();
  clampMarketCards();
}

function renderOddsHistory() {
  const oh = state.data.odds_history || {};
  if (!oh.snapshot_count) {
    return `<div class="empty">Noch keine Snapshots. <code>refresh-odds</code> / <code>refresh-bwin-exact-scores</code>.</div>`;
  }
  const sp = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1);
  const metrics = [
    ["Snapshots gesamt", oh.snapshot_count || 0],
    ["Verfolgte Reihen (match·markt·quelle)", oh.keys || 0],
    ["Davon bewegt", `<span class="badge ${(oh.moved_count || 0) > 0 ? "volatil" : "stabil"}">${oh.moved_count || 0}</span>`],
  ].map(([l, v]) => `<div class="line"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
  const moved = (oh.movements || []).filter((m) => m.moved);
  const movedHtml = moved.length ? `
    <details class="drilldown compact"><summary>Bewegte Quoten (${esc(moved.length)})</summary>
      <div class="drill-list compact">${moved.slice(0, 12).map((m) => {
        const drift = m.prob_drift ? ` · Drift H/U/A ${sp(m.prob_drift.home || 0)}/${sp(m.prob_drift.draw || 0)}/${sp(m.prob_drift.away || 0)} pp` : "";
        return `<div><b>${esc(m.match_id)} · ${esc(m.market)}</b><br><span class="meta">${esc(m.source)} · ${esc(m.snapshots)} Snapshots${drift}</span></div>`;
      }).join("")}</div></details>` : `<p class="meta">Aktuell 0 bewegt (Baseline). Bewegung erscheint, sobald sich Quoten aendern (taeglich uebers Briefing / Chrome-Pull).</p>`;
  return `<div class="list">${metrics}</div>${movedHtml}<p class="meta">Append-on-change aus <code>data/odds_snapshots.jsonl</code>. Details: <code>odds-history</code>.</p>`;
}

function renderSignalBreaker() {
  const sb = state.data.signal_breaker || {};
  if (!sb.signals) {
    return `<div class="empty">Noch keine Daten. <code>signal-breaker</code>.</div>`;
  }
  const head = [
    ["Spiele mit Ergebnis", sb.played_with_result || 0],
    ["Min. Feuerungen je Signal", sb.min_firings || 10],
  ].map(([l, v]) => `<div class="line"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
  const sig = (sb.signals || []).map((s) => {
    const cls = s.status === "review" ? "volatil" : s.status === "ok" ? "stabil" : "warte";
    return `<div class="line"><span>${esc(s.signal)} <span class="meta">(${esc(s.firings)} Feuerungen)</span></span><b><span class="badge ${cls}">${esc(s.status)}</span> ${esc(s.recommendation)}</b></div>`;
  }).join("");
  return `<div class="list">${head}</div><div class="list">${sig}</div><p class="meta">${esc(sb.note || "")}</p>`;
}

function renderTotalsAdjust() {
  const ta = state.data.totals_adjust || {};
  const cls = ta.status === "active" ? "stabil" : "warte";
  const metrics = [
    ["Spiele", `${esc(ta.matches || 0)} / ${esc(ta.min_matches || 15)}`],
    ["Status", `<span class="badge ${cls}">${esc(ta.status || "insufficient_data")}</span>`],
    ["Tore real vs erwartet", `${esc(ta.actual_goals)} vs ${esc(ta.expected_goals)}`],
    ["Ratio (real/erwartet)", esc(ta.ratio == null ? "n/a" : ta.ratio)],
    ["Empfohlener λ-Multiplikator", esc(ta.recommended_multiplier == null ? "n/a" : ta.recommended_multiplier)],
    ["Angewendet", esc(ta.applied_multiplier)],
  ].map(([l, v]) => `<div class="line"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
  return `<div class="list">${metrics}</div><p class="meta">${esc(ta.note || "")}</p>`;
}

function renderNewsReview() {
  const nr = state.data.news_review || {};
  const metrics = [
    ["Kandidaten", nr.count || 0],
    ["Promote-Vorschlag", nr.promote_suggested || 0],
  ].map(([l, v]) => `<div class="line"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
  const queue = nr.queue || [];
  const queueHtml = queue.length ? `
    <details class="drilldown compact"><summary>Queue (${esc(queue.length)})</summary>
      <div class="drill-list compact">${queue.slice(0, 15).map((q) => {
        const who = (q.players && q.players.length) ? esc(q.players.join(", ")) : `<i>kein Spieler${q.no_player_subject ? " (pruefen!)" : ""}</i>`;
        const sug = q.suggested === "promote" ? '<span class="badge stabil">promote</span>' : '<span class="badge warte">watch</span>';
        return `<div><b>${esc(q.title || "")}</b> ${sug}<br><span class="meta">${esc((q.teams || []).join(", "))} · ${who} · ${esc(q.severity || "")} · <code>${esc(q.id)}</code></span></div>`;
      }).join("")}</div></details>` : `<p class="meta">Keine offenen Kandidaten.</p>`;
  return `<div class="list">${metrics}</div>${queueHtml}<p class="meta">Human-in-the-loop: <code>news-review --promote &lt;id&gt;</code> (-> manual_news.json) oder <code>--dismiss &lt;id&gt;</code>. Spielerlose Items (Referee-Klasse) i.d.R. dismissen.</p>`;
}

function renderLineupLock() {
  const ll = state.data.lineup_lock || {};
  const metrics = [
    ["Im Fenster", ll.in_window || 0],
    ["Lockable (bestaetigte XI)", `<span class="badge ${(ll.lockable || 0) > 0 ? "stabil" : "warte"}">${ll.lockable || 0}</span>`],
    ["Wartet auf Lineup", ll.waiting_for_lineup || 0],
    ["Nachtspiele", ll.night_matches || 0],
  ].map(([l, v]) => `<div class="line"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
  const matches = ll.matches || [];
  const mHtml = matches.length ? `
    <details class="drilldown compact"><summary>Spiele im Fenster (${esc(matches.length)})</summary>
      <div class="drill-list compact">${matches.map((m) => `
        <div><b>${esc(m.home)} - ${esc(m.away)}</b> ${m.lockable ? '<span class="badge stabil">lockable</span>' : '<span class="badge warte">warte</span>'}${m.is_night_match ? ' <span class="badge volatil">Nacht</span>' : ""}<br>
        <span class="meta">${esc(m.home_lineup)} / ${esc(m.away_lineup)} · Tipp ${esc(m.tip_primary || "-")}</span></div>`).join("")}</div></details>` : `<p class="meta">Aktuell kein Spiel im ${esc(ll.window_minutes || 90)}-min-Fenster.</p>`;
  return `<div class="list">${metrics}</div>${mHtml}<p class="meta">${esc(ll.note || "")} <code>lineup-lock</code>.</p>`;
}

function renderRoleAb() {
  const ab = state.data.role_ab || {};
  const meta = ab._meta || {};
  if (!meta.summary) {
    return `<div class="empty">Noch kein Rollen-A/B. <code>PYTHONPATH=src python3 -m wm_tipps.cli role-ab</code> ausfuehren.</div>`;
  }
  const cls = (meta.net_delta || 0) > 0 ? "stabil" : (meta.net_delta || 0) < 0 ? "volatil" : "warte";
  const metrics = [
    ["Gewertete Tipps", meta.settled_slots || 0],
    ["Abweichend (role-aware vs role-off)", meta.differing_tips || 0],
    ["treatment / control", `${fmtValue(meta.treatment_points)} / ${fmtValue(meta.control_points)}`],
    ["Netto durch Rollen", `<span class="badge ${cls}">${meta.net_delta >= 0 ? "+" : ""}${fmtValue(meta.net_delta)}</span>`],
  ].map(([label, value]) => `<div class="line"><span>${esc(label)}</span><b>${value}</b></div>`).join("");
  const movers = (ab.movers || []).slice(0, 8);
  const moversHtml = movers.length ? `
    <details class="drilldown compact">
      <summary>Abweichende Spiele (${esc((ab.movers || []).length)})</summary>
      <div class="drill-list compact">${movers.map((m) => `
        <div><b>${esc(m.match)} · ${esc(m.round_id)}</b><br>
        <span class="meta">Ergebnis ${esc(m.actual)} · role-aware ${esc(m.treatment_tip)} (${esc(m.treatment_points)}) vs role-off ${esc(m.control_tip)} (${esc(m.control_points)}) · Delta ${esc(m.delta)}</span></div>
      `).join("")}</div>
    </details>` : "";
  return `
    <p class="meta">${esc(meta.summary)}</p>
    <div class="list">${metrics}</div>
    ${moversHtml}
    <p class="meta">Forward-A/B auf echten Spielen. Ergebnisse ab Anstoss in <code>data/manual_results.json</code> pflegen.</p>
  `;
}

function renderLiveEval() {
  const ev = state.data.live_eval || {};
  const meta = ev._meta || {};
  if (!ev._meta || !(meta.matches_evaluated)) {
    const pend = meta.results_pending || 0;
    return `<div class="empty">Noch keine ausgewerteten Spiele${pend ? ` (${pend} gespielt, Ergebnis fehlt)` : ""}. <code>PYTHONPATH=src python3 -m wm_tipps.cli eval-live</code></div>`;
  }
  const metrics = [
    ["Ausgewertete Spiele", meta.matches_evaluated || 0],
    ["Gespielt, Ergebnis offen", meta.results_pending || 0],
    ["Live beste Quelle (Brier)", `<b>${esc(meta.best_calibrated_source || "-")}</b>`],
  ].map(([label, value]) => `<div class="line"><span>${esc(label)}</span><b>${value}</b></div>`).join("");
  const rounds = Object.entries(ev.rounds || {}).map(([rid, r]) =>
    `<div class="line"><span>${esc(rid)}</span><b>${esc(r.points_per_match)}/Spiel <span class="meta">(erw. ${esc(r.mean_expected_points)})</span></b></div>`
  ).join("");
  const calib = Object.entries(ev.calibration || {}).filter(([, c]) => c.matches).map(([src, c]) => {
    const best = src === meta.best_calibrated_source;
    return `<div class="line"><span>${esc(src)} ${best ? '<span class="badge stabil">best</span>' : ""}</span><b>Brier ${esc(c.mean_brier)} · LogLoss ${esc(c.mean_logloss)}</b></div>`;
  }).join("");
  const totals = ev.totals ? `<p class="meta">Tor-Inflation: beobachtet ${esc(ev.totals.observed_goals)} vs Modell ${esc(ev.totals.model_expected_goals)} Tore — theta ${esc(ev.totals.inflation_theta)} (${esc(ev.totals.note)})</p>` : "";
  const drift = ev.drift ? `<p class="meta">Drift: live ${esc(ev.drift.live_ppm)}/Spiel vs Backtest ${esc(ev.drift.backtest_ppm)} (${ev.drift.delta >= 0 ? "+" : ""}${esc(ev.drift.delta)}) — ${esc(ev.drift.note)}</p>` : "";
  const games = (ev.matches || []).slice(-8).map((m) => {
    const pts = Object.entries(m.rounds || {}).map(([rid, r]) => `${esc(rid.split("-")[0])} ${esc(r.tip)}=${esc(r.points)}`).join(" · ");
    return `<div><b>${esc(m.match)}</b> <span class="meta">${pts}</span></div>`;
  }).join("");
  const gamesHtml = games ? `<details class="drilldown compact"><summary>Spiele (${esc((ev.matches || []).length)})</summary><div class="drill-list compact">${games}</div></details>` : "";
  return `
    <div class="list">${metrics}</div>
    <p class="meta">Erzielte Punkte je Runde:</p>
    <div class="list">${rounds}</div>
    <p class="meta">Probabilistische Guete (niedriger = besser):</p>
    <div class="list">${calib}</div>
    ${totals}
    ${drift}
    ${gamesHtml}
    <p class="meta">Read-only. Bewertet die Modell-Tipps gegen echte Ergebnisse aus <code>data/manual_results.json</code> (auto-geholt).</p>
  `;
}

function renderNewsAudit() {
  const audit = state.data.news_audit || {};
  const meta = audit._meta || {};
  if (!audit._meta) {
    return `<div class="empty">Noch kein News-Audit. <code>PYTHONPATH=src python3 -m wm_tipps.cli news-audit</code> ausfuehren.</div>`;
  }
  const flaggedCls = (meta.flagged_team_items || 0) > 0 ? "volatil" : "stabil";
  const metrics = [
    ["Teams mit News-Effekt", `${meta.teams_with_effect || 0} / ${meta.fixture_teams_scanned || 0}`],
    ["Multi-Team-Items (Risiko)", meta.risk_items || 0],
    ["markierte (Team, Item)", `<span class="badge ${flaggedCls}">${meta.flagged_team_items || 0}</span>`],
    ["stale (ignoriert)", meta.stale_impact_items || 0],
  ].map(([label, value]) => `<div class="line"><span>${esc(label)}</span><b>${value}</b></div>`).join("");
  const teams = audit.teams || [];
  const teamsHtml = teams.length ? `<div class="list">${teams.map((t) => {
    const flags = (t.items || []).flatMap((i) => i.flags || []);
    const flagBadge = flags.length ? ` <span class="badge volatil">${esc(flags.join(", "))}</span>` : "";
    const titles = (t.items || []).map((i) => esc(i.title)).join(" · ");
    return `<div class="line"><div><b>${esc(t.team)}</b><br><span class="meta">${titles}</span></div><div>attack ${esc(t.attack_delta)} / def ${esc(t.defense_delta)}${flagBadge}</div></div>`;
  }).join("")}</div>` : `<p class="meta">Kein Team hat aktuell einen News-xG-Effekt.</p>`;
  const risk = audit.risk_items || [];
  const riskHtml = risk.length ? `
    <details class="drilldown compact">
      <summary>Multi-Team-Items (${esc(risk.length)})</summary>
      <div class="drill-list compact">${risk.map((r) => `
        <div><b>${esc(r.title)}</b><br><span class="meta">${(r.decisions || []).map((d) => `${esc(d.team)}=${esc(d.action)}`).join(", ")}</span></div>
      `).join("")}</div>
    </details>` : "";
  return `
    <div class="list">${metrics}</div>
    ${teamsHtml}
    ${riskHtml}
    <p class="meta">Read-only Diagnose. FLAG = pruefen: <code>multi_team</code> (Sammelartikel) oder <code>subject_in_other_pool</code> (Spieler gehoert laut Pool einem anderen Team). News-Modell-Logik ist Codex' Domain.</p>
  `;
}

function renderStrategyAb() {
  const ab = state.data.strategy_ab || {};
  const meta = ab._meta || {};
  if (!ab._meta) {
    return `<div class="empty">Noch kein Aggressivitaets-A/B. <code>PYTHONPATH=src python3 -m wm_tipps.cli strategy-ab</code> ausfuehren.</div>`;
  }
  const bt = (ab.backtest || {})[defaultRoundId()] || {};
  const rows = Object.values(bt).map((r) => {
    const best = r.kappa === meta.backtest_best_kappa;
    const tag = r.kappa === 1.0 ? '<span class="badge stabil">live</span>' : (best ? '<span class="badge volatil">best</span>' : "");
    return `<div class="line"><span>kappa ${esc(r.kappa)} ${tag}</span><b>${esc(r.points)} Pkt · ${esc(r.exact_hits)} exakt · ${esc(r.mean_tip_goals)} Tore/Tipp</b></div>`;
  }).join("");
  return `
    <p class="meta"><b>${esc(meta.verdict)}</b> (${esc(meta.backtest_matches)} Backtest-Spiele)</p>
    <div class="list">${rows}</div>
    <p class="meta">kappa inflationiert die xG vor der EP-Maximierung (1.0 = aktuell, &gt;1 = aggressiver/hoehere Scorelines). Konservativ gewinnt auf Punkten UND Exakt-Treffern -> Live-Tipp bleibt; mehr Varianz nur als Endspiel-Chase-Taktik bei Rueckstand (T-0075).</p>
  `;
}

function renderRiskDial() {
  // Ohne Pool-Analytik (oeffentlicher Build) gibt es diesen Block nicht.
  if (!state.data.risk_dial) return "";
  const rd = state.data.risk_dial || {};
  const meta = rd._meta || {};
  if (!rd._meta) {
    return `<div class="empty">Noch kein Risk-Dial. <code>PYTHONPATH=src python3 -m wm_tipps.cli risk-dial</code> ausfuehren.</div>`;
  }
  const fr = (rd.frontier || {})[defaultRoundId()] || {};
  const em = fr.ep_max || {};
  const sm = fr.sigma_max || {};
  const frontierRows = [
    ["EP-Max (live)", `${esc(em.realized_ppm)} Pkt · Std ${esc(em.realized_std)}`],
    ["Sigma-Max (Aggression max)", `${esc(sm.realized_ppm)} Pkt · Std ${esc(sm.realized_std)}`],
  ].map(([l, v]) => `<div class="line"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
  const lv = (rd.live || {})[defaultRoundId()] || {};
  let liveHtml = "";
  if (lv.played) {
    const ranks = Object.values(lv.our_by_kappa || {})
      .map((r) => `kappa ${esc(r.kappa)} → Rang ${esc(r.rank)} (${esc(r.points)} Pkt)`)
      .join(" · ");
    liveHtml = `<p class="meta">Live-Counterfactual (${esc(lv.played)} Spiele, Feld ${esc(lv.field_size)}): ${ranks}.</p>`;
  }
  return `
    <p class="meta"><b>${esc(meta.verdict)}</b></p>
    <div class="list">${frontierRows}</div>
    <p class="meta">Flip-Rate ${esc((fr.flip_rate * 100).toFixed(0))}% · Std-Gewinn fuer max Varianz <b>${esc(fr.std_gain_for_max_variance)}</b> · EP-Preis <b>${esc(fr.ep_cost_for_max_variance)}</b> Pkt/Spiel. In Kicktipps 0/2/3/4-Wertung ist der EP-Max-Tipp schon nahe varianz-maximal -> kein nutzbarer Chase-Hebel (T-0075).</p>
    ${liveHtml}
  `;
}

function renderFavoriteCalibration() {
  const fc = state.data.favorite_host_calibration || {};
  const meta = fc._meta || {};
  if (!fc._meta) {
    return `<div class="empty">Noch keine Favoriten-/Gastgeber-Kalibrierung. <code>PYTHONPATH=src python3 -m wm_tipps.cli favorite-calibration</code> ausfuehren.</div>`;
  }
  const fav = fc.favorites || {};
  const binRows = (fav.bins || []).map((b) => {
    const mkt = b.market_pred == null ? "-" : esc(b.market_pred);
    return `<div class="line"><span>Fav ${esc(b.bin)} (${esc(b.matches)})</span><b>real ${esc(b.actual_fav_winrate)} · Modell ${esc(b.model_pred)} · Markt ${mkt}</b></div>`;
  }).join("");
  const host = fc.hosts || {};
  let hostHtml = "";
  if (host.matches) {
    hostHtml = `<p class="meta">Gastgeber (${esc(host.matches)} Spiele): real ${esc(host.actual_host_winrate)}, Modell ohne Bonus ${esc(host.model_pred_no_bonus)}, mit +0.18 ${esc(host.model_pred_with_bonus_018)}. Roh-Effekt <b>${esc(host.raw_host_effect)}</b>, Rest nach +0.18 <b>${esc(host.residual_after_bonus)}</b>.</p>`;
  }
  return `
    <p class="meta"><b>${esc(meta.verdict)}</b> (${esc(meta.backtest_matches)} Spiele)</p>
    <div class="list">${binRows}</div>
    <p class="meta">Gap Modell <b>${esc(fav.mean_gap_model)}</b> · Ensemble ${esc(fav.mean_gap_ensemble)} · Markt ${esc(fav.mean_gap_market == null ? "-" : fav.mean_gap_market)} (&gt;0 = Realrate ueber Prognose = under-confident). Der 80/20-Blend korrigiert teilweise (T-0084).</p>
    ${hostHtml}
  `;
}

function renderRivalProfiles() {
  // Ohne Pool-Analytik (oeffentlicher Build) gibt es diesen Block nicht.
  if (!state.data.rival_profiles) return "";
  const rp = state.data.rival_profiles || {};
  const meta = rp._meta || {};
  if (!rp._meta) {
    return `<div class="empty">Noch keine Rivalen-Profile. <code>PYTHONPATH=src python3 -m wm_tipps.cli rival-profiles</code> ausfuehren.</div>`;
  }
  const PROFILE_LIMIT = 50;
  const sections = roundList().map(([rid, label]) => {
    const limit = PROFILE_LIMIT;
    const rd = (rp.rounds || {})[rid] || {};
    if (!rd.profiles || !rd.profiles.length) return "";
    const rows = rd.profiles.slice(0, limit).map((p) => {
      const sim = p.model_similarity == null ? "-" : esc(p.model_similarity);
      return `<div class="line"><span>${esc(p.name)} <small>(${esc(p.tips)}T)</small></span><b>${esc(p.points)} Pkt · Remis ${esc(p.draw_rate)} · Tore/Tipp ${esc(p.mean_tip_goals)} · ModAehnl ${sim} · Exakt ${esc(p.exact_rate)}</b></div>`;
    }).join("");
    return `
      <h3>${esc(label)} <small>(${esc(rd.players)} Spieler)</small></h3>
      <p class="meta">Feld-Remis ${esc(rd.field_draw_rate)} · Feld-Tore/Tipp ${esc(rd.field_mean_tip_goals)} · Korr(Aggressivitaet, Pkt) ${esc(rd.aggressiveness_points_corr)} (n=${esc(rd.reliable_players)})</p>
      <div class="list">${rows}</div>`;
  }).join("");
  return `
    <p class="meta"><b>${esc(meta.verdict)}</b></p>
    ${sections}
    <p class="meta">(NT) = Anzahl getippter Spiele. model_similarity = Anteil Tipps == unser EP-Max-Modell. Abdeckung pro Spieler noch uneven (nur fotografierte Spalten). KO-Taktik-Tool (gegen EINEN konkreten Rivalen) folgt, sobald mehr Spieltage erfasst sind (T-0080).</p>
  `;
}

function renderDeficitPolicy() {
  // Ohne Pool-Analytik (oeffentlicher Build) gibt es diesen Block nicht.
  if (!state.data.deficit_policy) return "";
  const dp = state.data.deficit_policy || {};
  const meta = dp._meta || {};
  if (!dp._meta) {
    return `<div class="empty">Noch keine Deficit-Policy. <code>PYTHONPATH=src python3 -m wm_tipps.cli deficit-policy</code> ausfuehren.</div>`;
  }
  const regimeBadge = (reg) =>
    reg === "chase" ? '<span class="badge volatil">CHASE</span>'
    : reg === "protect" ? '<span class="badge stabil">Cover</span>'
    : reg === "neutral" ? '<span class="badge stabil">EP-Max</span>' : esc(reg);
  const sections = roundList().map(([rid, label]) => {
    const rd = (dp.rounds || {})[rid] || {};
    const recs = (rd.upcoming || []).filter((r) => r.deviates_from_ep).slice(0, 8);
    const devRows = recs.length
      ? recs.map((r) => `<div class="line"><span>${esc(r.match)}</span><b>EP ${esc(r.ep_tip)} → <span style="color:var(--warn)">${esc(r.policy_tip)}</span></b></div>`).join("")
      : `<p class="meta">Keine Abweichung vom EP-Tipp in diesem Regime.</p>`;
    return `
      <h3>${esc(label)} ${regimeBadge(rd.regime)}</h3>
      <p class="meta">Rückstand D=${esc(rd.deficit)} (Rang ${esc(rd.my_rank)}/${esc(rd.field_size)}) · M=${esc(rd.matches_left)} · Schwelle ${esc(rd.chase_threshold)} · ${esc(rd.deviations)} Abweichungen vom EP-Tipp</p>
      <div class="list">${devRows}</div>`;
  }).join("");
  return `
    <p class="meta"><b>${esc(meta.verdict)}</b></p>
    ${sections}
    <p class="meta">EP-Max bleibt Default. Regime: vorn=Cover (Feld spiegeln), weit zurück+spät=CHASE (vom Feld dekorrelieren), sonst EP-Max. Schwelle D&gt;1.5·√M. M zählt offene Gruppen-Fixtures (K.o. noch nicht enthalten) → Grenze konservativ. Quelle: Platz-1-Sim T-0100.</p>
  `;
}

function renderCalibrateFit() {
  const cf = state.data.calibration_fit || {};
  const m = cf._meta || {};
  if (!cf._meta) {
    return `<div class="empty">Noch kein Kalibrier-Fit. <code>PYTHONPATH=src python3 -m wm_tipps.cli calibrate-fit</code> ausfuehren.</div>`;
  }
  const rows = [
    ["Temperatur T*", `${esc(m.best_temperature)} (${esc(m.within_class_sharpness)})`],
    ["Dixon-Coles rho*", `${esc(m.best_rho)} (${esc(m.rho_reading)})`],
    ["Markt-Blend w* (Likelihood)", `${esc(m.best_blend_weight)} · live ${esc(m.live_blend_weight)}`],
  ].map(([label, value]) => `<div class="line"><span>${esc(label)}</span><b>${value}</b></div>`).join("");
  return `
    <div class="list">${rows}</div>
    <p class="meta">Offline auf ${esc(m.matches)} Backtest-Spielen. T*=1.0 &amp; rho*=0.0 -> Modell ist innerhalb der Ergebnis-Klasse bereits gut kalibriert (keine Recalibration noetig). Die Likelihood favorisiert mehr Marktgewicht -> live jetzt 0.20 (T-0079).</p>
  `;
}

function renderBlendSweep() {
  const sweep = state.data.blend_sweep || {};
  const weights = sweep.weights || [];
  if (!weights.length) {
    return `<div class="empty">Noch kein Blend-Sweep. <code>PYTHONPATH=src python3 -m wm_tipps.cli blend-sweep</code> ausfuehren.</div>`;
  }
  const meta = sweep._meta || {};
  const maxPpm = Math.max(...weights.map((w) => w.points_per_match || 0));
  const rows = weights.map((w) => {
    const best = (w.points_per_match || 0) === maxPpm;
    const tag = w.is_current ? '<span class="badge stabil">live</span>' : (best ? '<span class="badge volatil">best</span>' : "");
    return `<div class="line"><span>${Math.round((w.market_weight || 0) * 100)}% Markt ${tag}</span><b>${fmtValue(w.points)} (${fmtValue(w.points_per_match)}/Spiel)</b></div>`;
  }).join("");
  return `
    <p class="meta">${esc(meta.summary || "")}</p>
    <div class="list">${rows}</div>
    <p class="meta">Live ${esc(meta.current_weight)} vs bestes ${esc(meta.best_weight)} (Delta ${esc(meta.best_minus_current_ppm)}/Spiel auf ${esc(meta.matches)} Spielen). Flaches Plateau -> Gewicht ist unkritisch; 0.35-Spitze ist Rauschen, nicht jagen.</p>
  `;
}

function renderContextAblation() {
  const ablation = state.data.context_ablation || {};
  const effects = ablation.effects || [];
  if (!effects.length) {
    return `<div class="empty">Noch keine Kontext-Ablation. <code>PYTHONPATH=src python3 -m wm_tipps.cli context-ablation</code> ausfuehren.</div>`;
  }
  const meta = ablation._meta || {};
  const rows = effects.map((item) => `
    <div class="line">
      <div><b>${esc(item.label)}</b><br><span class="meta">${esc(item.fixtures_affected)} Spiele · mittl. |dxg| ${esc(item.mean_abs_xg)} · max ${esc(item.max_abs_xg)}</span></div>
      <div><span class="badge ${item.tip_changes_total ? "volatil" : "stabil"}">${esc(item.tip_changes_total)} Tippwechsel</span></div>
    </div>`).join("");
  const movers = effects.flatMap((item) => (item.changed_fixtures || []).map((change) => ({ label: item.label, ...change })));
  const moversHtml = movers.length ? `
    <details class="drilldown compact">
      <summary>Tatsaechliche Tippwechsel (${esc(movers.length)})</summary>
      <div class="drill-list compact">${movers.map((change) => `
        <div><b>${esc(change.label)} · ${esc(change.match)}</b><br>
        <span class="meta">${esc(change.round_id)} · mit ${esc(change.with_effect_tip)} (EP ${esc(change.ep_with)}) → ohne ${esc(change.without_effect_tip)} (EP ${esc(change.ep_without)})</span></div>
      `).join("")}</div>
    </details>` : "";
  return `
    <p class="meta">${esc(meta.summary || "")}</p>
    <div class="list">${rows}</div>
    ${moversHtml}
    <p class="meta">Diagnose: je Effekt das xG-Delta entfernen und den Tipp neu rechnen. Veraendert keine Tipps.</p>
  `;
}

function renderBacktestWorth() {
  const report = state.data.backtest_report || {};
  const verdict = report.verdict || {};
  const combined = report.combined || {};
  const calibration = report.score_calibration || {};
  const calibrationVariants = calibration.variants || {};
  const oddsCalibration = calibrationVariants.odds_draw_total || {};
  const marketScoreCalibration = calibrationVariants.odds_market_score_v1 || {};
  const ensembleCalibration = calibrationVariants.ensemble_current_15 || {};
  const disagreement = calibration.market_score_disagreement || {};
  const disagreementHelped = disagreement.helped || {};
  const disagreementHurt = disagreement.hurt || {};
  const marketCalibrator = calibration.market_score_calibrator || {};
  const marketCoverage = marketCalibrator.historical_coverage || {};
  const marketImport = marketCalibrator.historical_import || {};
  const marketImportCoverage = marketImport.coverage || {};
  const marketSourceAudit = marketCalibrator.source_audit || {};
  // Fairer Vergleich nur auf den Spielen mit Quoten (gleicher Nenner);
  // Fallback auf combined fuer aeltere Reports ohne odds_covered.
  const fair = report.odds_covered && report.odds_covered.matches
    ? report.odds_covered
    : combined;
  const fairVariants = fair.variants || {};
  const ensemble = fairVariants.ensemble || {};
  const odds = fairVariants.odds || {};
  const best = combined.best_variant || {};
  const worst = combined.worst_variant || {};
  if (!verdict.status || !combined.matches) {
    return `<div class="empty">Noch kein Ablation-Report. <code>PYTHONPATH=src python3 -m wm_tipps.cli backtest-report</code> ausfuehren.</div>`;
  }
  const cls = verdict.status === "keep_full_intelligence"
    ? "stabil"
    : verdict.status === "simplify_to_odds_plus_watch" ? "volatil" : "warte";
  const delta = ensemble.delta_vs_odds_ppm;
  const metrics = [
    ["Verdict", `<span class="badge ${cls}">${esc(verdict.status)}</span>`],
    ["Spiele gesamt", combined.matches],
    ["davon mit Quoten", fair.matches],
    ["Ensemble (Quoten-Set)", `${fmtValue(ensemble.points)} (${fmtValue(ensemble.points_per_match)}/Spiel)`],
    ["Odds-only (Quoten-Set)", `${fmtValue(odds.points)} (${fmtValue(odds.points_per_match)}/Spiel)`],
    ["Delta/Spiel", delta === null || delta === undefined ? "n/a" : Number(delta).toFixed(3)],
    calibration.matches ? ["Score-Kalibrierung", `${fmtValue(oddsCalibration.delta_vs_legacy_points)} Odds-Punkte vs alt · ${fmtValue(ensembleCalibration.delta_vs_legacy_points)} Ensemble-Punkte vs alt`] : null,
    marketScoreCalibration.matches ? ["Zusatzmarkt-Backtest", `${fmtValue(marketScoreCalibration.points)} Punkte · ${fmtValue(marketScoreCalibration.delta_vs_draw_total_points)} vs 1X2-only · ${fmtValue(marketScoreCalibration.extra_market_matches)} Spiele mit Zusatzsignal`] : null,
    disagreement.differing_tips ? ["Zusatzmarkt-Disagreement", `netto ${fmtValue(disagreement.net_points)} · +${fmtValue(disagreementHelped.points)}/${fmtValue(disagreementHelped.games)} Spiele, ${fmtValue(disagreementHurt.points)}/${fmtValue(disagreementHurt.games)} · ${fmtValue(disagreement.neutral_tip_changes)} punktneutral`] : null,
    marketCalibrator.status ? ["Zusatzmarkt-Coverage", `O/U ${fmtValue(marketCoverage.over_under)} · BTTS ${fmtValue(marketCoverage.btts)} · Handicap ${fmtValue(marketCoverage.handicap)}`] : null,
    marketImport.status ? ["Historischer Import", `${fmtValue(marketImportCoverage.matches)} Spiele · Quellen ${fmtValue(marketSourceAudit.accepted_sources_count)}/${fmtValue(marketSourceAudit.searched_sources_count)}`] : null,
    ["Beste Variante", renderVariantMetric(best)],
    ["Schlechteste", renderVariantMetric(worst)],
  ].filter(Boolean).map(([label, value]) => `<div class="line"><span>${esc(label)}</span><b>${value}</b></div>`).join("");
  const differing = (combined.ensemble_odds_differing_matches || []).slice(0, 6);
  const diffHtml = differing.length ? `
    <details class="drilldown compact">
      <summary>Abweichende Tipps (${esc(combined.head_to_head?.ensemble_vs_odds?.differing_tips || differing.length)})</summary>
      <div class="drill-list compact">${differing.map((row) => `
        <div><b>${esc(row.tournament)} · ${esc(row.match)}</b><br>
        <span class="meta">Ergebnis ${esc(row.actual)} · Ensemble ${esc(row.ensemble_tip)} (${esc(row.ensemble_points)}) · Odds ${esc(row.odds_tip)} (${esc(row.odds_points)}) · Delta ${esc(row.point_delta)}</span></div>
      `).join("")}</div>
    </details>` : "";
  return `
    <div class="list">${metrics}</div>
    <p class="meta">${esc(verdict.summary || "")}</p>
    ${calibration.summary ? `<p class="meta">${esc(calibration.summary)}</p>` : ""}
    ${marketCalibrator.summary ? `<p class="meta">${esc(marketCalibrator.summary)}</p>` : ""}
    <p class="meta">${esc(verdict.caveat || "")}</p>
    ${diffHtml}
  `;
}

function renderVariantMetric(row) {
  if (!row || !row.name) return "n/a";
  return `${esc(row.name)} · ${esc(fmtValue(row.points))} Punkte · ${esc(fmtValue(row.points_per_match))}/Spiel`;
}

// Bonus hat keinen eigenen Tab mehr: die Fragen werden einmal zu
// Turnierbeginn getippt und gehoeren damit zu den finalen Tipps.
function bonusHtml() {
  const bonus = state.data.bonus || {};
  return `
    <h2 class="section-head">Bonusfragen</h2>
    <div class="grid">
      ${renderBonusList("Weltmeister", bonus.world_champion || [])}
      ${renderBonusList("Halbfinalisten", bonus.semifinalists || [])}
      ${renderGroupWinners(bonus.group_winners || {})}
      ${renderBonusList("Team Torschuetzenkoenig", bonus.top_scorer_team || [])}
    </div>`;
}

function renderBonusList(title, rows) {
  const filtered = rows.filter((row) => matchesSearch(`${row.team || ""}`)).slice(0, 10);
  return `<section class="card"><h2>${esc(title)}</h2><div class="list">${filtered.map((row) => `
    <div class="line"><span>${esc(row.team)}</span><b>${fmtPct(row.probability)}</b></div>`).join("") || `<div class="empty">Keine Daten.</div>`}</div></section>`;
}

function renderGroupWinners(groups) {
  const rows = Object.entries(groups || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([group, ranking]) => {
      const top = state.search
        ? (ranking || []).find((row) => matchesSearch(`${group} ${row.team || ""}`))
        : (ranking || [])[0];
      return top ? { group, ...top } : null;
    })
    .filter(Boolean);
  return `<section class="card"><h2>Gruppensieger A-L</h2><div class="list">${rows.map((row) => `
    <div class="line"><span>Gruppe ${esc(row.group)} · ${esc(row.team)}</span><b>${fmtPct(row.probability)}</b></div>`).join("") || `<div class="empty">Keine Daten.</div>`}</div></section>`;
}

// Die Watchlist-TABELLE ist entfallen (T-0169): sie enthielt keine
// Information, die nicht in der Spiele-Karte oder in der News-Tabelle
// steht -- ihr Wert lag allein in der Vorauswahl, und die griff zuletzt
// nicht mehr (104 von 104 Spielen). Das Matchday Command Center ist
// dagegen einzigartig und lebt unter "Analyse" weiter.
function matchdaySections() {
  return renderMatchdayCommandCenter() + renderMatchdayDryRun();
}

function renderMatchdayCommandCenter() {
  const command = state.data.matchday_command || {};
  const summary = command.summary || {};
  if (!summary.matches) {
    return `<section class="card"><h2>Matchday Command Center</h2><div class="empty">Noch kein Command Center. <code>PYTHONPATH=src python3 -m wm_tipps.cli matchday-command</code> ausfuehren.</div></section>`;
  }
  const metrics = [
    ["Fokus", summary.focus_items || 0],
    ["Kritisch", summary.critical || 0],
    ["Warte Lineup", summary.waiting_lineup || 0],
    ["Faellig", summary.open_due || 0],
    ["Naechster Check", fmtDate(summary.next_check_at)],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const focusRows = (command.today_items || []).filter((row) => matchesSearch(`${row.match || ""} ${(row.reasons || []).join(" ")} ${row.status || ""}`));
  const nextRows = (command.next_items || []).filter((row) => matchesSearch(`${row.match || ""} ${row.status || ""}`)).slice(0, 8);
  const focusHtml = focusRows.length
    ? `<div class="drill-list compact">${focusRows.map(renderCommandRow).join("")}</div>`
    : `<div class="empty">Heute keine faelligen Fokus-Checks fuer den Filter.</div>`;
  const nextHtml = nextRows.length
    ? `<details class="drilldown compact"><summary>Naechste Checks</summary><div class="drill-list compact">${nextRows.map(renderCommandRow).join("")}</div></details>`
    : "";
  return `
    <section class="card">
      <h2>Matchday Command Center</h2>
      <div class="metrics-row">${metrics}</div>
      ${focusHtml}
      ${nextHtml}
    </section>`;
}

function renderCommandRow(row) {
  const actions = (row.due_actions && row.due_actions.length ? row.due_actions : row.next_actions || []).slice(0, 3);
  const actionText = actions.map((action) => `${action.label || action.type} ${fmtDate(action.due_at)}`).join(" · ") || "kein Check";
  const links = (row.source_links || []).slice(0, 5).map((source) => {
    if (!source.url) return `<span class="meta">${esc(source.name || source.id)}</span>`;
    return `<a href="${esc(source.url)}" target="_blank" rel="noreferrer">${esc(source.name || source.id)}</a>`;
  }).join(" · ");
  return `
    <div>
      <div class="line">
        <div><b>${esc(row.match || "")}</b><br><span class="meta">Spiel ${esc(row.match_number || "")} · ${fmtDate(row.kickoff_utc)} · ${esc(row.venue || "")}</span></div>
        <div><span class="badge ${commandStatusClass(row.status)}">${esc(row.status || "offen")}</span></div>
      </div>
      <div class="meta">Tipp ${esc(row.tip || "n/a")} · ${esc(row.stability || "")} · ${esc(actionText)}</div>
      ${row.status_detail ? `<div class="meta">${esc(row.status_detail)}</div>` : ""}
      ${links ? `<div class="meta">Quellen: ${links}</div>` : ""}
    </div>`;
}

function renderMatchdayDryRun() {
  const report = state.data.matchday_dry_run || {};
  if (!report.status) {
    return `<section class="card"><h2>Matchday-Probelauf</h2><div class="empty">Noch kein Probelauf. <code>PYTHONPATH=src python3 -m wm_tipps.cli matchday-dry-run</code> ausfuehren.</div></section>`;
  }
  const cls = report.status === "pass" ? "stabil" : "warte";
  const target = report.target_match || {};
  const checks = (report.checks || []).map((check) => {
    const checkCls = check.status === "pass" ? "stabil" : "warte";
    return `<div class="line"><span>${esc(check.id || "")}</span><b><span class="badge ${checkCls}">${esc(check.status || "")}</span></b></div>`;
  }).join("");
  const scenarios = (report.scenarios || []).map((scenario) => {
    const scenarioCls = scenario.result === "pass" ? "stabil" : "warte";
    const due = (scenario.due_checks || []).join(", ") || "—";
    return `<div><b>${esc(scenario.label || "")}</b> <span class="badge ${scenarioCls}">${esc(scenario.result || "")}</span><br><span class="meta">${esc(scenario.status || "")} · ${esc(due)}</span></div>`;
  }).join("");
  return `
    <section class="card">
      <h2>Matchday-Probelauf</h2>
      <div class="line">
        <div><b>${esc(target.match || "n/a")}</b><br><span class="meta">${fmtDate(target.kickoff_utc)} · ${esc(target.venue || "")}</span></div>
        <div><span class="badge ${cls}">${esc(report.status)}</span></div>
      </div>
      <div class="list compact">${checks}</div>
      ${scenarios ? `<details class="drilldown compact"><summary>Simulierte Fenster</summary><div class="drill-list compact">${scenarios}</div></details>` : ""}
    </section>`;
}

function renderSnapshot(title, snapshot, match) {
  if (!snapshot) return `<section><h3>${esc(title)}</h3><p class="meta">Kein Snapshot gespeichert.</p></section>`;
  const teams = String(match || "").split(" - ");
  const home = teams[0] || "Heim";
  const away = teams[1] || "Auswaerts";
  const probs = snapshot.probabilities?.blended || {};
  const xg = snapshot.xg || {};
  const strength = snapshot.strength || {};
  const homeStrength = strength.home || {};
  const awayStrength = strength.away || {};
  const topScores = (snapshot.top_scores || []).slice(0, 4).map((score) => `${esc(score.score)} ${fmtPct1(score.probability)}`).join(" · ");
  const contextFlags = (snapshot.context?.flags || []).join(", ") || "-";
  return `
    <section>
      <h3>${esc(title)}</h3>
      <p class="meta">Tipp ${esc(snapshot.recommended_tip?.tip || "n/a")} · Status ${esc(snapshot.stability || "n/a")}</p>
      <div class="drill-list">
        <div><b>xG</b> ${esc(home)} ${esc(fmtValue(xg.home))} · ${esc(away)} ${esc(fmtValue(xg.away))}</div>
        <div><b>Wahrscheinlichkeit</b> ${esc(home)} ${fmtPct1(probs.home)} · Remis ${fmtPct1(probs.draw)} · ${esc(away)} ${fmtPct1(probs.away)}</div>
        <div><b>Top-Scores</b> ${topScores || "n/a"}</div>
        <div><b>${esc(home)}</b> Elo ${esc(fmtValue(homeStrength.elo))} · Attack ${esc(fmtValue(homeStrength.attack))} · FIFA ${esc(fmtValue(homeStrength.fifa_rank))} · Form ${esc(fmtValue(homeStrength.form_adjustment))}</div>
        <div><b>${esc(away)}</b> Elo ${esc(fmtValue(awayStrength.elo))} · Attack ${esc(fmtValue(awayStrength.attack))} · FIFA ${esc(fmtValue(awayStrength.fifa_rank))} · Form ${esc(fmtValue(awayStrength.form_adjustment))}</div>
        <div><b>Kontext</b> Flags ${esc(contextFlags)} · Heimvorteil-xG ${esc(fmtValue(snapshot.context?.home_advantage_xg))}</div>
      </div>
    </section>
  `;
}

function renderBonusTop(title, rows) {
  if (!rows || !rows.length) return `<section><h3>${esc(title)}</h3><p class="meta">Keine Daten gespeichert.</p></section>`;
  const lines = rows.map((row, idx) => `<div class="drill-row"><span>#${idx + 1}</span><b>${esc(row.team || "?")}</b><span>${fmtPct1(row.probability)}</span></div>`).join("");
  return `<section><h3>${esc(title)}</h3><div class="drill-list">${lines}</div></section>`;
}

const INPUT_LABELS = {
  strengths: "team_strength_inputs",
  player_pool: "player_pool",
  markets: "manuelle Markt-Signale",
  news: "News-Lage",
};

function renderTriggerReason(row) {
  const reasons = row.trigger_reason || [];
  if (!reasons.length) return "";
  const badges = reasons.map((r) => `<span class="badge warte">${esc(INPUT_LABELS[r] || r)}</span>`).join(" ");
  return `<div class="meta">Ursache: ${badges}</div>`;
}

function renderHistoryDetails(row) {
  const snapshot = row.snapshot || {};
  if (snapshot.kind === "bonus_ranking") {
    return `
      <details class="drilldown">
        <summary>Details</summary>
        ${renderTriggerReason(row)}
        <div class="drill-grid">
          ${renderBonusTop("Vorher (Top-5)", snapshot.from_top)}
          ${renderBonusTop("Nachher (Top-5)", snapshot.to_top)}
        </div>
      </details>
    `;
  }
  return `
    <details class="drilldown">
      <summary>Details</summary>
      <div class="drill-grid">
        ${renderSnapshot("Vorher", snapshot.from, row.match)}
        ${renderSnapshot("Nachher", snapshot.to, row.match)}
      </div>
    </details>
  `;
}

function renderHistorySummary() {
  const events = state.data.prediction_history || [];
  const updatedAt = state.data.prediction_history_updated_at;
  const youngest = events.length ? events.map((e) => e.changed_at).sort().reverse()[0] : null;
  return `
    <section class="card">
      <p class="meta">History trackt nur echte Tippwechsel oder Bonus-Favoritenwechsel zwischen aufeinanderfolgenden Builds (Diff-Log, kein Aktivitaets-Log). EP- oder Statusbewegungen ohne neues Tippergebnis erzeugen keinen Eintrag.</p>
      <div class="list">
        <div><b>Letzte Pruefung</b> ${fmtDate(updatedAt)}</div>
        <div><b>Events gesamt</b> ${esc(events.length)}</div>
        <div><b>Juengstes Event</b> ${youngest ? fmtDate(youngest) : "—"}</div>
      </div>
    </section>
  `;
}



function renderHistory() {
  const rows = (state.data.prediction_history || [])
    .filter((item) => matchesSearch(`${item.round_name || ""} ${item.kickoff_utc || ""} ${item.match} ${item.summary} ${item.trigger} ${(item.details || []).join(" ")}`))
    .filter((item) => !state.history_trigger || item.trigger === state.history_trigger);
  // Nach Spieltermin: naechstes kommendes Spiel zuerst, gespielte danach,
  // undatierte (z.B. Bonus) ans Ende.
  rows.sort(upcomingFirstComparator((row) => parseTs(row.kickoff_utc)));
  const tableHtml = rows.length ? `
    <div class="table-wrap"><table>
      <thead><tr><th>Zeit</th><th>Runde / Spieltermin</th><th>Spiel</th><th>Aenderung</th><th>Ausloeser</th><th>Details</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td>${fmtDate(row.changed_at)}</td>
          <td>${esc(row.round_name || "n/a")}<br><span class="meta">${fmtDate(row.kickoff_utc)}</span></td>
          <td>${esc(row.match)}</td>
          <td><b>${esc(row.from_tip)} -> ${esc(row.to_tip)}</b><br><span class="meta">EP ${esc(row.from_expected_points)} -> ${esc(row.to_expected_points)} · ${esc(row.from_stability)} -> ${esc(row.to_stability)}</span></td>
          <td><span class="badge ${row.trigger === "News" ? "volatil" : "warte"}">${esc(row.trigger)}</span></td>
          <td>${esc((row.details || []).join(" · "))}${renderHistoryDetails(row)}</td>
        </tr>`).join("")}</tbody>
    </table></div>` : empty("Noch keine Tipp-Aenderungen protokolliert.");
  document.getElementById("history").innerHTML = renderHistorySummary() + tableHtml;
}

function knockoutPendingText(row) {
  const match = row.match_number ? `M${row.match_number}` : "KO";
  const openGroups = Array.isArray(row.open_groups) && row.open_groups.length
    ? ` (offen: ${row.open_groups.join(", ")})`
    : "";
  const unresolved = Array.isArray(row.unresolved_groups) && row.unresolved_groups.length
    ? ` (Tie-Break offen: ${row.unresolved_groups.join(", ")})`
    : "";
  if (row.reason === "third_assignment_pending") {
    const slot = row.third_place_column ? ` fuer Slot ${row.third_place_column}` : "";
    return `${match} wartet auf beste Drittplatzierte${slot}${openGroups || unresolved}`;
  }
  if (row.reason === "slot_pending") {
    const slots = Array.isArray(row.missing_slots) && row.missing_slots.length
      ? ` ${row.missing_slots.join(", ")}`
      : "";
    return `${match} wartet auf Slot${slots}${openGroups || unresolved}`;
  }
  if (row.reason === "previous_winner_pending") {
    const refs = [row.home_from, row.away_from].filter(Boolean).map((n) => `M${n}`).join(" und ");
    return `${match} wartet auf Sieger ${refs || "der Vorrunde"}`;
  }
  if (row.reason === "semi_loser_pending") {
    const refs = [row.home_from, row.away_from].filter(Boolean).map((n) => `M${n}`).join(" und ");
    return `${match} wartet auf Verlierer ${refs || "der Halbfinals"}`;
  }
  return `${match} wartet (${row.reason || "pending"})`;
}

function renderKnockoutStatus() {
  const status = state.data.knockout_status || {};
  const pending = Array.isArray(status.pending) ? status.pending : [];
  const resolved = Array.isArray(status.resolved) ? status.resolved : [];
  const listed = Array.isArray(status.listed) ? status.listed : resolved;
  if (!pending.length && !resolved.length && !listed.length) return "";
  const listedBadges = listed.slice(0, 16)
    .map((row) => `<span class="badge ${row.has_pending_slot ? "warte" : "stabil"}">M${esc(row.match_number)} ${esc(row.match || "")}</span>`)
    .join(" ");
  const pendingRows = pending.slice(0, 12)
    .map((row) => `<div class="line"><span>${esc(knockoutPendingText(row))}</span><b><span class="badge warte">${esc(row.reason || "pending")}</span></b></div>`)
    .join("");
  const more = pending.length > 12
    ? `<div class="meta">Weitere offene KO-Spiele: ${esc(pending.length - 12)}</div>`
    : "";
  const thirdGroups = status.qualified_third_groups || "offen";
  const metrics = [
    ["Verzeichnet", listed.length || resolved.length],
    ["Sicher", resolved.length],
    ["Pending", pending.length],
    ["Beste Dritte", thirdGroups],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  return `
    <section class="card">
      <h2>KO-Status</h2>
      <div class="metrics-row">${metrics}</div>
      <div class="list">${listedBadges || '<span class="badge warte">noch keine KO-Spiele verzeichnet</span>'}</div>
      <div class="list">${pendingRows || '<div class="empty">Alle KO-Slots sind aufgeloest.</div>'}${more}</div>
    </section>`;
}

function renderTips() {
  const sourceRows = state.data.all_final_tips || state.data.final_tips || [];
  const rows = sortRows(sourceRows.filter((item) => {
    return matchesSearch(`${item.round_name || ""} ${item.round_id || ""} ${item.stage || ""} ${item.match_id || ""} ${item.match_number || ""} ${item.kickoff_utc || ""} ${item.match} ${item.status}`)
      && (!state.status || item.status === state.status)
      && (!state.round || item.round_id === state.round);
  }));
  const statusBlock = renderKnockoutStatus();
  const tableBlock = rows.length ? `
    <div class="table-wrap"><table>
      <thead><tr><th>Runde</th><th>Nr</th><th>Anpfiff</th><th>Spiel</th><th>Tipp</th><th>EP</th><th>Status</th></tr></thead>
      <tbody>${rows.map((row) => `<tr>
        <td>${esc(row.round_name || "n/a")}<br><span class="meta">${esc(row.round_id || "")} · ${esc(row.rule_summary || "")}</span></td>
        <td>${esc(row.match_number)}</td>
        <td>${fmtDate(row.kickoff_utc)}</td>
        <td>${esc(row.match)}<br><span class="meta">${esc(row.stage || "n/a")} · ${esc(row.match_id || "")}</span></td>
        <td><b>${esc(row.tip)}</b></td>
        <td>${esc(row.expected_points)}</td>
        <td><span class="badge ${statusClass(row.status)}">${esc(row.status)}</span></td>
      </tr>`).join("")}</tbody>
    </table></div>` : empty("Keine Tipps fuer den Filter.");
  document.getElementById("tips").innerHTML = statusBlock + tableBlock + bonusHtml();
}

// Die Hauptaktion sitzt in der Topbar und ist damit aus jedem Tab
// erreichbar. Status und Qualitaetswarnung stehen als Tooltip daran, die
// ausfuehrliche Fassung bleibt unter "Analyse".
function renderTopbarAction() {
  const host = document.getElementById("topbar-action");
  if (!host) return;
  const coverage = state.data.cli_ui_coverage || {};
  const updateAll = (coverage.commands || []).find((row) => row.command === "update-all");
  if (!updateAll) {
    host.innerHTML = "";
    return;
  }
  // Bewusst NICHT renderCommandAction: das liefert zusaetzlich Ergebnis
  // und Output-Drilldown und wuerde den Kopf sprengen. Hier nur der Knopf
  // plus eine einzeilige Statusangabe; das Ausfuehrliche steht unter
  // "Analyse".
  const isRunning = state.runningCommands.has("update-all");
  const updateStatus = state.data.update_all_status || {};
  const summary = updateStatus.steps_total
    ? `${updateStatus.steps_ok || 0}/${updateStatus.steps_total || 0} Schritte · ${fmtDate(updateStatus.finished_at)}`
    : "noch kein Gesamt-Update";
  host.innerHTML = `
    <button class="run-command" data-command="update-all" ${isRunning ? "disabled" : ""}>${esc(isRunning ? "Laeuft..." : (updateAll.run_label || "Alles updaten"))}</button>
    <span class="meta topbar-action__meta" title="${esc(summary)}">${esc(summary)}</span>`;
}

function pipelineSections() {
  const coverage = state.data.cli_ui_coverage || {};
  const summary = coverage.summary || {};
  const persistedRuns = (state.data.ui_command_runs && state.data.ui_command_runs.last_runs) || {};
  const updateAll = (coverage.commands || []).find((row) => row.command === "update-all");
  const updateStatus = state.data.update_all_status || {};
  const rows = (coverage.commands || []).filter((row) => {
    const haystack = `${row.command || ""} ${row.group || ""} ${row.purpose || ""} ${row.ui_section || ""} ${row.signal || ""} ${row.status || ""}`;
    return matchesSearch(haystack);
  });
  const groups = Object.entries(summary.groups || {})
    .map(([group, count]) => `<span class="badge stabil">${esc(group)} ${esc(count)}</span>`)
    .join(" ");
  const metrics = [
    ["Kommandos", summary.commands_total || rows.length],
    ["OK", summary.ok || 0],
    ["Fehlend", summary.missing || 0],
    ["Lint", `${summary.lint_issues || 0}/${summary.lint_info || 0}`],
  ].map(([label, value]) => `<div class="metric compact"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  const updateSummary = updateStatus.steps_total
    ? `${updateStatus.steps_ok || 0}/${updateStatus.steps_total || 0} Schritte · ${fmtDate(updateStatus.finished_at)}`
    : "Noch kein Gesamt-Update in dieser UI-Runner-Historie.";
  const updateQuality = renderUpdateQuality(updateStatus);
  // Der Knopf selbst sitzt in der Topbar (renderTopbarAction); hier steht
  // nur noch der ausfuehrliche Status dazu.
  const updateAction = updateAll
    ? `<div class="pipeline-primary">
        <div>
          <h3>Ein-Klick-Update</h3>
          <p class="meta">${esc(updateSummary)}</p>
          ${updateQuality}
        </div>
      </div>`
    : "";
  const table = rows.length ? `
    <div class="table-wrap compact"><table>
      <thead><tr><th>Kommando</th><th>UI-Ort</th><th>Status</th><th>Aktion</th><th>Artefakte</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td><b>${esc(row.command)}</b><br><span class="meta">${esc(row.group || "")} · ${esc(row.purpose || "")}</span></td>
          <td>${esc(row.ui_section || "")}<br><span class="meta">${esc(row.signal || "")}</span></td>
          <td><span class="badge ${cliStatusClass(row.status)}">${esc(row.status || "watch")}</span><br><span class="meta">${esc(row.status_detail || "")}</span><br><span class="meta">Stand ${fmtDate(row.updated_at)}</span></td>
          <td>${renderCommandAction(row, state.commandResults[row.command] || persistedRuns[row.command])}</td>
          <td>${renderCliArtifacts(row.artifacts || [])}</td>
        </tr>`).join("")}</tbody>
    </table></div>` : empty("Keine CLI-Kommandos fuer den Filter.");
  return `
    <section class="card">
      <h2>CLI & UI Coverage</h2>
      <div class="metrics-row">${metrics}</div>
      <div class="list">${groups || '<span class="badge warte">keine Gruppen</span>'}</div>
      ${updateAction}
    </section>
    <section class="card">
      <h2>Kommandos</h2>
      ${table}
    </section>`;
}

function renderUpdateQuality(updateStatus) {
  const fallbackFreshness = state.data.odds_freshness || {};
  const gates = (updateStatus.quality_gates || []).length
    ? updateStatus.quality_gates
    : fallbackFreshness.source
      ? [{
          name: "bwin-freshness",
          status: fallbackFreshness.status,
          message: fallbackFreshness.status_detail,
          future_matches: fallbackFreshness.future_matches,
          fresh_matches: fallbackFreshness.fresh_matches,
        }]
      : [];
  if (!gates.length && !updateStatus.quality_status) return "";
  const messages = updateStatus.quality_messages || [];
  const status = updateStatus.quality_status || fallbackFreshness.status || (updateStatus.ok ? "ok" : "failed");
  const gateBadges = gates.map((gate) => {
    const bits = [
      gate.name,
      gate.future_matches ? `${gate.fresh_matches || 0}/${gate.future_matches} frisch` : "",
      gate.csv_rows_written !== undefined ? `${gate.csv_rows_written} CSV` : "",
    ].filter(Boolean).join(" · ");
    return `<span class="badge ${qualityClass(gate.status)}" title="${esc(gate.message || "")}">${esc(bits || gate.status)}</span>`;
  }).join(" ");
  const messageHtml = messages.length
    ? `<div class="meta">${messages.slice(0, 3).map(esc).join("<br>")}</div>`
    : "";
  return `
    <div class="list">
      <span class="badge ${qualityClass(status)}">Quality ${esc(status)}</span>
      ${gateBadges}
    </div>
    ${messageHtml}`;
}

function renderCliArtifacts(artifacts) {
  if (!artifacts.length) return `<span class="meta">Live-Check, kein Datei-Artefakt.</span>`;
  return artifacts.map((artifact) => {
    const cls = artifact.exists ? "stabil" : "volatil";
    const size = artifact.exists ? `${Math.round((artifact.size_bytes || 0) / 1024)} KB` : "fehlt";
    return `<span class="badge ${cls}">${esc(artifact.path)} · ${esc(size)}</span>`;
  }).join(" ");
}

function renderCommandAction(row, result) {
  if (row.runnable === false) {
    return `<span class="badge warte">Terminal</span><br><span class="meta">${esc(row.disabled_reason || "Nicht direkt aus der UI startbar.")}</span>`;
  }
  const isRunning = state.runningCommands.has(row.command);
  const label = isRunning ? "Laeuft..." : (row.run_label || "Ausfuehren");
  const disabled = isRunning ? "disabled" : "";
  const outcome = result ? renderCommandResult(result) : `<span class="meta">Startet <code>PYTHONPATH=src python3 -m wm_tipps.cli ${esc((row.run_args || [row.command]).join(" "))}</code>.</span>`;
  return `
    <button class="run-command" data-command="${esc(row.command)}" ${disabled}>${esc(label)}</button>
    ${outcome}`;
}

function renderCommandResult(result) {
  const quality = result.quality_status || "";
  const cls = quality ? qualityClass(quality) : result.ok ? "stabil" : "volatil";
  const summary = quality === "warning"
    ? "OK mit Warnung"
    : quality === "failed"
      ? "Gate Fehler"
      : result.ok ? "OK" : `Fehler ${fmtValue(result.returncode)}`;
  const steps = result.steps_summary ? ` · Schritte ${esc(result.steps_summary)}` : "";
  const qualityMessages = Array.isArray(result.quality_messages) && result.quality_messages.length
    ? `<div class="meta">${result.quality_messages.slice(0, 3).map(esc).join("<br>")}</div>`
    : "";
  const stderr = result.stderr_tail ? `<pre class="command-output">${esc(result.stderr_tail)}</pre>` : "";
  const stdout = result.stdout_tail ? `<details class="drilldown compact"><summary>Output</summary><pre class="command-output">${esc(result.stdout_tail)}</pre></details>` : "";
  return `
    <div class="meta"><span class="badge ${cls}">${esc(summary)}</span> ${fmtDate(result.finished_at)}${steps}</div>
    ${qualityMessages}
    ${stderr}
    ${stdout}`;
}

function bindPipelineActions() {
  document.querySelectorAll(".run-command").forEach((button) => {
    button.addEventListener("click", () => runCliCommand(button.dataset.command));
  });
}

async function runCliCommand(command) {
  if (!command || state.runningCommands.has(command)) return;
  state.runningCommands.add(command);
  // Sofort neu zeichnen, damit der Knopf sichtbar in den Laufzustand
  // geht. Betrifft beide Orte: die Topbar-Aktion und die Kommando-
  // Tabelle unter "Analyse" (die renderMarkets miterzeugt).
  renderTopbarAction();
  renderMarkets();
  try {
    const response = await fetch("/api/run-command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      state.commandResults[command] = payload.result || {
        ok: false,
        returncode: response.status,
        stderr_tail: payload.error || "Command-Runner nicht erreichbar. Dashboard mit serve-dashboard starten.",
        finished_at: new Date().toISOString(),
      };
    } else {
      state.commandResults[command] = payload.result;
      await reloadDashboardData();
    }
  } catch (error) {
    state.commandResults[command] = {
      ok: false,
      returncode: null,
      stderr_tail: `Command-Runner nicht erreichbar: ${error.message}. Dashboard mit PYTHONPATH=src python3 -m wm_tipps.cli serve-dashboard --port 8002 starten.`,
      finished_at: new Date().toISOString(),
    };
  } finally {
    state.runningCommands.delete(command);
    renderAll();
  }
}

// Das Rival-Lab bringt eigene Nutzlast und eigenen Zustand mit und wird
// darum GENAU EINMAL montiert -- nicht aus renderAll heraus, sonst
// verliert es bei jedem Tastendruck in der Suche Runde und Unter-Tab.
// Fehlt die Datei (oeffentlicher Build oder noch nie gebaut), bleibt der
// Bereich mit einem Hinweis statt einer leeren Flaeche.
async function mountRivalLabPanel() {
  const host = document.getElementById("analyse-rival-lab");
  if (!host || typeof mountRivalLab !== "function") return;
  let payload = null;
  try {
    const response = await fetch("data/rival_lab.json", { cache: "no-store" });
    if (response.ok) payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!payload) {
    host.innerHTML = `<h2 class="section-head">Rival Tipp-Lab</h2>${empty(
      "Noch keine Lab-Daten. <code>python3 analysis/rival_lab.py</code> ausfuehren."
    )}`;
    return;
  }
  host.innerHTML = `
    <h2 class="section-head">Rival Tipp-Lab</h2>
    <header>
      <div class="sub" id="subline"></div>
    </header>
    <div class="bar">
      <div class="grp">
        <label>Runde</label>
        <div class="seg" id="roundSeg"></div>
      </div>
      <div class="grp">
        <label>Mindest-Tipps (Konfidenz-Filter)</label>
        <div class="slider">
          <input type="range" id="minTips" min="1" max="16" value="8" step="1">
          <span class="val" id="minTipsVal"></span>
        </div>
      </div>
      <div class="grp">
        <label>Ich bin</label>
        <div id="meBadge" style="font-weight:700;color:var(--me)"></div>
      </div>
    </div>
    <div class="tabs" id="tabs"></div>
    <div id="view"></div>
    <details class="method">
      <summary>Methodik, Datenstand &amp; Caveats</summary>
      <div class="body" id="methodBody"></div>
    </details>`;
  if (!document.getElementById("tt")) {
    const tip = document.createElement("div");
    tip.className = "tt";
    tip.id = "tt";
    document.body.appendChild(tip);
  }
  mountRivalLab(payload);
}

// Gleiches Muster wie beim Rival-Lab: eigene Nutzlast, eigener Container,
// genau einmal montiert. Das Board ist rein deskriptiv und haelt keinen
// Zustand -- der eigene Container dient hier vor allem dazu, dass
// renderMarkets es nicht bei jedem Filterwechsel ueberschreibt.
async function mountPlayerBoardPanel() {
  const host = document.getElementById("analyse-player-board");
  if (!host || typeof mountPlayerBoard !== "function") return;
  let payload = null;
  try {
    const response = await fetch("data/player_board.json", { cache: "no-store" });
    if (response.ok) payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!payload) {
    host.innerHTML = `<h2 class="section-head">Spieler-Impact-Board</h2>${empty(
      "Noch keine Board-Daten. <code>python3 analysis/wm_player_ratings.py --html</code> ausfuehren."
    )}`;
    return;
  }
  const kopf = document.createElement("h2");
  kopf.className = "section-head";
  kopf.textContent = "Spieler-Impact-Board";
  host.innerHTML = "";
  host.appendChild(kopf);
  const rumpf = document.createElement("div");
  host.appendChild(rumpf);
  mountPlayerBoard(payload, rumpf);
}

async function reloadDashboardData() {
  const response = await fetch("data/dashboard.json", { cache: "no-store" });
  if (response.ok) {
    state.data = await response.json();
  }
}

function empty(text) {
  return `<div class="empty">${esc(text)}</div>`;
}

function renderAll() {
  renderStatus();
  renderTopbarAction();
  renderMatches();
  renderNews();
  // renderMarkets befuellt seit T-0168 zwei Panels: #markets und #analyse.
  renderMarkets();
  renderHistory();
  renderTips();
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(button.dataset.tab).classList.add("active");
    updateToolbarForTab(button.dataset.tab);
    // Kachel-Ueberlauf erst messbar, wenn der Tab sichtbar ist:
    if (CLAMP_PANELS.includes(button.dataset.tab)) clampMarketCards();
  });
});

// Aufklappen/Einklappen der Kacheln (delegiert auf beide Panels, die
// welche enthalten; ueberlebt Re-Renders ueber state.expandedCards).
CLAMP_PANELS.forEach((id) => {
  const panel = document.getElementById(id);
  if (!panel) return;
  panel.addEventListener("click", (event) => {
    const btn = event.target.closest(".card__toggle");
    if (!btn) return;
    const title = btn.dataset.cardToggle;
    const card = btn.closest(".card--clamp");
    const open = !state.expandedCards.has(title);
    if (open) state.expandedCards.add(title);
    else state.expandedCards.delete(title);
    if (card) card.classList.toggle("is-open", open);
    btn.textContent = open ? "Einklappen ▴" : "Aufklappen ▾";
  });
});

updateToolbarForTab(document.querySelector(".tab.active")?.dataset.tab || "matches");

document.getElementById("search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderAll();
});

document.getElementById("status-filter").addEventListener("change", (event) => {
  state.status = event.target.value;
  renderAll();
});

document.getElementById("sort-order").addEventListener("change", (event) => {
  state.sort = event.target.value;
  renderAll();
});

document.getElementById("round-filter").addEventListener("change", (event) => {
  state.round = event.target.value;
  renderAll();
});

loadData();
